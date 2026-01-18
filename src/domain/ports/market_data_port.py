"""
Market Data Port - Interface for fetching market data.
"""

from abc import ABC, abstractmethod
from typing import Optional

from src.domain.entities.coin import Coin
from src.domain.entities.market_data import CandleStick, MarketData, TickerData


class MarketDataPort(ABC):
    """
    Port interface for market data operations.
    
    Implementations:
        - BitgetMarketDataAdapter: Fetches data from Bitget API
    """
    
    @abstractmethod
    async def get_all_coins(self) -> list[Coin]:
        """
        Fetch all available coins.
        
        Returns:
            List of Coin entities with metadata.
        """
        ...
    
    @abstractmethod
    async def get_coin_info(self, coin: str) -> Optional[Coin]:
        """
        Fetch information for a specific coin.
        
        Args:
            coin: Coin ticker symbol (e.g., "BTC")
            
        Returns:
            Coin entity or None if not found.
        """
        ...
    
    @abstractmethod
    async def get_all_tickers(self) -> list[TickerData]:
        """
        Fetch ticker data for all trading pairs.
        
        Returns:
            List of TickerData with current prices and volumes.
        """
        ...
    
    @abstractmethod
    async def get_ticker(self, symbol: str) -> Optional[TickerData]:
        """
        Fetch ticker data for a specific trading pair.
        
        Args:
            symbol: Trading pair symbol (e.g., "BTCUSDT")
            
        Returns:
            TickerData or None if not found.
        """
        ...
    
    @abstractmethod
    async def get_candles(
        self,
        symbol: str,
        granularity: str = "1h",
        limit: int = 100,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> list[CandleStick]:
        """
        Fetch candlestick (OHLCV) data for a trading pair.
        
        Args:
            symbol: Trading pair symbol (e.g., "BTCUSDT")
            granularity: Candle interval (1min, 5min, 15min, 1h, 4h, 1day, etc.)
            limit: Number of candles to fetch (max 1000)
            start_time: Start timestamp in milliseconds
            end_time: End timestamp in milliseconds
            
        Returns:
            List of CandleStick data points.
        """
        ...
    
    @abstractmethod
    async def get_top_coins_by_volume(self, limit: int = 200) -> list[TickerData]:
        """
        Fetch top trading pairs by USDT volume.
        
        Args:
            limit: Number of top pairs to return
            
        Returns:
            List of TickerData sorted by volume descending.
        """
        ...
    
    @abstractmethod
    async def get_market_data(
        self,
        symbol: str,
        candle_granularity: str = "1h",
        candle_limit: int = 24,
    ) -> Optional[MarketData]:
        """
        Fetch comprehensive market data for a symbol.
        
        Combines ticker and candle data into a single MarketData entity.
        
        Args:
            symbol: Trading pair symbol
            candle_granularity: Candle interval
            candle_limit: Number of candles
            
        Returns:
            MarketData entity or None if symbol not found.
        """
        ...
