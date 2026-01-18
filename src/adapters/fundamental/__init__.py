"""
Fundamental data adapters - External API integrations.
"""

from src.adapters.fundamental.alternative_me_adapter import AlternativeMeAdapter
from src.adapters.fundamental.coingecko_adapter import CoinGeckoAdapter
from src.adapters.fundamental.fundamental_data_service import FundamentalDataService

__all__ = [
    "AlternativeMeAdapter",
    "CoinGeckoAdapter",
    "FundamentalDataService",
]
