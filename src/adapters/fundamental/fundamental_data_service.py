"""
Fundamental Data Service - Orchestrates fundamental data fetching with caching.

Uses JSON file storage for caching to avoid repeated API calls.
Implements TTL-based cache invalidation for serverless environments.
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from src.adapters.fundamental.alternative_me_adapter import AlternativeMeAdapter
from src.adapters.fundamental.coingecko_adapter import CoinGeckoAdapter
from src.domain.entities.fundamental_data import (
    FundamentalData,
    FearGreedIndex,
    CoinMetrics,
    NewsItem,
)
from src.domain.ports.fundamental_data_port import FundamentalDataPort

logger = logging.getLogger(__name__)


class FundamentalDataService(FundamentalDataPort):
    """
    Service that aggregates fundamental data from multiple sources.
    
    Features:
    - Caches data in JSON file to minimize API calls
    - TTL-based cache invalidation
    - Graceful degradation when APIs fail
    
    Cache TTLs:
    - Fear & Greed Index: 1 hour (updates every few hours)
    - Coin Metrics: 30 minutes (market data changes frequently)
    - News: 15 minutes (news is time-sensitive)
    """
    
    # Cache TTLs in seconds
    FEAR_GREED_TTL = 3600  # 1 hour
    COIN_METRICS_TTL = 1800  # 30 minutes
    NEWS_TTL = 900  # 15 minutes
    
    def __init__(
        self,
        cache_path: str = "data/fundamental_cache.json",
        coingecko_api_key: Optional[str] = None,
    ):
        """
        Initialize the service.
        
        Args:
            cache_path: Path to the JSON cache file.
            coingecko_api_key: Optional CoinGecko API key for higher rate limits.
        """
        self._cache_path = Path(cache_path)
        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize adapters
        self._alternative_me = AlternativeMeAdapter()
        self._coingecko = CoinGeckoAdapter(api_key=coingecko_api_key)
        
        # In-memory cache
        self._cache: dict = {}
        self._load_cache()
    
    def _load_cache(self) -> None:
        """Load cache from disk."""
        try:
            if self._cache_path.exists():
                with open(self._cache_path, "r") as f:
                    self._cache = json.load(f)
                logger.debug(f"Loaded fundamental cache from {self._cache_path}")
        except Exception as e:
            logger.warning(f"Could not load fundamental cache: {e}")
            self._cache = {}
    
    def _save_cache(self) -> None:
        """Save cache to disk."""
        try:
            with open(self._cache_path, "w") as f:
                json.dump(self._cache, f, indent=2, default=str)
            logger.debug(f"Saved fundamental cache to {self._cache_path}")
        except Exception as e:
            logger.error(f"Could not save fundamental cache: {e}")
    
    def _is_cache_valid(self, cache_key: str, ttl_seconds: int) -> bool:
        """Check if cached data is still valid."""
        if cache_key not in self._cache:
            return False
        
        cached_at = self._cache[cache_key].get("cached_at")
        if not cached_at:
            return False
        
        try:
            cached_time = datetime.fromisoformat(cached_at)
            return datetime.now() - cached_time < timedelta(seconds=ttl_seconds)
        except Exception:
            return False
    
    async def get_fear_greed_index(self) -> Optional[FearGreedIndex]:
        """
        Fetch the current Fear & Greed Index with caching.
        
        Returns:
            FearGreedIndex or None if unavailable.
        """
        cache_key = "fear_greed"
        
        # Check cache
        if self._is_cache_valid(cache_key, self.FEAR_GREED_TTL):
            cached_data = self._cache[cache_key].get("data")
            if cached_data:
                logger.debug("Using cached Fear & Greed Index")
                return FearGreedIndex.from_dict(cached_data)
        
        # Fetch fresh data
        logger.info("Fetching Fear & Greed Index from Alternative.me")
        result = await self._alternative_me.get_fear_greed_index()
        
        if result:
            self._cache[cache_key] = {
                "data": result.to_dict(),
                "cached_at": datetime.now().isoformat(),
            }
            self._save_cache()
        
        return result
    
    async def get_coin_metrics(self, tickers: list[str]) -> dict[str, CoinMetrics]:
        """
        Fetch fundamental metrics for multiple coins with caching.
        
        Args:
            tickers: List of coin tickers (e.g., ["BTC", "ETH"])
            
        Returns:
            Dictionary mapping ticker to CoinMetrics.
        """
        results: dict[str, CoinMetrics] = {}
        tickers_to_fetch: list[str] = []
        
        # Check cache for each ticker
        for ticker in tickers:
            cache_key = f"metrics_{ticker.upper()}"
            if self._is_cache_valid(cache_key, self.COIN_METRICS_TTL):
                cached_data = self._cache[cache_key].get("data")
                if cached_data:
                    results[ticker.upper()] = CoinMetrics.from_dict(cached_data)
                    logger.debug(f"Using cached metrics for {ticker}")
                    continue
            tickers_to_fetch.append(ticker)
        
        # Fetch missing tickers
        if tickers_to_fetch:
            logger.info(f"Fetching CoinGecko metrics for: {tickers_to_fetch}")
            fresh_data = await self._coingecko.get_coin_metrics(tickers_to_fetch)
            
            for ticker, metrics in fresh_data.items():
                results[ticker] = metrics
                cache_key = f"metrics_{ticker.upper()}"
                self._cache[cache_key] = {
                    "data": metrics.to_dict(),
                    "cached_at": datetime.now().isoformat(),
                }
            
            if fresh_data:
                self._save_cache()
        
        return results
    
    async def get_news_headlines(
        self,
        tickers: Optional[list[str]] = None,
        limit: int = 5
    ) -> list[NewsItem]:
        """
        Get news headlines.
        
        Note: CryptoPanic integration is optional and not implemented yet.
        Returns empty list for now.
        
        Args:
            tickers: Optional list of tickers to filter news
            limit: Maximum number of headlines to return
            
        Returns:
            List of NewsItem objects (empty for now).
        """
        # TODO: Implement CryptoPanic integration when API key is available
        logger.debug("News headlines not implemented (CryptoPanic API key required)")
        return []
    
    async def get_all_fundamental_data(
        self,
        tickers: list[str],
    ) -> FundamentalData:
        """
        Fetch all fundamental data in one call.
        
        This is the main method to use for getting all fundamental data
        for analysis, with proper caching.
        
        Args:
            tickers: List of coin tickers to get metrics for.
            
        Returns:
            FundamentalData object with all available data.
        """
        # Fetch all data concurrently
        import asyncio
        
        fear_greed_task = self.get_fear_greed_index()
        metrics_task = self.get_coin_metrics(tickers)
        news_task = self.get_news_headlines(tickers)
        
        fear_greed, metrics, news = await asyncio.gather(
            fear_greed_task,
            metrics_task,
            news_task,
            return_exceptions=True,
        )
        
        # Handle any exceptions gracefully
        if isinstance(fear_greed, Exception):
            logger.error(f"Error fetching Fear & Greed: {fear_greed}")
            fear_greed = None
        
        if isinstance(metrics, Exception):
            logger.error(f"Error fetching metrics: {metrics}")
            metrics = {}
        
        if isinstance(news, Exception):
            logger.error(f"Error fetching news: {news}")
            news = []
        
        return FundamentalData(
            fear_greed=fear_greed,
            coin_metrics=metrics or {},
            news_items=news or [],
            fetched_at=datetime.now(),
        )
    
    async def close(self) -> None:
        """Close all HTTP clients."""
        await self._alternative_me.close()
        await self._coingecko.close()
    
    def clear_cache(self) -> None:
        """Clear all cached data."""
        self._cache = {}
        if self._cache_path.exists():
            self._cache_path.unlink()
        logger.info("Fundamental data cache cleared")
