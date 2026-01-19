"""
Trade Fills Cache - Caches trade execution history for PNL calculation.

Fetches trade fills from Bitget API and caches them locally to avoid
repeated API calls and enable cost basis calculation.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from src.adapters.bitget.client import BitgetClient
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)


@dataclass
class TradeFill:
    """Represents a single trade fill."""
    
    fill_id: str
    symbol: str
    side: str  # "buy" or "sell"
    price: float
    quantity: float
    fee: float
    fee_currency: str
    timestamp: datetime
    
    def to_dict(self) -> dict:
        return {
            "fill_id": self.fill_id,
            "symbol": self.symbol,
            "side": self.side,
            "price": self.price,
            "quantity": self.quantity,
            "fee": self.fee,
            "fee_currency": self.fee_currency,
            "timestamp": self.timestamp.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "TradeFill":
        return cls(
            fill_id=data["fill_id"],
            symbol=data["symbol"],
            side=data["side"],
            price=data["price"],
            quantity=data["quantity"],
            fee=data["fee"],
            fee_currency=data["fee_currency"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
        )


@dataclass
class CoinCostBasis:
    """Calculated cost basis for a coin."""
    
    coin: str
    avg_entry_price: float
    total_quantity: float
    total_cost: float
    last_updated: datetime


class TradeFillsCache:
    """
    Caches trade fills and calculates cost basis.
    
    Uses Bitget /api/v2/spot/trade/fills endpoint to fetch historical fills.
    Caches results to JSON file with configurable TTL.
    """
    
    def __init__(
        self,
        client: BitgetClient,
        cache_path: str = "data/trade_fills_cache.json",
        cache_ttl_hours: int = 1,
    ):
        """
        Initialize trade fills cache.
        
        Args:
            client: Bitget API client
            cache_path: Path to cache file
            cache_ttl_hours: Hours before cache is considered stale
        """
        self.client = client
        self.cache_path = Path(cache_path)
        self.cache_ttl = timedelta(hours=cache_ttl_hours)
        self._cache: dict = {}
        self._load_cache()
    
    def _load_cache(self) -> None:
        """Load cache from disk."""
        if self.cache_path.exists():
            try:
                with open(self.cache_path, "r") as f:
                    self._cache = json.load(f)
                logger.debug("Trade fills cache loaded", path=str(self.cache_path))
            except Exception as e:
                logger.warning("Failed to load trade fills cache", error=str(e))
                self._cache = {}
        else:
            self._cache = {}
    
    def _save_cache(self) -> None:
        """Save cache to disk."""
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cache_path, "w") as f:
                json.dump(self._cache, f, indent=2)
            logger.debug("Trade fills cache saved", path=str(self.cache_path))
        except Exception as e:
            logger.warning("Failed to save trade fills cache", error=str(e))
    
    def _is_cache_valid(self, coin: str) -> bool:
        """Check if cache for a coin is still valid."""
        cache_key = f"fills_{coin}"
        if cache_key not in self._cache:
            return False
        
        cached_at = self._cache[cache_key].get("cached_at")
        if not cached_at:
            return False
        
        cached_time = datetime.fromisoformat(cached_at)
        return datetime.now() - cached_time < self.cache_ttl
    
    async def fetch_fills_for_symbol(
        self,
        symbol: str,
        limit: int = 500,
    ) -> list[TradeFill]:
        """
        Fetch trade fills for a symbol from Bitget API.
        
        Args:
            symbol: Trading pair (e.g., "BTCUSDT")
            limit: Maximum fills to fetch
            
        Returns:
            List of TradeFill objects.
        """
        try:
            data = await self.client.get(
                "/api/v2/spot/trade/fills",
                params={
                    "symbol": symbol.upper(),
                    "limit": str(limit),
                },
                authenticated=True,
            )
            
            fills = []
            for item in data or []:
                try:
                    fill = TradeFill(
                        fill_id=item.get("tradeId", ""),
                        symbol=item.get("symbol", ""),
                        side=item.get("side", "").lower(),
                        price=float(item.get("priceAvg", 0)),
                        quantity=float(item.get("size", 0)),
                        fee=float(item.get("feeDetail", {}).get("totalFee", 0)),
                        fee_currency=item.get("feeDetail", {}).get("feeCoin", ""),
                        timestamp=datetime.fromtimestamp(
                            int(item.get("cTime", 0)) / 1000
                        ),
                    )
                    fills.append(fill)
                except (ValueError, TypeError) as e:
                    logger.warning("Failed to parse fill", error=str(e), item=item)
            
            logger.info(
                "Fetched trade fills",
                symbol=symbol,
                count=len(fills),
            )
            return fills
            
        except Exception as e:
            logger.error("Failed to fetch trade fills", symbol=symbol, error=str(e))
            return []
    
    async def get_cost_basis(self, coin: str) -> Optional[CoinCostBasis]:
        """
        Get cost basis for a coin, using cache if valid.
        
        Args:
            coin: Coin ticker (e.g., "BTC")
            
        Returns:
            CoinCostBasis or None if no trades found.
        """
        cache_key = f"fills_{coin}"
        
        # Check cache first
        if self._is_cache_valid(coin):
            cached = self._cache[cache_key]
            if cached.get("cost_basis"):
                cb = cached["cost_basis"]
                return CoinCostBasis(
                    coin=coin,
                    avg_entry_price=cb["avg_entry_price"],
                    total_quantity=cb["total_quantity"],
                    total_cost=cb["total_cost"],
                    last_updated=datetime.fromisoformat(cb["last_updated"]),
                )
        
        # Fetch fresh data
        symbol = f"{coin}USDT"
        fills = await self.fetch_fills_for_symbol(symbol)
        
        if not fills:
            # Cache empty result to avoid repeated API calls
            self._cache[cache_key] = {
                "fills": [],
                "cost_basis": None,
                "cached_at": datetime.now().isoformat(),
            }
            self._save_cache()
            return None
        
        # Calculate cost basis using simple average of buy fills
        buy_fills = [f for f in fills if f.side == "buy"]
        
        if not buy_fills:
            self._cache[cache_key] = {
                "fills": [f.to_dict() for f in fills],
                "cost_basis": None,
                "cached_at": datetime.now().isoformat(),
            }
            self._save_cache()
            return None
        
        # Weighted average price for buys
        total_cost = sum(f.price * f.quantity for f in buy_fills)
        total_qty = sum(f.quantity for f in buy_fills)
        avg_price = total_cost / total_qty if total_qty > 0 else 0
        
        cost_basis = CoinCostBasis(
            coin=coin,
            avg_entry_price=avg_price,
            total_quantity=total_qty,
            total_cost=total_cost,
            last_updated=datetime.now(),
        )
        
        # Cache the result
        self._cache[cache_key] = {
            "fills": [f.to_dict() for f in fills],
            "cost_basis": {
                "avg_entry_price": cost_basis.avg_entry_price,
                "total_quantity": cost_basis.total_quantity,
                "total_cost": cost_basis.total_cost,
                "last_updated": cost_basis.last_updated.isoformat(),
            },
            "cached_at": datetime.now().isoformat(),
        }
        self._save_cache()
        
        logger.info(
            "Calculated cost basis",
            coin=coin,
            avg_entry_price=cost_basis.avg_entry_price,
            total_quantity=cost_basis.total_quantity,
        )
        
        return cost_basis
    
    async def get_cost_basis_batch(
        self,
        coins: list[str],
    ) -> dict[str, CoinCostBasis]:
        """
        Get cost basis for multiple coins.
        
        Args:
            coins: List of coin tickers
            
        Returns:
            Dictionary mapping coin to CoinCostBasis.
        """
        results = {}
        for coin in coins:
            if coin.upper() == "USDT":
                continue
            cost_basis = await self.get_cost_basis(coin)
            if cost_basis:
                results[coin.upper()] = cost_basis
        return results
