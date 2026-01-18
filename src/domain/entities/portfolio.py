"""
Portfolio entities - Holdings and positions.
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class PortfolioPosition:
    """Represents a single asset position in the portfolio."""
    
    coin: str  # Token name (e.g., BTC)
    available: str  # Available balance
    frozen: str  # Frozen amount (in orders)
    locked: str  # Locked amount
    updated_at: int  # Unix milliseconds
    
    @property
    def total_balance(self) -> float:
        """Calculate total balance including frozen and locked."""
        try:
            return float(self.available) + float(self.frozen) + float(self.locked)
        except (ValueError, TypeError):
            return 0.0
    
    @property
    def available_float(self) -> float:
        """Get available balance as float."""
        try:
            return float(self.available)
        except (ValueError, TypeError):
            return 0.0


@dataclass
class Portfolio:
    """Represents the complete portfolio state."""
    
    positions: list[PortfolioPosition] = field(default_factory=list)
    fetched_at: datetime = field(default_factory=datetime.now)
    
    def get_position(self, coin: str) -> PortfolioPosition | None:
        """Get position for a specific coin."""
        for position in self.positions:
            if position.coin.upper() == coin.upper():
                return position
        return None
    
    @property
    def usdt_balance(self) -> float:
        """Get available USDT balance."""
        position = self.get_position("USDT")
        return position.available_float if position else 0.0
    
    @property
    def total_positions(self) -> int:
        """Count of non-zero positions."""
        return sum(1 for p in self.positions if p.total_balance > 0)
    
    def to_dict(self) -> dict:
        """Convert portfolio to dictionary for LLM context."""
        return {
            "usdt_balance": self.usdt_balance,
            "total_positions": self.total_positions,
            "positions": [
                {
                    "coin": p.coin,
                    "available": p.available,
                    "frozen": p.frozen,
                    "total": p.total_balance,
                }
                for p in self.positions
                if p.total_balance > 0
            ],
            "fetched_at": self.fetched_at.isoformat(),
        }
