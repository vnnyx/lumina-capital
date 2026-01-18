"""
Bitget Trading Adapter - Implements TradingPort.
"""

import uuid
from typing import Optional

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

logger = get_logger(__name__)


class BitgetTradingAdapter(TradingPort):
    """
    Bitget implementation of TradingPort.
    
    Handles portfolio queries and trade execution via Bitget Spot API v2.
    Supports paper trading mode for simulation.
    """
    
    def __init__(self, client: BitgetClient, settings: Settings):
        """
        Initialize adapter.
        
        Args:
            client: Bitget HTTP client
            settings: Application settings
        """
        self.client = client
        self.settings = settings
        self.paper_mode = settings.trade_mode == "paper"
        
        # Paper trading state
        self._paper_portfolio: dict[str, PortfolioPosition] = {}
        self._paper_orders: list[dict] = []
    
    async def get_portfolio(self) -> Portfolio:
        """Fetch current portfolio holdings."""
        logger.info("Fetching portfolio", paper_mode=self.paper_mode)
        
        if self.paper_mode and self._paper_portfolio:
            return Portfolio(positions=list(self._paper_portfolio.values()))
        
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
    
    async def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        size: str,
        price: Optional[str] = None,
        client_oid: Optional[str] = None,
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
    ) -> TradeExecutionResult:
        """Simulate order placement in paper trading mode."""
        order_id = f"paper_{uuid.uuid4().hex[:12]}"
        
        # Simulate immediate fill for market orders
        status = "filled" if order_type == "market" else "live"
        
        paper_order = {
            "orderId": order_id,
            "clientOid": client_oid,
            "symbol": symbol,
            "side": side,
            "orderType": order_type,
            "size": size,
            "price": price or "0",
            "status": status,
        }
        
        self._paper_orders.append(paper_order)
        
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
