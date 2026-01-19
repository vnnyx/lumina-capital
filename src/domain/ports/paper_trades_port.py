"""
Paper Trades Port - Interface for paper trading position storage.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


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
        created_at = data["created_at"]
        updated_at = data["updated_at"]
        
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        
        return cls(
            coin=data["coin"],
            quantity=float(data["quantity"]),
            avg_entry_price=float(data["avg_entry_price"]),
            total_cost=float(data["total_cost"]),
            created_at=created_at,
            updated_at=updated_at,
        )


class PaperTradesPort(ABC):
    """
    Port interface for paper trading position storage.
    
    Implementations:
        - JsonPaperTradesAdapter: Local JSON file storage
        - DynamoDBPaperTradesAdapter: AWS DynamoDB storage
    """
    
    @abstractmethod
    async def record_buy(
        self,
        coin: str,
        quantity: float,
        price: float,
    ) -> PaperPosition:
        """Record a paper buy trade."""
        ...
    
    @abstractmethod
    async def record_sell(
        self,
        coin: str,
        quantity: float,
        price: float,
    ) -> Optional[PaperPosition]:
        """Record a paper sell trade."""
        ...
    
    @abstractmethod
    async def get_position(self, coin: str) -> Optional[PaperPosition]:
        """Get paper position for a coin."""
        ...
    
    @abstractmethod
    async def get_all_positions(self) -> dict[str, PaperPosition]:
        """Get all paper positions."""
        ...
    
    @abstractmethod
    async def get_cost_basis(self, coin: str) -> Optional[float]:
        """Get average entry price for a coin."""
        ...
    
    @abstractmethod
    async def clear_all(self) -> None:
        """Clear all paper positions."""
        ...
    
    @abstractmethod
    async def get_trade_history(self, limit: int = 100) -> list[dict]:
        """Get recent trade history."""
        ...
