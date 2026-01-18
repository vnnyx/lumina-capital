"""
Alternative.me Adapter - Fetches Fear & Greed Index.

API Documentation: https://alternative.me/crypto/fear-and-greed-index/
Free tier: Unlimited calls, no API key required.
"""

import logging
from datetime import datetime
from typing import Optional

import httpx

from src.domain.entities.fundamental_data import FearGreedIndex

logger = logging.getLogger(__name__)


class AlternativeMeAdapter:
    """
    Adapter for Alternative.me Fear & Greed Index API.
    
    This is a free API with no rate limits or authentication required.
    Returns the current market sentiment index (0-100).
    """
    
    BASE_URL = "https://api.alternative.me/fng/"
    TIMEOUT = 10.0
    
    def __init__(self):
        """Initialize the adapter."""
        self._client: Optional[httpx.AsyncClient] = None
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.TIMEOUT)
        return self._client
    
    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
    
    async def get_fear_greed_index(self) -> Optional[FearGreedIndex]:
        """
        Fetch the current Fear & Greed Index.
        
        Returns:
            FearGreedIndex with current value and classification, or None on error.
        """
        try:
            client = await self._get_client()
            response = await client.get(self.BASE_URL, params={"limit": 1})
            response.raise_for_status()
            
            data = response.json()
            
            if data.get("data") and len(data["data"]) > 0:
                fng_data = data["data"][0]
                
                # Parse timestamp (Unix timestamp in seconds)
                timestamp = datetime.fromtimestamp(int(fng_data.get("timestamp", 0)))
                
                return FearGreedIndex(
                    value=int(fng_data.get("value", 50)),
                    label=fng_data.get("value_classification", "Neutral"),
                    timestamp=timestamp,
                )
            
            logger.warning("No Fear & Greed data in response")
            return None
            
        except httpx.TimeoutException:
            logger.error("Timeout fetching Fear & Greed Index")
            return None
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching Fear & Greed Index: {e.response.status_code}")
            return None
        except Exception as e:
            logger.error(f"Error fetching Fear & Greed Index: {e}")
            return None
    
    async def get_historical(self, days: int = 7) -> list[FearGreedIndex]:
        """
        Fetch historical Fear & Greed Index values.
        
        Args:
            days: Number of days of history to fetch.
            
        Returns:
            List of FearGreedIndex objects ordered by date (newest first).
        """
        try:
            client = await self._get_client()
            response = await client.get(self.BASE_URL, params={"limit": days})
            response.raise_for_status()
            
            data = response.json()
            results = []
            
            for fng_data in data.get("data", []):
                timestamp = datetime.fromtimestamp(int(fng_data.get("timestamp", 0)))
                results.append(FearGreedIndex(
                    value=int(fng_data.get("value", 50)),
                    label=fng_data.get("value_classification", "Neutral"),
                    timestamp=timestamp,
                ))
            
            return results
            
        except Exception as e:
            logger.error(f"Error fetching historical Fear & Greed: {e}")
            return []
