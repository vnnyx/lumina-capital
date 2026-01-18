"""
Bitget API adapter package.
"""

from src.adapters.bitget.client import BitgetClient
from src.adapters.bitget.market_data_adapter import BitgetMarketDataAdapter
from src.adapters.bitget.trading_adapter import BitgetTradingAdapter

__all__ = [
    "BitgetClient",
    "BitgetMarketDataAdapter",
    "BitgetTradingAdapter",
]
