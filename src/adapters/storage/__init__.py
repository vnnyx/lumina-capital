"""Storage adapters."""

from src.adapters.storage.json_storage_adapter import JSONStorageAdapter
from src.adapters.storage.json_analysis_history import JsonAnalysisHistoryAdapter
from src.adapters.storage.paper_trades_tracker import PaperTradesTracker
from src.adapters.storage.json_trade_outcome import JsonTradeOutcomeAdapter

__all__ = [
    "JSONStorageAdapter",
    "JsonAnalysisHistoryAdapter",
    "PaperTradesTracker",
    "JsonTradeOutcomeAdapter",
]
