"""
CoinGecko Adapter - Fetches coin market metrics.

API Documentation: https://www.coingecko.com/en/api/documentation
Free tier: 30 calls/minute, no API key required for basic endpoints.
"""

import logging
from datetime import datetime
from typing import Optional

import httpx

from src.domain.entities.fundamental_data import CoinMetrics

logger = logging.getLogger(__name__)


# Mapping from common tickers to CoinGecko IDs
TICKER_TO_COINGECKO_ID = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "BNB": "binancecoin",
    "XRP": "ripple",
    "ADA": "cardano",
    "DOGE": "dogecoin",
    "AVAX": "avalanche-2",
    "DOT": "polkadot",
    "MATIC": "matic-network",
    "LINK": "chainlink",
    "SHIB": "shiba-inu",
    "LTC": "litecoin",
    "UNI": "uniswap",
    "ATOM": "cosmos",
    "XLM": "stellar",
    "ETC": "ethereum-classic",
    "FIL": "filecoin",
    "APT": "aptos",
    "NEAR": "near",
    "ARB": "arbitrum",
    "OP": "optimism",
    "SUI": "sui",
    "INJ": "injective-protocol",
    "SEI": "sei-network",
    "TIA": "celestia",
    "PEPE": "pepe",
    "WIF": "dogwifcoin",
    "BONK": "bonk",
    "FLOKI": "floki",
    "RENDER": "render-token",
    "FET": "fetch-ai",
    "RNDR": "render-token",
    "GRT": "the-graph",
    "IMX": "immutable-x",
    "SAND": "the-sandbox",
    "MANA": "decentraland",
    "AXS": "axie-infinity",
    "GALA": "gala",
    "ENJ": "enjincoin",
    "CHZ": "chiliz",
    "CRV": "curve-dao-token",
    "AAVE": "aave",
    "MKR": "maker",
    "SNX": "havven",
    "COMP": "compound-governance-token",
    "SUSHI": "sushi",
    "YFI": "yearn-finance",
    "1INCH": "1inch",
    "BGB": "bitget-token",
}

# Cache for dynamically discovered ticker mappings
_dynamic_ticker_cache: dict[str, Optional[str]] = {}


