"""
Fundamental data entity - Stores market sentiment and fundamental metrics.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class FearGreedIndex:
    """Fear & Greed Index data from Alternative.me."""
    
    value: int  # 0-100
    label: str  # Extreme Fear, Fear, Neutral, Greed, Extreme Greed
    timestamp: datetime
    
    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "value": self.value,
            "label": self.label,
            "timestamp": self.timestamp.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "FearGreedIndex":
        """Create from dictionary."""
        timestamp = data.get("timestamp")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        elif timestamp is None:
            timestamp = datetime.now()
            
        return cls(
            value=int(data.get("value", 50)),
            label=data.get("label", "Neutral"),
            timestamp=timestamp,
        )


@dataclass
class NewsItem:
    """Single news item from CryptoPanic."""
    
    title: str
    source: str
    url: str
    published_at: datetime
    sentiment: Optional[str] = None  # positive, negative, neutral
    
    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "title": self.title,
            "source": self.source,
            "url": self.url,
            "published_at": self.published_at.isoformat(),
            "sentiment": self.sentiment,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "NewsItem":
        """Create from dictionary."""
        published_at = data.get("published_at")
        if isinstance(published_at, str):
            published_at = datetime.fromisoformat(published_at)
        elif published_at is None:
            published_at = datetime.now()
            
        return cls(
            title=data.get("title", ""),
            source=data.get("source", ""),
            url=data.get("url", ""),
            published_at=published_at,
            sentiment=data.get("sentiment"),
        )


@dataclass
class CoinMetrics:
    """Fundamental metrics from CoinGecko."""
    
    ticker: str
    market_cap: Optional[float] = None
    market_cap_rank: Optional[int] = None
    fully_diluted_valuation: Optional[float] = None
    total_volume: Optional[float] = None
    circulating_supply: Optional[float] = None
    total_supply: Optional[float] = None
    max_supply: Optional[float] = None
    ath: Optional[float] = None  # All-time high
    ath_change_percentage: Optional[float] = None
    atl: Optional[float] = None  # All-time low
    atl_change_percentage: Optional[float] = None
    price_change_7d: Optional[float] = None
    price_change_30d: Optional[float] = None
    last_updated: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "ticker": self.ticker,
            "market_cap": self.market_cap,
            "market_cap_rank": self.market_cap_rank,
            "fully_diluted_valuation": self.fully_diluted_valuation,
            "total_volume": self.total_volume,
            "circulating_supply": self.circulating_supply,
            "total_supply": self.total_supply,
            "max_supply": self.max_supply,
            "ath": self.ath,
            "ath_change_percentage": self.ath_change_percentage,
            "atl": self.atl,
            "atl_change_percentage": self.atl_change_percentage,
            "price_change_7d": self.price_change_7d,
            "price_change_30d": self.price_change_30d,
            "last_updated": self.last_updated.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "CoinMetrics":
        """Create from dictionary."""
        last_updated = data.get("last_updated")
        if isinstance(last_updated, str):
            last_updated = datetime.fromisoformat(last_updated)
        elif last_updated is None:
            last_updated = datetime.now()
            
        return cls(
            ticker=data.get("ticker", ""),
            market_cap=data.get("market_cap"),
            market_cap_rank=data.get("market_cap_rank"),
            fully_diluted_valuation=data.get("fully_diluted_valuation"),
            total_volume=data.get("total_volume"),
            circulating_supply=data.get("circulating_supply"),
            total_supply=data.get("total_supply"),
            max_supply=data.get("max_supply"),
            ath=data.get("ath"),
            ath_change_percentage=data.get("ath_change_percentage"),
            atl=data.get("atl"),
            atl_change_percentage=data.get("atl_change_percentage"),
            price_change_7d=data.get("price_change_7d"),
            price_change_30d=data.get("price_change_30d"),
            last_updated=last_updated,
        )


@dataclass
class FundamentalData:
    """
    Complete fundamental data for market analysis.
    
    Aggregates data from multiple sources:
    - Alternative.me: Fear & Greed Index (global market sentiment)
    - CoinGecko: Market metrics per coin
    - CryptoPanic: News headlines (optional)
    """
    
    # Global market sentiment
    fear_greed: Optional[FearGreedIndex] = None
    
    # Per-coin metrics (keyed by ticker)
    coin_metrics: dict[str, CoinMetrics] = field(default_factory=dict)
    
    # Recent news (top headlines)
    news_items: list[NewsItem] = field(default_factory=list)
    
    # Cache metadata
    fetched_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "fear_greed": self.fear_greed.to_dict() if self.fear_greed else None,
            "coin_metrics": {
                ticker: metrics.to_dict() 
                for ticker, metrics in self.coin_metrics.items()
            },
            "news_items": [item.to_dict() for item in self.news_items],
            "fetched_at": self.fetched_at.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "FundamentalData":
        """Create from dictionary."""
        fetched_at = data.get("fetched_at")
        if isinstance(fetched_at, str):
            fetched_at = datetime.fromisoformat(fetched_at)
        elif fetched_at is None:
            fetched_at = datetime.now()
        
        fear_greed_data = data.get("fear_greed")
        fear_greed = FearGreedIndex.from_dict(fear_greed_data) if fear_greed_data else None
        
        coin_metrics = {
            ticker: CoinMetrics.from_dict(metrics_data)
            for ticker, metrics_data in data.get("coin_metrics", {}).items()
        }
        
        news_items = [
            NewsItem.from_dict(item_data)
            for item_data in data.get("news_items", [])
        ]
        
        return cls(
            fear_greed=fear_greed,
            coin_metrics=coin_metrics,
            news_items=news_items,
            fetched_at=fetched_at,
        )
    
    def get_metrics_for_coin(self, ticker: str) -> Optional[CoinMetrics]:
        """Get metrics for a specific coin."""
        return self.coin_metrics.get(ticker.upper())
    
    def get_summary_for_prompt(self, ticker: Optional[str] = None) -> str:
        """
        Generate a summary string for LLM prompt injection.
        
        Args:
            ticker: Optional ticker to get coin-specific metrics
            
        Returns:
            Formatted string for prompt inclusion
        """
        lines = ["## Fundamental Market Data"]
        
        # Fear & Greed
        if self.fear_greed:
            lines.append(f"\n### Market Sentiment")
            lines.append(f"- Fear & Greed Index: {self.fear_greed.value}/100 ({self.fear_greed.label})")
        
        # Coin-specific metrics
        if ticker and ticker.upper() in self.coin_metrics:
            metrics = self.coin_metrics[ticker.upper()]
            lines.append(f"\n### {ticker.upper()} Fundamentals")
            if metrics.market_cap_rank:
                lines.append(f"- Market Cap Rank: #{metrics.market_cap_rank}")
            if metrics.market_cap:
                lines.append(f"- Market Cap: ${metrics.market_cap:,.0f}")
            if metrics.ath and metrics.ath_change_percentage:
                lines.append(f"- All-Time High: ${metrics.ath:,.2f} ({metrics.ath_change_percentage:+.1f}% from ATH)")
            if metrics.price_change_7d:
                lines.append(f"- 7-Day Change: {metrics.price_change_7d:+.2f}%")
            if metrics.price_change_30d:
                lines.append(f"- 30-Day Change: {metrics.price_change_30d:+.2f}%")
            if metrics.circulating_supply and metrics.max_supply:
                pct = (metrics.circulating_supply / metrics.max_supply) * 100
                lines.append(f"- Circulating/Max Supply: {pct:.1f}%")
        
        # Recent news
        if self.news_items:
            lines.append(f"\n### Recent News Headlines")
            for item in self.news_items[:5]:
                sentiment_emoji = {
                    "positive": "📈",
                    "negative": "📉",
                    "neutral": "➖"
                }.get(item.sentiment, "📰")
                lines.append(f"- {sentiment_emoji} {item.title} ({item.source})")
        
        return "\n".join(lines)
