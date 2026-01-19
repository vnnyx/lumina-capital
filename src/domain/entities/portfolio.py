"""
Portfolio entities - Holdings and positions.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class PortfolioPosition:
    """Represents a single asset position in the portfolio."""
    
    coin: str  # Token name (e.g., BTC)
    available: str  # Available balance
    frozen: str  # Frozen amount (in orders)
    locked: str  # Locked amount
    updated_at: int  # Unix milliseconds
    
    # PNL fields (optional, enriched later)
    avg_entry_price: Optional[float] = None  # Average cost basis
    current_price: Optional[float] = None  # Current market price
    unrealized_pnl: Optional[float] = None  # Unrealized P&L in USDT
    unrealized_pnl_pct: Optional[float] = None  # P&L percentage
    
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
    
    @property
    def total_cost_basis(self) -> Optional[float]:
        """Calculate total cost basis (qty × avg_entry_price)."""
        if self.avg_entry_price is not None:
            return self.total_balance * self.avg_entry_price
        return None
    
    @property
    def current_value(self) -> Optional[float]:
        """Calculate current value (qty × current_price)."""
        if self.current_price is not None:
            return self.total_balance * self.current_price
        return None


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
        positions_data = []
        total_unrealized_pnl = 0.0
        
        for p in self.positions:
            if p.total_balance > 0:
                pos_dict = {
                    "coin": p.coin,
                    "available": p.available,
                    "frozen": p.frozen,
                    "total": p.total_balance,
                }
                # Add PNL data if available
                if p.avg_entry_price is not None:
                    pos_dict["avg_entry_price"] = p.avg_entry_price
                if p.current_price is not None:
                    pos_dict["current_price"] = p.current_price
                if p.unrealized_pnl is not None:
                    pos_dict["unrealized_pnl"] = p.unrealized_pnl
                    total_unrealized_pnl += p.unrealized_pnl
                if p.unrealized_pnl_pct is not None:
                    pos_dict["unrealized_pnl_pct"] = p.unrealized_pnl_pct
                
                positions_data.append(pos_dict)
        
        result = {
            "usdt_balance": self.usdt_balance,
            "total_positions": self.total_positions,
            "positions": positions_data,
            "fetched_at": self.fetched_at.isoformat(),
        }
        
        # Add total PNL if any position has PNL data
        if total_unrealized_pnl != 0.0:
            result["total_unrealized_pnl"] = total_unrealized_pnl
        
        return result
