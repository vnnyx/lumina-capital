"""
Trading Port - Interface for executing trades.
"""

from abc import ABC, abstractmethod
from typing import Optional

from src.domain.entities.portfolio import Portfolio
from src.domain.entities.trade_decision import TradeDecision, TradeExecutionResult


class TradingPort(ABC):
    """
    Port interface for trading operations.
    
    Implementations:
        - BitgetTradingAdapter: Executes trades on Bitget
        - PaperTradingAdapter: Simulates trades for testing
    """
    
    @abstractmethod
    async def get_portfolio(self) -> Portfolio:
        """
        Fetch current portfolio holdings.
        
        Returns:
            Portfolio with all positions.
        """
        ...
    
    @abstractmethod
    async def get_asset_balance(self, coin: str) -> Optional[str]:
        """
        Get available balance for a specific asset.
        
        Args:
            coin: Asset ticker (e.g., "USDT", "BTC")
            
        Returns:
            Available balance as string or None.
        """
        ...
    
    @abstractmethod
    async def place_order(
        self,
        symbol: str,
        side: str,  # "buy" or "sell"
        order_type: str,  # "market" or "limit"
        size: str,
        price: Optional[str] = None,
        client_oid: Optional[str] = None,
    ) -> TradeExecutionResult:
        """
        Place a trading order.
        
        Args:
            symbol: Trading pair (e.g., "BTCUSDT")
            side: "buy" or "sell"
            order_type: "market" or "limit"
            size: Order quantity
            price: Limit price (required for limit orders)
            client_oid: Optional custom order ID
            
        Returns:
            TradeExecutionResult with order details.
        """
        ...
    
    @abstractmethod
    async def execute_decision(self, decision: TradeDecision) -> TradeExecutionResult:
        """
        Execute a trading decision.
        
        Converts a TradeDecision into an order and executes it.
        
        Args:
            decision: TradeDecision from the manager agent
            
        Returns:
            TradeExecutionResult with execution details.
        """
        ...
    
    @abstractmethod
    async def get_order_info(self, order_id: str) -> Optional[dict]:
        """
        Get information about an existing order.
        
        Args:
            order_id: Order ID to look up
            
        Returns:
            Order details or None if not found.
        """
        ...
    
    @abstractmethod
    async def cancel_order(self, symbol: str, order_id: str) -> bool:
        """
        Cancel an existing order.
        
        Args:
            symbol: Trading pair
            order_id: Order ID to cancel
            
        Returns:
            True if cancelled successfully.
        """
        ...