class CoinGeckoAdapter:
    """
    Adapter for CoinGecko API.
    
    Free tier limits:
    - 30 calls/minute
    - No API key required for basic endpoints
    
    This adapter batches requests to minimize API calls.
    """
    
    BASE_URL = "https://api.coingecko.com/api/v3"
    TIMEOUT = 15.0
    MAX_COINS_PER_REQUEST = 100  # CoinGecko limit
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the adapter.
        
        Args:
            api_key: Optional CoinGecko API key for higher rate limits.
        """
        self._client: Optional[httpx.AsyncClient] = None
        self._api_key = api_key
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            headers = {}
            if self._api_key:
                headers["x-cg-demo-api-key"] = self._api_key
            self._client = httpx.AsyncClient(
                timeout=self.TIMEOUT,
                headers=headers,
            )
        return self._client
    
    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
    
    def _ticker_to_id(self, ticker: str) -> Optional[str]:
        """Convert ticker to CoinGecko ID (from static mapping only)."""
        return TICKER_TO_COINGECKO_ID.get(ticker.upper())
    
    async def _search_ticker(self, ticker: str) -> Optional[str]:
        """
        Search for a ticker on CoinGecko and return its ID.
        
        Uses the /search endpoint to find coins by symbol.
        Results are cached to avoid repeated API calls.
        
        Args:
            ticker: Coin ticker symbol (e.g., "RIVER")
            
        Returns:
            CoinGecko ID if found, None otherwise.
        """
        ticker_upper = ticker.upper()
        
        # Check dynamic cache first
        if ticker_upper in _dynamic_ticker_cache:
            return _dynamic_ticker_cache[ticker_upper]
        
        try:
            client = await self._get_client()
            response = await client.get(
                f"{self.BASE_URL}/search",
                params={"query": ticker},
            )
            response.raise_for_status()
            
            data = response.json()
            coins = data.get("coins", [])
            
            # Find exact symbol match (case-insensitive)
            for coin in coins:
                if coin.get("symbol", "").upper() == ticker_upper:
                    cg_id = coin.get("id")
                    _dynamic_ticker_cache[ticker_upper] = cg_id
                    logger.info(
                        f"Discovered CoinGecko ID for ticker: {ticker_upper} -> {cg_id}"
                    )
                    return cg_id
            
            # No match found, cache as None to avoid repeated searches
            _dynamic_ticker_cache[ticker_upper] = None
            logger.debug(f"No CoinGecko match found for ticker: {ticker}")
            return None
            
        except Exception as e:
            logger.warning(f"Failed to search CoinGecko for ticker {ticker}: {e}")
            # Don't cache failures to allow retry
            return None
    
    async def get_coin_metrics(self, tickers: list[str]) -> dict[str, CoinMetrics]:
        """
        Fetch market metrics for multiple coins in a single request.
        
        Args:
            tickers: List of coin tickers (e.g., ["BTC", "ETH"])
            
        Returns:
            Dictionary mapping ticker to CoinMetrics.
        """
        results: dict[str, CoinMetrics] = {}
        
        # Convert tickers to CoinGecko IDs
        ticker_to_id = {}
        unknown_tickers = []
        
        for ticker in tickers:
            # First check static mapping
            cg_id = self._ticker_to_id(ticker)
            if cg_id:
                ticker_to_id[ticker.upper()] = cg_id
            else:
                unknown_tickers.append(ticker)
        
        # Auto-lookup unknown tickers via search API
        if unknown_tickers:
            logger.info(f"Looking up {len(unknown_tickers)} unknown tickers on CoinGecko")
            for ticker in unknown_tickers:
                cg_id = await self._search_ticker(ticker)
                if cg_id:
                    ticker_to_id[ticker.upper()] = cg_id
        
        if not ticker_to_id:
            return results
        
        try:
            client = await self._get_client()
            
            # Fetch all coins in a single request using /coins/markets
            ids = ",".join(ticker_to_id.values())
            response = await client.get(
                f"{self.BASE_URL}/coins/markets",
                params={
                    "vs_currency": "usd",
                    "ids": ids,
                    "order": "market_cap_desc",
                    "per_page": self.MAX_COINS_PER_REQUEST,
                    "page": 1,
                    "sparkline": "false",
                    "price_change_percentage": "7d,30d",
                },
            )
            response.raise_for_status()
            
            data = response.json()
            
            # Create reverse mapping: CoinGecko ID -> ticker
            id_to_ticker = {v: k for k, v in ticker_to_id.items()}
            
            for coin_data in data:
                cg_id = coin_data.get("id")
                ticker = id_to_ticker.get(cg_id)
                
                if not ticker:
                    continue
                
                results[ticker] = CoinMetrics(
                    ticker=ticker,
                    market_cap=coin_data.get("market_cap"),
                    market_cap_rank=coin_data.get("market_cap_rank"),
                    fully_diluted_valuation=coin_data.get("fully_diluted_valuation"),
                    total_volume=coin_data.get("total_volume"),
                    circulating_supply=coin_data.get("circulating_supply"),
                    total_supply=coin_data.get("total_supply"),
                    max_supply=coin_data.get("max_supply"),
                    ath=coin_data.get("ath"),
                    ath_change_percentage=coin_data.get("ath_change_percentage"),
                    atl=coin_data.get("atl"),
                    atl_change_percentage=coin_data.get("atl_change_percentage"),
                    price_change_7d=coin_data.get("price_change_percentage_7d_in_currency"),
                    price_change_30d=coin_data.get("price_change_percentage_30d_in_currency"),
                    last_updated=datetime.now(),
                )
            
            logger.info(f"Fetched CoinGecko metrics for {len(results)} coins")
            return results
            
        except httpx.TimeoutException:
            logger.error("Timeout fetching CoinGecko data")
            return results
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching CoinGecko data: {e.response.status_code}")
            if e.response.status_code == 429:
                logger.warning("CoinGecko rate limit exceeded")
            return results
        except Exception as e:
            logger.error(f"Error fetching CoinGecko data: {e}")
            return results
    
    async def get_global_data(self) -> Optional[dict]:
        """
        Fetch global cryptocurrency market data.
        
        Returns:
            Dictionary with global market stats or None on error.
        """
        try:
            client = await self._get_client()
            response = await client.get(f"{self.BASE_URL}/global")
            response.raise_for_status()
            
            data = response.json()
            return data.get("data")
            
        except Exception as e:
            logger.error(f"Error fetching global data: {e}")
            return None
