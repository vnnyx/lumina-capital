"""
Analysis History Port - Interface for historical analysis storage.
"""

from abc import ABC, abstractmethod
from typing import Optional

from src.domain.entities.analysis_history import AnalysisHistoryEntry


class AnalysisHistoryPort(ABC):
    """
    Port interface for analysis history storage operations.
    
    Implementations:
        - JsonAnalysisHistoryAdapter: Local JSON file storage
        - DynamoDBAnalysisHistoryAdapter: AWS DynamoDB storage
    """
    
    @abstractmethod
    async def save_history(self, entry: AnalysisHistoryEntry) -> bool:
        """
        Save an analysis history entry.
        
        Args:
            entry: AnalysisHistoryEntry to store
            
        Returns:
            True if saved successfully.
        """
        ...
    
    @abstractmethod
    async def get_pending_outcomes(self) -> list[AnalysisHistoryEntry]:
        """
        Get entries that are ready for outcome recording (4h+ old, no outcome yet).
        
        Returns:
            List of entries awaiting outcome backfill.
        """
        ...
    
    @abstractmethod
    async def update_outcome(
        self,
        history_key: str,
        actual_price: float,
        price_change_pct: float,
        outcome_label: str,
        prediction_correct: Optional[bool],
    ) -> bool:
        """
        Update an entry with its outcome data.
        
        Args:
            history_key: The entry's history_key (TICKER#TIMESTAMP)
            actual_price: Price 4 hours after analysis
            price_change_pct: Percentage change from analysis price
            outcome_label: "correct", "wrong", or "neutral"
            prediction_correct: True/False/None based on threshold
            
        Returns:
            True if updated successfully.
        """
        ...
    
    @abstractmethod
    async def get_history_for_ticker(
        self,
        ticker: str,
        limit: int = 100,
    ) -> list[AnalysisHistoryEntry]:
        """
        Get historical entries for a specific ticker.
        
        Args:
            ticker: Coin ticker (e.g., "BTC")
            limit: Maximum entries to return
            
        Returns:
            List of history entries, newest first.
        """
        ...
    
    @abstractmethod
    async def get_all_history(
        self,
        with_outcome_only: bool = False,
        limit: int = 500,
    ) -> list[AnalysisHistoryEntry]:
        """
        Get all historical entries.
        
        Args:
            with_outcome_only: If True, only return entries with outcomes
            limit: Maximum entries to return
            
        Returns:
            List of history entries, newest first.
        """
        ...
    
    @abstractmethod
    async def get_accuracy_stats(self, ticker: Optional[str] = None) -> dict:
        """
        Calculate prediction accuracy statistics.
        
        Args:
            ticker: Optional ticker to filter by
            
        Returns:
            Dict with accuracy stats: total, correct, wrong, neutral, accuracy_pct
        """
        ...
