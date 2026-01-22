"""
Trade Outcome entities - Tracking realized P&L from executed trades.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import uuid4


class OutcomeStatus(str, Enum):
    """Status of a trade outcome."""
    
    OPEN = "open"  # Entry recorded, awaiting exit
    CLOSED = "closed"  # Exit recorded, P&L calculated
    PARTIAL = "partial"  # Partially closed


@dataclass
class TradeOutcome:
    """
    Tracks a single trade from entry to exit with realized P&L.
    
    Uses FIFO matching: sells are matched against oldest buys for the symbol.
    """
    
    # Identifiers
    outcome_id: str = field(default_factory=lambda: str(uuid4())[:8])
    symbol: str = ""  # Trading pair (e.g., BTCUSDT)
    coin: str = ""  # Base coin (e.g., BTC)
    
    # Entry details
    entry_price: float = 0.0
    entry_quantity: float = 0.0
    entry_timestamp: datetime = field(default_factory=datetime.now)
    entry_decision_reasoning: str = ""
    
    # Exit details (populated on close)
    exit_price: Optional[float] = None
    exit_quantity: Optional[float] = None
    exit_timestamp: Optional[datetime] = None
    exit_decision_reasoning: str = ""
    
    # P&L (calculated on close)
    realized_pnl: Optional[float] = None  # In USDT
    realized_pnl_pct: Optional[float] = None  # Percentage
    
    # Metadata
    status: OutcomeStatus = OutcomeStatus.OPEN
    remaining_quantity: float = 0.0  # For partial exits
    holding_duration_hours: Optional[float] = None
    
    def __post_init__(self):
        """Initialize remaining quantity from entry quantity."""
        if self.remaining_quantity == 0.0 and self.entry_quantity > 0:
            self.remaining_quantity = self.entry_quantity
    
    def record_exit(
        self,
        exit_price: float,
        exit_quantity: float,
        exit_timestamp: Optional[datetime] = None,
        reasoning: str = "",
    ) -> "TradeOutcome":
        """
        Record an exit and calculate realized P&L.
        
        Args:
            exit_price: Price at exit
            exit_quantity: Quantity sold (can be partial)
            exit_timestamp: Time of exit
            reasoning: Exit decision reasoning
            
        Returns:
            Self with updated exit details
        """
        self.exit_price = exit_price
        self.exit_quantity = exit_quantity
        self.exit_timestamp = exit_timestamp or datetime.now()
        self.exit_decision_reasoning = reasoning
        
        # Calculate realized P&L
        exit_value = exit_price * exit_quantity
        entry_value = self.entry_price * exit_quantity
        self.realized_pnl = exit_value - entry_value
        self.realized_pnl_pct = ((exit_price / self.entry_price) - 1) * 100 if self.entry_price > 0 else 0.0
        
        # Calculate holding duration
        duration = self.exit_timestamp - self.entry_timestamp
        self.holding_duration_hours = duration.total_seconds() / 3600
        
        # Update remaining quantity and status
        self.remaining_quantity -= exit_quantity
        if self.remaining_quantity <= 0.001:  # Small threshold for floating point
            self.status = OutcomeStatus.CLOSED
            self.remaining_quantity = 0.0
        else:
            self.status = OutcomeStatus.PARTIAL
        
        return self
    
    @property
    def is_winner(self) -> Optional[bool]:
        """Check if this was a winning trade (None if still open)."""
        if self.realized_pnl is None:
            return None
        return self.realized_pnl > 0
    
    @property
    def entry_value(self) -> float:
        """Total entry value in USDT."""
        return self.entry_price * self.entry_quantity
    
    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "outcome_id": self.outcome_id,
            "symbol": self.symbol,
            "coin": self.coin,
            "entry_price": self.entry_price,
            "entry_quantity": self.entry_quantity,
            "entry_timestamp": self.entry_timestamp.isoformat(),
            "entry_decision_reasoning": self.entry_decision_reasoning,
            "exit_price": self.exit_price,
            "exit_quantity": self.exit_quantity,
            "exit_timestamp": self.exit_timestamp.isoformat() if self.exit_timestamp else None,
            "exit_decision_reasoning": self.exit_decision_reasoning,
            "realized_pnl": self.realized_pnl,
            "realized_pnl_pct": self.realized_pnl_pct,
            "status": self.status.value,
            "remaining_quantity": self.remaining_quantity,
            "holding_duration_hours": self.holding_duration_hours,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "TradeOutcome":
        """Create from dictionary."""
        entry_timestamp = data.get("entry_timestamp")
        if isinstance(entry_timestamp, str):
            entry_timestamp = datetime.fromisoformat(entry_timestamp.replace("Z", "+00:00"))
        
        exit_timestamp = data.get("exit_timestamp")
        if isinstance(exit_timestamp, str):
            exit_timestamp = datetime.fromisoformat(exit_timestamp.replace("Z", "+00:00"))
        
        return cls(
            outcome_id=data.get("outcome_id", str(uuid4())[:8]),
            symbol=data.get("symbol", ""),
            coin=data.get("coin", ""),
            entry_price=float(data.get("entry_price", 0)),
            entry_quantity=float(data.get("entry_quantity", 0)),
            entry_timestamp=entry_timestamp or datetime.now(),
            entry_decision_reasoning=data.get("entry_decision_reasoning", ""),
            exit_price=float(data["exit_price"]) if data.get("exit_price") else None,
            exit_quantity=float(data["exit_quantity"]) if data.get("exit_quantity") else None,
            exit_timestamp=exit_timestamp,
            exit_decision_reasoning=data.get("exit_decision_reasoning", ""),
            realized_pnl=float(data["realized_pnl"]) if data.get("realized_pnl") is not None else None,
            realized_pnl_pct=float(data["realized_pnl_pct"]) if data.get("realized_pnl_pct") is not None else None,
            status=OutcomeStatus(data.get("status", "open")),
            remaining_quantity=float(data.get("remaining_quantity", 0)),
            holding_duration_hours=float(data["holding_duration_hours"]) if data.get("holding_duration_hours") else None,
        )
    
    def to_summary(self) -> str:
        """Get a short summary for LLM context."""
        if self.status == OutcomeStatus.OPEN:
            return f"{self.coin}: OPEN entry@{self.entry_price:.4f} qty={self.entry_quantity:.4f}"
        
        pnl_str = f"+{self.realized_pnl:.2f}" if self.realized_pnl >= 0 else f"{self.realized_pnl:.2f}"
        pnl_pct_str = f"+{self.realized_pnl_pct:.2f}%" if self.realized_pnl_pct >= 0 else f"{self.realized_pnl_pct:.2f}%"
        result = "WIN" if self.is_winner else "LOSS"
        
        return f"{self.coin}: {result} {pnl_str} USDT ({pnl_pct_str}) held {self.holding_duration_hours:.1f}h"


@dataclass
class PositionPerformance:
    """
    Aggregated performance metrics for a single coin/position.
    
    Tracks cumulative statistics across all closed trades for the symbol.
    """
    
    symbol: str = ""
    coin: str = ""
    
    # Trade counts
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    
    # P&L metrics
    total_realized_pnl: float = 0.0
    total_realized_pnl_pct: float = 0.0  # Weighted average
    best_trade_pnl: float = 0.0
    worst_trade_pnl: float = 0.0
    
    # Time metrics
    avg_holding_duration_hours: float = 0.0
    
    # Last updated
    updated_at: datetime = field(default_factory=datetime.now)
    
    @property
    def win_rate(self) -> float:
        """Calculate win rate as percentage."""
        if self.total_trades == 0:
            return 0.0
        return (self.winning_trades / self.total_trades) * 100
    
    @property
    def avg_pnl_per_trade(self) -> float:
        """Average P&L per trade."""
        if self.total_trades == 0:
            return 0.0
        return self.total_realized_pnl / self.total_trades
    
    def update_from_outcome(self, outcome: TradeOutcome) -> "PositionPerformance":
        """
        Update aggregated stats from a closed trade outcome.
        
        Args:
            outcome: A closed TradeOutcome to incorporate
            
        Returns:
            Self with updated statistics
        """
        if outcome.status != OutcomeStatus.CLOSED or outcome.realized_pnl is None:
            return self
        
        # Update counts
        self.total_trades += 1
        if outcome.is_winner:
            self.winning_trades += 1
        else:
            self.losing_trades += 1
        
        # Update P&L
        self.total_realized_pnl += outcome.realized_pnl
        
        # Track best/worst
        if outcome.realized_pnl > self.best_trade_pnl:
            self.best_trade_pnl = outcome.realized_pnl
        if outcome.realized_pnl < self.worst_trade_pnl:
            self.worst_trade_pnl = outcome.realized_pnl
        
        # Update average holding duration (running average)
        if outcome.holding_duration_hours:
            prev_total = self.avg_holding_duration_hours * (self.total_trades - 1)
            self.avg_holding_duration_hours = (prev_total + outcome.holding_duration_hours) / self.total_trades
        
        self.updated_at = datetime.now()
        return self
    
    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "symbol": self.symbol,
            "coin": self.coin,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "total_realized_pnl": self.total_realized_pnl,
            "total_realized_pnl_pct": self.total_realized_pnl_pct,
            "best_trade_pnl": self.best_trade_pnl,
            "worst_trade_pnl": self.worst_trade_pnl,
            "avg_holding_duration_hours": self.avg_holding_duration_hours,
            "win_rate": self.win_rate,
            "avg_pnl_per_trade": self.avg_pnl_per_trade,
            "updated_at": self.updated_at.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "PositionPerformance":
        """Create from dictionary."""
        updated_at = data.get("updated_at")
        if isinstance(updated_at, str):
            updated_at = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        
        return cls(
            symbol=data.get("symbol", ""),
            coin=data.get("coin", ""),
            total_trades=int(data.get("total_trades", 0)),
            winning_trades=int(data.get("winning_trades", 0)),
            losing_trades=int(data.get("losing_trades", 0)),
            total_realized_pnl=float(data.get("total_realized_pnl", 0)),
            total_realized_pnl_pct=float(data.get("total_realized_pnl_pct", 0)),
            best_trade_pnl=float(data.get("best_trade_pnl", 0)),
            worst_trade_pnl=float(data.get("worst_trade_pnl", 0)),
            avg_holding_duration_hours=float(data.get("avg_holding_duration_hours", 0)),
            updated_at=updated_at or datetime.now(),
        )
    
    def to_summary(self) -> str:
        """Get a short summary for LLM context."""
        pnl_str = f"+{self.total_realized_pnl:.2f}" if self.total_realized_pnl >= 0 else f"{self.total_realized_pnl:.2f}"
        return f"{self.coin}: {self.total_trades} trades, {self.win_rate:.1f}% win rate, {pnl_str} USDT total P&L"


@dataclass
class PortfolioStats:
    """
    Portfolio-wide performance statistics.
    
    Aggregated across all positions for overall performance tracking.
    """
    
    # Trade counts
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    
    # P&L metrics
    total_realized_pnl: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    
    # Streaks
    current_streak: int = 0  # Positive = winning, negative = losing
    max_winning_streak: int = 0
    max_losing_streak: int = 0
    
    # Positions traded
    unique_coins_traded: int = 0
    
    # Time range
    first_trade_at: Optional[datetime] = None
    last_trade_at: Optional[datetime] = None
    
    @property
    def win_rate(self) -> float:
        """Overall win rate percentage."""
        if self.total_trades == 0:
            return 0.0
        return (self.winning_trades / self.total_trades) * 100
    
    @property
    def profit_factor(self) -> float:
        """Gross profit / gross loss (>1 is profitable)."""
        if self.largest_loss == 0:
            return float('inf') if self.largest_win > 0 else 0.0
        # Note: This is simplified; ideally track gross profit and loss separately
        return abs(self.largest_win / self.largest_loss) if self.largest_loss != 0 else 0.0
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "total_realized_pnl": self.total_realized_pnl,
            "win_rate": self.win_rate,
            "largest_win": self.largest_win,
            "largest_loss": self.largest_loss,
            "current_streak": self.current_streak,
            "max_winning_streak": self.max_winning_streak,
            "max_losing_streak": self.max_losing_streak,
            "unique_coins_traded": self.unique_coins_traded,
            "first_trade_at": self.first_trade_at.isoformat() if self.first_trade_at else None,
            "last_trade_at": self.last_trade_at.isoformat() if self.last_trade_at else None,
        }
    
    def to_summary(self) -> str:
        """Get summary for LLM context."""
        pnl_str = f"+{self.total_realized_pnl:.2f}" if self.total_realized_pnl >= 0 else f"{self.total_realized_pnl:.2f}"
        streak_str = f"+{self.current_streak}" if self.current_streak > 0 else str(self.current_streak)
        return (
            f"Portfolio: {self.total_trades} trades, {self.win_rate:.1f}% win rate, "
            f"{pnl_str} USDT total P&L, current streak: {streak_str}"
        )
