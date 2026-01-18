"""
Market data entities - Price, volume, and candlestick data.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class TickerData:
    """Real-time ticker information for a trading pair."""
    
    symbol: str  # Trading pair (e.g., BTCUSDT)
    high_24h: str
    low_24h: str
    open_price: str
    last_price: str
    base_volume: str  # Volume in base currency
    quote_volume: str  # Volume in quote currency
    usdt_volume: str  # Volume in USDT
    bid_price: str
    ask_price: str
    bid_size: str
    ask_size: str
    change_24h: str  # 24h change percentage
    change_utc_24h: str
    timestamp: int  # Unix milliseconds
    
    @property
    def usdt_volume_float(self) -> float:
        """Get USDT volume as float for sorting."""
        try:
            return float(self.usdt_volume)
        except (ValueError, TypeError):
            return 0.0
    
    @property
    def change_24h_percent(self) -> float:
        """Get 24h change as percentage."""
        try:
            return float(self.change_24h) * 100
        except (ValueError, TypeError):
            return 0.0


@dataclass
class CandleStick:
    """OHLCV candlestick data point."""
    
    timestamp: int  # Unix milliseconds
    open_price: str
    high_price: str
    low_price: str
    close_price: str
    base_volume: str
    usdt_volume: str
    quote_volume: str
    
    @property
    def datetime(self) -> datetime:
        """Convert timestamp to datetime."""
        return datetime.fromtimestamp(self.timestamp / 1000)


@dataclass
class MarketData:
    """Aggregated market data for a coin."""
    
    symbol: str
    ticker: TickerData
    candles: list[CandleStick] = field(default_factory=list)
    granularity: str = "1h"  # Candle interval
    fetched_at: datetime = field(default_factory=datetime.now)
    
    @property
    def price_trend(self) -> str:
        """Calculate simple price trend from candles."""
        if len(self.candles) < 2:
            return "unknown"
        
        first_close = float(self.candles[0].close_price)
        last_close = float(self.candles[-1].close_price)
        
        change = (last_close - first_close) / first_close if first_close > 0 else 0
        
        if change > 0.02:
            return "bullish"
        elif change < -0.02:
            return "bearish"
        return "sideways"
    
    @property
    def volatility(self) -> float:
        """Calculate price volatility from candles."""
        if len(self.candles) < 2:
            return 0.0
        
        prices = [float(c.close_price) for c in self.candles if c.close_price]
        if not prices:
            return 0.0
        
        mean_price = sum(prices) / len(prices)
        if mean_price == 0:
            return 0.0
        
        variance = sum((p - mean_price) ** 2 for p in prices) / len(prices)
        return (variance ** 0.5) / mean_price  # Coefficient of variation
