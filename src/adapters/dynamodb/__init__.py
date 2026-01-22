"""
DynamoDB adapter package.
"""

from src.adapters.dynamodb.repository import DynamoDBStorageAdapter
from src.adapters.dynamodb.analysis_history_repository import DynamoDBAnalysisHistoryAdapter
from src.adapters.dynamodb.paper_trades_repository import DynamoDBPaperTradesAdapter
from src.adapters.dynamodb.trade_outcome_repository import DynamoDBTradeOutcomeAdapter

__all__ = [
    "DynamoDBStorageAdapter",
    "DynamoDBAnalysisHistoryAdapter",
    "DynamoDBPaperTradesAdapter",
    "DynamoDBTradeOutcomeAdapter",
]
