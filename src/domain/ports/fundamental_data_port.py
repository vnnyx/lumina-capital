"""
Fundamental Data Port - Interface for fetching fundamental market data.
"""

from abc import ABC, abstractmethod
from typing import Optional

from src.domain.entities.fundamental_data import (
    FearGreedIndex,
    CoinMetrics,
    NewsItem,
)


class FundamentalDataPort(ABC):
    """
    Port interface for fundamental data operations.
    
    Implementations fetch data from external APIs:
    - Alternative.me: Fear & Greed Index
    - CoinGecko: Market metrics
    - CryptoPanic: News headlines
    """
    
    @abstractmethod
    async def get_fear_greed_index(self) -> Optional[FearGreedIndex]:
        """
        Fetch the current Fear & Greed Index.
        
        Returns:
            FearGreedIndex or None if unavailable.
        """
        ...
    
    @abstractmethod
    async def get_coin_metrics(self, tickers: list[str]) -> dict[str, CoinMetrics]:
        """
        Fetch fundamental metrics for multiple coins.
        
        Args:
            tickers: List of coin tickers (e.g., ["BTC", "ETH"])
            
        Returns:
            Dictionary mapping ticker to CoinMetrics.
        """
        ...
    
    @abstractmethod
    async def get_news_headlines(
        self, 
        tickers: Optional[list[str]] = None,
        limit: int = 5
    ) -> list[NewsItem]:
        """
        Fetch recent news headlines.
        
        Args:
            tickers: Optional list of tickers to filter news
            limit: Maximum number of headlines to return
            
        Returns:
            List of NewsItem objects.
        """
        ...
