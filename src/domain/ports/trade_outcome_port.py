"""
Trade Outcome Port - Interface for trade outcome and P&L tracking.
"""

from abc import ABC, abstractmethod
from typing import Optional

from src.domain.entities.trade_outcome import (
    TradeOutcome,
    PositionPerformance,
    PortfolioStats,
)


class TradeOutcomePort(ABC):
    """
    Port interface for trade outcome tracking and P&L calculation.
    
    Tracks individual trade entries/exits with FIFO matching and calculates
    realized P&L. Also maintains aggregated position and portfolio statistics.
    
    Implementations:
        - DynamoDBTradeOutcomeAdapter: AWS DynamoDB storage
    """
    
    @abstractmethod
    async def record_entry(
        self,
        symbol: str,
        coin: str,
        price: float,
        quantity: float,
        reasoning: str = "",
    ) -> TradeOutcome:
        """
        Record a new trade entry (buy).
        
        Args:
            symbol: Trading pair (e.g., BTCUSDT)
            coin: Base coin (e.g., BTC)
            price: Entry price
            quantity: Quantity bought
            reasoning: Decision reasoning for context
            
        Returns:
            Created TradeOutcome with OPEN status
        """
        ...
    
    @abstractmethod
    async def record_exit(
        self,
        symbol: str,
        coin: str,
        price: float,
        quantity: float,
        reasoning: str = "",
    ) -> list[TradeOutcome]:
        """
        Record a trade exit (sell) using FIFO matching.
        
        Matches against oldest open entries for the symbol and calculates
        realized P&L. May close multiple entries if quantity exceeds
        the oldest entry's remaining quantity.
        
        Args:
            symbol: Trading pair (e.g., BTCUSDT)
            coin: Base coin (e.g., BTC)
            price: Exit price
            quantity: Quantity sold
            reasoning: Decision reasoning for context
            
        Returns:
            List of TradeOutcome records that were closed/partially closed
        """
        ...
    
    @abstractmethod
    async def get_open_entries(self, symbol: Optional[str] = None) -> list[TradeOutcome]:
        """
        Get all open (unmatched) trade entries.
        
        Args:
            symbol: Optional filter by symbol
            
        Returns:
            List of TradeOutcome with OPEN or PARTIAL status
        """
        ...
    
    @abstractmethod
    async def get_recent_outcomes(
        self,
        limit: int = 20,
        symbol: Optional[str] = None,
    ) -> list[TradeOutcome]:
        """
        Get recent closed trade outcomes.
        
        Args:
            limit: Maximum number of outcomes to return
            symbol: Optional filter by symbol
            
        Returns:
            List of closed TradeOutcome sorted by exit timestamp desc
        """
        ...
    
    @abstractmethod
    async def get_position_performance(self, coin: str) -> Optional[PositionPerformance]:
        """
        Get aggregated performance for a specific coin.
        
        Args:
            coin: Coin ticker (e.g., BTC)
            
        Returns:
            PositionPerformance or None if no trades for this coin
        """
        ...
    
    @abstractmethod
    async def get_all_position_performance(self) -> list[PositionPerformance]:
        """
        Get performance metrics for all traded coins.
        
        Returns:
            List of PositionPerformance for each traded coin
        """
        ...
    
    @abstractmethod
    async def get_portfolio_stats(self) -> PortfolioStats:
        """
        Get portfolio-wide statistics.
        
        Returns:
            PortfolioStats with aggregated metrics
        """
        ...
    
    @abstractmethod
    async def recalculate_stats(self) -> None:
        """
        Recalculate all position and portfolio statistics from trade history.
        
        Useful for rebuilding stats after data issues or migrations.
        """
        ...
