"""
Trade decision entities - Actions and decisions from the manager agent.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class TradeAction(str, Enum):
    """Possible trading actions."""
    
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class TradeDecision:
    """Represents a trading decision made by the DeepSeek manager."""
    
    symbol: str  # Trading pair (e.g., BTCUSDT)
    action: TradeAction
    quantity: Optional[str] = None  # Amount to trade
    price: Optional[str] = None  # Limit price (None for market order)
    order_type: str = "market"  # market or limit
    reasoning: str = ""  # Explanation for the decision
    confidence: float = 0.0  # 0.0 to 1.0
    priority: int = 0  # Higher = execute first
    created_at: datetime = field(default_factory=datetime.now)
    executed: bool = False
    execution_result: Optional[dict] = None
    
    @property
    def is_actionable(self) -> bool:
        """Check if this decision requires an order."""
        return self.action in (TradeAction.BUY, TradeAction.SELL) and self.quantity is not None
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "symbol": self.symbol,
            "action": self.action.value,
            "quantity": self.quantity,
            "price": self.price,
            "order_type": self.order_type,
            "reasoning": self.reasoning,
            "confidence": self.confidence,
            "priority": self.priority,
            "created_at": self.created_at.isoformat(),
            "executed": self.executed,
        }


@dataclass
class TradeExecutionResult:
    """Result of executing a trade."""
    
    order_id: str
    client_order_id: Optional[str] = None
    symbol: str = ""
    side: str = ""
    status: str = ""
    filled_quantity: str = "0"
    filled_price: str = "0"
    fee: str = "0"
    created_at: datetime = field(default_factory=datetime.now)
    success: bool = True
    error_message: Optional[str] = None
