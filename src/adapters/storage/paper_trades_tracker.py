"""
Paper Trades Tracker - Tracks simulated trades for paper trading mode.

Stores entry prices and positions for paper trades to enable PNL calculation
without actual trade execution on the exchange.
"""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.infrastructure.logging import get_logger

logger = get_logger(__name__)


@dataclass
class PaperPosition:
    """A paper trading position."""
    
    coin: str
    quantity: float
    avg_entry_price: float
    total_cost: float
    created_at: datetime
    updated_at: datetime
    
    def to_dict(self) -> dict:
        return {
            "coin": self.coin,
            "quantity": self.quantity,
            "avg_entry_price": self.avg_entry_price,
            "total_cost": self.total_cost,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "PaperPosition":
        return cls(
            coin=data["coin"],
            quantity=data["quantity"],
            avg_entry_price=data["avg_entry_price"],
            total_cost=data["total_cost"],
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )


class PaperTradesTracker:
    """
    Tracks paper trading positions and calculates PNL.
    
    Stores positions in a JSON file and updates them when paper trades
    are "executed" by the trading adapter.
    """
    
    def __init__(self, storage_path: str = "data/paper_trades.json"):
        """
        Initialize paper trades tracker.
        
        Args:
            storage_path: Path to paper trades storage file
        """
        self.storage_path = Path(storage_path)
        self._positions: dict[str, PaperPosition] = {}
        self._trade_history: list[dict] = []
        self._load()
    
    def _load(self) -> None:
        """Load positions from disk."""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, "r") as f:
                    data = json.load(f)
                
                self._positions = {
                    coin: PaperPosition.from_dict(pos_data)
                    for coin, pos_data in data.get("positions", {}).items()
                }
                self._trade_history = data.get("trade_history", [])
                
                logger.debug(
                    "Paper trades loaded",
                    positions=len(self._positions),
                    trades=len(self._trade_history),
                )
            except Exception as e:
                logger.warning("Failed to load paper trades", error=str(e))
                self._positions = {}
                self._trade_history = []
        else:
            self._positions = {}
            self._trade_history = []
    
    def _save(self) -> None:
        """Save positions to disk."""
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            
            data = {
                "positions": {
                    coin: pos.to_dict()
                    for coin, pos in self._positions.items()
                },
                "trade_history": self._trade_history[-100:],  # Keep last 100 trades
                "last_updated": datetime.now().isoformat(),
            }
            
            with open(self.storage_path, "w") as f:
                json.dump(data, f, indent=2)
            
            logger.debug("Paper trades saved", path=str(self.storage_path))
        except Exception as e:
            logger.warning("Failed to save paper trades", error=str(e))
    
    def record_buy(
        self,
        coin: str,
        quantity: float,
        price: float,
    ) -> PaperPosition:
        """
        Record a paper buy trade.
        
        Updates the average entry price using weighted average.
        
        Args:
            coin: Coin ticker (e.g., "BTC")
            quantity: Quantity bought
            price: Execution price
            
        Returns:
            Updated PaperPosition.
        """
        coin = coin.upper()
        now = datetime.now()
        
        if coin in self._positions:
            # Update existing position with weighted average
            existing = self._positions[coin]
            new_total_cost = existing.total_cost + (quantity * price)
            new_quantity = existing.quantity + quantity
            new_avg_price = new_total_cost / new_quantity if new_quantity > 0 else 0
            
            self._positions[coin] = PaperPosition(
                coin=coin,
                quantity=new_quantity,
                avg_entry_price=new_avg_price,
                total_cost=new_total_cost,
                created_at=existing.created_at,
                updated_at=now,
            )
        else:
            # Create new position
            self._positions[coin] = PaperPosition(
                coin=coin,
                quantity=quantity,
                avg_entry_price=price,
                total_cost=quantity * price,
                created_at=now,
                updated_at=now,
            )
        
        # Record trade history
        self._trade_history.append({
            "type": "buy",
            "coin": coin,
            "quantity": quantity,
            "price": price,
            "timestamp": now.isoformat(),
        })
        
        self._save()
        
        logger.info(
            "Paper buy recorded",
            coin=coin,
            quantity=quantity,
            price=price,
            new_avg_price=self._positions[coin].avg_entry_price,
        )
        
        return self._positions[coin]
    
    def record_sell(
        self,
        coin: str,
        quantity: float,
        price: float,
    ) -> Optional[PaperPosition]:
        """
        Record a paper sell trade.
        
        Reduces position quantity but keeps the same avg entry price
        for remaining position.
        
        Args:
            coin: Coin ticker (e.g., "BTC")
            quantity: Quantity sold
            price: Execution price
            
        Returns:
            Updated PaperPosition or None if position fully closed.
        """
        coin = coin.upper()
        now = datetime.now()
        
        if coin not in self._positions:
            logger.warning("No paper position to sell", coin=coin)
            return None
        
        existing = self._positions[coin]
        new_quantity = existing.quantity - quantity
        
        if new_quantity <= 0:
            # Position fully closed
            del self._positions[coin]
            result = None
        else:
            # Reduce position, keep avg entry price
            new_total_cost = new_quantity * existing.avg_entry_price
            self._positions[coin] = PaperPosition(
                coin=coin,
                quantity=new_quantity,
                avg_entry_price=existing.avg_entry_price,
                total_cost=new_total_cost,
                created_at=existing.created_at,
                updated_at=now,
            )
            result = self._positions[coin]
        
        # Record trade history
        self._trade_history.append({
            "type": "sell",
            "coin": coin,
            "quantity": quantity,
            "price": price,
            "realized_pnl": (price - existing.avg_entry_price) * quantity,
            "timestamp": now.isoformat(),
        })
        
        self._save()
        
        logger.info(
            "Paper sell recorded",
            coin=coin,
            quantity=quantity,
            price=price,
            remaining=new_quantity if new_quantity > 0 else 0,
        )
        
        return result
    
    def get_position(self, coin: str) -> Optional[PaperPosition]:
        """Get paper position for a coin."""
        return self._positions.get(coin.upper())
    
    def get_all_positions(self) -> dict[str, PaperPosition]:
        """Get all paper positions."""
        return self._positions.copy()
    
    def get_cost_basis(self, coin: str) -> Optional[float]:
        """Get average entry price for a coin."""
        position = self.get_position(coin)
        return position.avg_entry_price if position else None
    
    def clear_all(self) -> None:
        """Clear all paper positions (for testing/reset)."""
        self._positions = {}
        self._trade_history = []
        self._save()
        logger.info("Paper trades cleared")
