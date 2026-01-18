"""
Storage Port - Interface for data persistence.
"""

from abc import ABC, abstractmethod
from typing import Optional

from src.domain.entities.coin_analysis import CoinAnalysis


class StoragePort(ABC):
    """
    Port interface for data storage operations.
    
    Implementations:
        - DynamoDBStorageAdapter: AWS DynamoDB storage
        - LocalStorageAdapter: Local JSON file storage for testing
    """
    
    @abstractmethod
    async def save_coin_analysis(self, analysis: CoinAnalysis) -> bool:
        """
        Save or update a coin analysis record.
        
        Args:
            analysis: CoinAnalysis entity to store
            
        Returns:
            True if saved successfully.
        """
        ...
    
    @abstractmethod
    async def get_coin_analysis(self, partition_key: str) -> Optional[CoinAnalysis]:
        """
        Retrieve a coin analysis by partition key.
        
        Args:
            partition_key: Key in format TICKER-COINNAME
            
        Returns:
            CoinAnalysis or None if not found.
        """
        ...
    
    @abstractmethod
    async def get_all_analyses(self) -> list[CoinAnalysis]:
        """
        Retrieve all coin analyses.
        
        Returns:
            List of all CoinAnalysis records.
        """
        ...
    
    @abstractmethod
    async def get_analyses_by_volume_rank(
        self, 
        min_rank: int = 1, 
        max_rank: int = 200
    ) -> list[CoinAnalysis]:
        """
        Retrieve analyses within a volume rank range.
        
        Args:
            min_rank: Minimum rank (1 = highest volume)
            max_rank: Maximum rank
            
        Returns:
            List of CoinAnalysis sorted by volume rank.
        """
        ...
    
    @abstractmethod
    async def delete_coin_analysis(self, partition_key: str) -> bool:
        """
        Delete a coin analysis record.
        
        Args:
            partition_key: Key in format TICKER-COINNAME
            
        Returns:
            True if deleted successfully.
        """
        ...
    
    @abstractmethod
    async def batch_save_analyses(self, analyses: list[CoinAnalysis]) -> int:
        """
        Save multiple analyses in batch.
        
        Args:
            analyses: List of CoinAnalysis to save
            
        Returns:
            Number of successfully saved items.
        """
        ...
    
    @abstractmethod
    async def save_trade_decision(self, decision: dict) -> bool:
        """
        Save a trade decision for audit trail.
        
        Args:
            decision: Trade decision as dictionary
            
        Returns:
            True if saved successfully.
        """
        ...
    
    @abstractmethod
    async def get_recent_decisions(self, limit: int = 50) -> list[dict]:
        """
        Get recent trade decisions.
        
        Args:
            limit: Maximum number of decisions to return
            
        Returns:
            List of recent trade decisions.
        """
        ...
