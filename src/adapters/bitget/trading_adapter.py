"""
Bitget Trading Adapter - Implements TradingPort.
"""

import uuid
from typing import Optional, TYPE_CHECKING

from src.adapters.bitget.client import BitgetClient, BitgetAPIError
from src.domain.entities.portfolio import Portfolio, PortfolioPosition
from src.domain.entities.trade_decision import (
    TradeAction,
    TradeDecision,
    TradeExecutionResult,
)
from src.domain.ports.trading_port import TradingPort
from src.infrastructure.config import Settings
from src.infrastructure.logging import get_logger

if TYPE_CHECKING:
    from src.adapters.bitget.trade_fills_cache import TradeFillsCache
    from src.domain.ports.paper_trades_port import PaperTradesPort
    from src.domain.ports.trade_outcome_port import TradeOutcomePort

logger = get_logger(__name__)


class BitgetTradingAdapter(TradingPort):
    """
    Bitget implementation of TradingPort.
    
    Handles portfolio queries and trade execution via Bitget Spot API v2.
    Supports paper trading mode for simulation.
    """
    
    def __init__(
        self,
        client: BitgetClient,
        settings: Settings,
        trade_fills_cache: Optional["TradeFillsCache"] = None,
        paper_trades_tracker: Optional["PaperTradesPort"] = None,
        trade_outcome_tracker: Optional["TradeOutcomePort"] = None,
    ):
        """
        Initialize adapter.
        
        Args:
            client: Bitget HTTP client
            settings: Application settings
            trade_fills_cache: Optional cache for trade fills (live mode PNL)
            paper_trades_tracker: Optional tracker for paper trades (paper mode PNL)
            trade_outcome_tracker: Optional tracker for trade outcomes (P&L tracking)
        """
        self.client = client
        self.settings = settings
        self.paper_mode = settings.trade_mode == "paper"
        self.trade_fills_cache = trade_fills_cache
        self.paper_trades_tracker = paper_trades_tracker
        self.trade_outcome_tracker = trade_outcome_tracker
        
        # Paper trading state
        self._paper_portfolio: dict[str, PortfolioPosition] = {}
        self._paper_orders: list[dict] = []
    
    async def get_portfolio(self) -> Portfolio:
        """Fetch current portfolio holdings with PNL enrichment."""
        logger.info("Fetching portfolio", paper_mode=self.paper_mode)
        
        if self.paper_mode and self._paper_portfolio:
            positions = list(self._paper_portfolio.values())
            portfolio = Portfolio(positions=positions)
            # Enrich with PNL data for paper mode
            await self._enrich_portfolio_pnl(portfolio)
            return portfolio
        
        data = await self.client.get(
            "/api/v2/spot/account/assets",
            params={"assetType": "hold_only"},
            authenticated=True,
        )
        
        positions = [
            PortfolioPosition(
                coin=item.get("coin", ""),
                available=item.get("available", "0"),
                frozen=item.get("frozen", "0"),
                locked=item.get("locked", "0"),
                updated_at=int(item.get("uTime", "0")),
            )
            for item in data
        ]
        
        portfolio = Portfolio(positions=positions)
        
        # Enrich with PNL data
        await self._enrich_portfolio_pnl(portfolio)
        
        logger.info(
            "Portfolio fetched",
            total_positions=portfolio.total_positions,
            usdt_balance=portfolio.usdt_balance,
        )
        
        return portfolio
    
    async def get_asset_balance(self, coin: str) -> Optional[str]:
        """Get available balance for a specific asset."""
        logger.debug("Fetching asset balance", coin=coin)
        
        data = await self.client.get(
            "/api/v2/spot/account/assets",
            params={"coin": coin.upper()},
            authenticated=True,
        )
        
        if not data:
            return None
        
        item = data[0] if isinstance(data, list) else data
        return item.get("available", "0")
    
    async def _get_current_price(self, symbol: str) -> Optional[float]:
        """
        Get current market price for a symbol.
        
        Args:
            symbol: Trading pair (e.g., "BTCUSDT")
            
        Returns:
            Current price as float or None.
        """
        try:
            data = await self.client.get(
                "/api/v2/spot/market/tickers",
                params={"symbol": symbol.upper()},
                authenticated=False,
            )
            if data and isinstance(data, list) and len(data) > 0:
                return float(data[0].get("lastPr", 0))
            return None
        except Exception as e:
            logger.warning("Failed to get price", symbol=symbol, error=str(e))
            return None
    
    async def _enrich_portfolio_pnl(self, portfolio: Portfolio) -> None:
        """
        Enrich portfolio positions with PNL data.
        
        For live mode: Uses TradeFillsCache to get cost basis from trade history.
        For paper mode: Uses PaperTradesTracker to get entry prices.
        
        Args:
            portfolio: Portfolio to enrich (modified in place)
        """
        # Get coins to enrich (exclude USDT and dust)
        coins_to_enrich = [
            p.coin for p in portfolio.positions
            if p.coin.upper() != "USDT" and p.total_balance > self.settings.min_portfolio_balance
        ]
        
        if not coins_to_enrich:
            return
        
        logger.debug("Enriching PNL for coins", coins=coins_to_enrich)
        
        # Fetch current prices for all coins
        prices: dict[str, float] = {}
        for coin in coins_to_enrich:
            symbol = f"{coin}USDT"
            price = await self._get_current_price(symbol)
            if price:
                prices[coin.upper()] = price
        
        # Get cost basis based on mode
        cost_basis: dict[str, float] = {}
        
        if self.paper_mode and self.paper_trades_tracker:
            # Paper mode: get entry prices from paper trades tracker
            for coin in coins_to_enrich:
                entry_price = await self.paper_trades_tracker.get_cost_basis(coin)
                if entry_price:
                    cost_basis[coin.upper()] = entry_price
        elif not self.paper_mode and self.trade_fills_cache:
            # Live mode: get cost basis from trade fills cache
            try:
                cb_results = await self.trade_fills_cache.get_cost_basis_batch(coins_to_enrich)
                for coin, cb in cb_results.items():
                    cost_basis[coin.upper()] = cb.avg_entry_price
            except Exception as e:
                logger.warning("Failed to get cost basis", error=str(e))
        
        # Enrich each position
        for position in portfolio.positions:
            coin_upper = position.coin.upper()
            
            if coin_upper == "USDT":
                continue
            
            # Set current price
            if coin_upper in prices:
                position.current_price = prices[coin_upper]
            
            # Set entry price and calculate PNL
            if coin_upper in cost_basis:
                position.avg_entry_price = cost_basis[coin_upper]
                
                if position.current_price and position.avg_entry_price:
                    qty = position.total_balance
                    entry = position.avg_entry_price
                    current = position.current_price
                    
                    position.unrealized_pnl = (current - entry) * qty
                    position.unrealized_pnl_pct = ((current - entry) / entry) * 100 if entry > 0 else 0.0
            else:
                # No cost basis available - set PNL to 0 as fallback
                if position.current_price:
                    position.unrealized_pnl = 0.0
                    position.unrealized_pnl_pct = 0.0
        
        # Log summary
        total_pnl = sum(
            p.unrealized_pnl or 0 
            for p in portfolio.positions 
            if p.unrealized_pnl is not None
        )
        logger.info(
            "Portfolio PNL enriched",
            positions_with_pnl=len([p for p in portfolio.positions if p.unrealized_pnl is not None]),
            total_unrealized_pnl=round(total_pnl, 2),
        )

    async def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        size: str,
        price: Optional[str] = None,
        client_oid: Optional[str] = None,
        reasoning: str = "",
    ) -> TradeExecutionResult:
        """Place a trading order."""
        if client_oid is None:
            client_oid = str(uuid.uuid4())
        
        logger.info(
            "Placing order",
            symbol=symbol,
            side=side,
            order_type=order_type,
            size=size,
            price=price,
            paper_mode=self.paper_mode,
        )
        
        if self.paper_mode:
            return await self._paper_place_order(
                symbol=symbol,
                side=side,
                order_type=order_type,
                size=size,
                price=price,
                client_oid=client_oid,
                reasoning=reasoning,
            )
        
        # Build order payload
        payload = {
            "symbol": symbol.upper(),
            "side": side.lower(),
            "orderType": order_type.lower(),
            "size": size,
            "clientOid": client_oid,
            "force": "gtc" if order_type.lower() == "limit" else "gtc",
        }
        
        if price and order_type.lower() == "limit":
            payload["price"] = price
        
        try:
            data = await self.client.post(
                "/api/v2/spot/trade/place-order",
                data=payload,
                authenticated=True,
            )
            
            return TradeExecutionResult(
                order_id=data.get("orderId", ""),
                client_order_id=data.get("clientOid", client_oid),
                symbol=symbol,
                side=side,
                status="submitted",
                success=True,
            )
        
        except BitgetAPIError as e:
            logger.error("Order placement failed", error=str(e), symbol=symbol)
            return TradeExecutionResult(
                order_id="",
                client_order_id=client_oid,
                symbol=symbol,
                side=side,
                status="failed",
                success=False,
                error_message=str(e),
            )
    
    async def execute_decision(self, decision: TradeDecision) -> TradeExecutionResult:
        """Execute a trading decision."""
        logger.info(
            "Executing decision",
            symbol=decision.symbol,
            action=decision.action.value,
            quantity=decision.quantity,
        )
        
        if decision.action == TradeAction.HOLD:
            return TradeExecutionResult(
                order_id="",
                symbol=decision.symbol,
                side="hold",
                status="no_action",
                success=True,
            )
        
        if not decision.is_actionable:
            logger.warning("Decision not actionable", decision=decision.to_dict())
            return TradeExecutionResult(
                order_id="",
                symbol=decision.symbol,
                status="invalid",
                success=False,
                error_message="Decision missing required fields",
            )
        
        result = await self.place_order(
            symbol=decision.symbol,
            side=decision.action.value,
            order_type=decision.order_type,
            size=decision.quantity,  # type: ignore
            price=decision.price,
            reasoning=decision.reasoning,
        )
        
        decision.executed = True
        decision.execution_result = {
            "order_id": result.order_id,
            "status": result.status,
            "success": result.success,
        }
        
        return result
    
    async def get_order_info(self, order_id: str) -> Optional[dict]:
        """Get information about an existing order."""
        logger.debug("Fetching order info", order_id=order_id)
        
        if self.paper_mode:
            for order in self._paper_orders:
                if order.get("orderId") == order_id:
                    return order
            return None
        
        try:
            data = await self.client.get(
                "/api/v2/spot/trade/orderInfo",
                params={"orderId": order_id},
                authenticated=True,
            )
            return data[0] if isinstance(data, list) else data
        except BitgetAPIError:
            return None
    
    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        """Cancel an existing order."""
        logger.info("Cancelling order", symbol=symbol, order_id=order_id)
        
        if self.paper_mode:
            for order in self._paper_orders:
                if order.get("orderId") == order_id:
                    order["status"] = "cancelled"
                    return True
            return False
        
        try:
            await self.client.post(
                "/api/v2/spot/trade/cancel-order",
                data={"symbol": symbol, "orderId": order_id},
                authenticated=True,
            )
            return True
        except BitgetAPIError as e:
            logger.error("Cancel order failed", error=str(e))
            return False
    
    async def _paper_place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        size: str,
        price: Optional[str],
        client_oid: str,
        reasoning: str = "",
    ) -> TradeExecutionResult:
        """Simulate order placement in paper trading mode."""
        order_id = f"paper_{uuid.uuid4().hex[:12]}"
        
        # In paper mode, simulate immediate fill for ALL orders (both market and limit)
        # This allows to track P&L and test the system without waiting for fills
        status = "filled"
        
        # Determine execution price
        exec_price = float(price) if price else 0.0
        if not price or exec_price <= 0:
            current_price = await self._get_current_price(symbol)
            exec_price = current_price if current_price else 0.0
        
        paper_order = {
            "orderId": order_id,
            "clientOid": client_oid,
            "symbol": symbol,
            "side": side,
            "orderType": order_type,
            "size": size,
            "price": str(exec_price),
            "status": status,
        }
        
        self._paper_orders.append(paper_order)
        
        # Extract coin from symbol (e.g., "BTCUSDT" -> "BTC")
        coin = symbol.upper().replace("USDT", "")
        quantity = float(size)
        
        # Record trade in paper trades tracker for PNL tracking
        if status == "filled" and self.paper_trades_tracker and exec_price > 0:
            if side.lower() == "buy":
                await self.paper_trades_tracker.record_buy(coin, quantity, exec_price)
            elif side.lower() == "sell":
                await self.paper_trades_tracker.record_sell(coin, quantity, exec_price)
        
        # Record trade outcome for P&L tracking and feedback loop
        if status == "filled" and self.trade_outcome_tracker and exec_price > 0:
            try:
                if side.lower() == "buy":
                    await self.trade_outcome_tracker.record_entry(
                        symbol=symbol,
                        coin=coin,
                        price=exec_price,
                        quantity=quantity,
                        reasoning=reasoning,
                    )
                    logger.info(
                        "Trade entry recorded for outcome tracking",
                        symbol=symbol,
                        price=exec_price,
                        quantity=quantity,
                    )
                elif side.lower() == "sell":
                    closed_outcomes = await self.trade_outcome_tracker.record_exit(
                        symbol=symbol,
                        coin=coin,
                        price=exec_price,
                        quantity=quantity,
                        reasoning=reasoning,
                    )
                    total_pnl = sum(o.realized_pnl or 0 for o in closed_outcomes)
                    logger.info(
                        "Trade exit recorded for outcome tracking",
                        symbol=symbol,
                        price=exec_price,
                        quantity=quantity,
                        closed_trades=len(closed_outcomes),
                        realized_pnl=round(total_pnl, 2),
                    )
            except Exception as e:
                logger.warning(
                    "Failed to record trade outcome (non-critical)",
                    error=str(e),
                    symbol=symbol,
                )
        
        logger.info("Paper order placed", order=paper_order)
        
        return TradeExecutionResult(
            order_id=order_id,
            client_order_id=client_oid,
            symbol=symbol,
            side=side,
            status=status,
            filled_quantity=size if status == "filled" else "0",
            success=True,
        )
