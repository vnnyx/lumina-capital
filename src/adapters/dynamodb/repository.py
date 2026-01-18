"""
DynamoDB Storage Adapter - Implements StoragePort.
"""

import json
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

import boto3
from botocore.exceptions import ClientError

from src.domain.entities.coin_analysis import CoinAnalysis
from src.domain.ports.storage_port import StoragePort
from src.infrastructure.config import Settings
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)


class DecimalEncoder(json.JSONEncoder):
    """JSON encoder that handles Decimal types from DynamoDB."""
    
    def default(self, obj: Any) -> Any:
        if isinstance(obj, Decimal):
            return str(obj)
        return super().default(obj)


def convert_floats_to_decimal(obj: Any) -> Any:
    """Convert float values to Decimal for DynamoDB compatibility."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    elif isinstance(obj, dict):
        return {k: convert_floats_to_decimal(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_floats_to_decimal(v) for v in obj]
    return obj


def convert_decimals_to_float(obj: Any) -> Any:
    """Convert Decimal values back to float/int."""
    if isinstance(obj, Decimal):
        if obj % 1 == 0:
            return int(obj)
        return float(obj)
    elif isinstance(obj, dict):
        return {k: convert_decimals_to_float(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_decimals_to_float(v) for v in obj]
    return obj


class DynamoDBStorageAdapter(StoragePort):
    """
    DynamoDB implementation of StoragePort.
    
    Stores coin analysis data and trade decisions in DynamoDB tables.
    """
    
    def __init__(self, settings: Settings):
        """
        Initialize DynamoDB adapter.
        
        Args:
            settings: Application settings with AWS credentials.
        """
        self.settings = settings
        self.table_name = settings.dynamodb_table_name
        self.decisions_table_name = f"{settings.dynamodb_table_name}_decisions"
        
        # Configure DynamoDB client
        client_kwargs: dict[str, Any] = {
            "region_name": settings.aws_region,
        }
        
        # Use local endpoint for development
        if settings.use_local_dynamodb:
            client_kwargs["endpoint_url"] = settings.dynamodb_endpoint_url
            logger.info("Using local DynamoDB", endpoint=settings.dynamodb_endpoint_url)
        
        # Use explicit credentials if provided
        if settings.aws_access_key_id and settings.aws_secret_access_key:
            client_kwargs["aws_access_key_id"] = settings.aws_access_key_id
            client_kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
        
        self.dynamodb = boto3.resource("dynamodb", **client_kwargs)
        self.table = self.dynamodb.Table(self.table_name)
        self.decisions_table = self.dynamodb.Table(self.decisions_table_name)
    
    async def initialize_tables(self) -> None:
        """Create DynamoDB tables if they don't exist."""
        await self._create_table_if_not_exists(
            table_name=self.table_name,
            key_schema=[{"AttributeName": "pk", "KeyType": "HASH"}],
            attribute_definitions=[{"AttributeName": "pk", "AttributeType": "S"}],
        )
        
        await self._create_table_if_not_exists(
            table_name=self.decisions_table_name,
            key_schema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            attribute_definitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
        )
    
    async def _create_table_if_not_exists(
        self,
        table_name: str,
        key_schema: list[dict],
        attribute_definitions: list[dict],
    ) -> None:
        """Create a DynamoDB table if it doesn't exist."""
        try:
            client = self.dynamodb.meta.client
            client.describe_table(TableName=table_name)
            logger.debug("Table exists", table=table_name)
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                logger.info("Creating table", table=table_name)
                client.create_table(
                    TableName=table_name,
                    KeySchema=key_schema,
                    AttributeDefinitions=attribute_definitions,
                    BillingMode="PAY_PER_REQUEST",
                )
                # Wait for table to be active
                waiter = client.get_waiter("table_exists")
                waiter.wait(TableName=table_name)
                logger.info("Table created", table=table_name)
            else:
                raise
    
    async def save_coin_analysis(self, analysis: CoinAnalysis) -> bool:
        """Save or update a coin analysis record."""
        logger.debug("Saving coin analysis", pk=analysis.partition_key)
        
        try:
            item = convert_floats_to_decimal(analysis.to_dynamodb_item())
            self.table.put_item(Item=item)
            return True
        except ClientError as e:
            logger.error("Failed to save analysis", pk=analysis.partition_key, error=str(e))
            return False
    
    async def get_coin_analysis(self, partition_key: str) -> Optional[CoinAnalysis]:
        """Retrieve a coin analysis by partition key."""
        logger.debug("Getting coin analysis", pk=partition_key)
        
        try:
            response = self.table.get_item(Key={"pk": partition_key})
            item = response.get("Item")
            
            if not item:
                return None
            
            item = convert_decimals_to_float(item)
            return CoinAnalysis.from_dynamodb_item(item)
        
        except ClientError as e:
            logger.error("Failed to get analysis", pk=partition_key, error=str(e))
            return None
    
    async def get_all_analyses(self) -> list[CoinAnalysis]:
        """Retrieve all coin analyses."""
        logger.info("Getting all analyses")
        
        analyses = []
        
        try:
            response = self.table.scan()
            items = response.get("Items", [])
            
            # Handle pagination
            while "LastEvaluatedKey" in response:
                response = self.table.scan(
                    ExclusiveStartKey=response["LastEvaluatedKey"]
                )
                items.extend(response.get("Items", []))
            
            for item in items:
                item = convert_decimals_to_float(item)
                analyses.append(CoinAnalysis.from_dynamodb_item(item))
            
            logger.info("Retrieved analyses", count=len(analyses))
            return analyses
        
        except ClientError as e:
            logger.error("Failed to scan analyses", error=str(e))
            return []
    
    async def get_analyses_by_volume_rank(
        self,
        min_rank: int = 1,
        max_rank: int = 200,
    ) -> list[CoinAnalysis]:
        """Retrieve analyses within a volume rank range."""
        logger.debug("Getting analyses by rank", min_rank=min_rank, max_rank=max_rank)
        
        # Scan with filter (not ideal but works for <1000 items)
        analyses = await self.get_all_analyses()
        
        filtered = [
            a for a in analyses
            if min_rank <= a.volume_rank <= max_rank
        ]
        
        # Sort by volume rank
        filtered.sort(key=lambda a: a.volume_rank)
        
        return filtered
    
    async def delete_coin_analysis(self, partition_key: str) -> bool:
        """Delete a coin analysis record."""
        logger.debug("Deleting coin analysis", pk=partition_key)
        
        try:
            self.table.delete_item(Key={"pk": partition_key})
            return True
        except ClientError as e:
            logger.error("Failed to delete analysis", pk=partition_key, error=str(e))
            return False
    
    async def batch_save_analyses(self, analyses: list[CoinAnalysis]) -> int:
        """Save multiple analyses in batch."""
        logger.info("Batch saving analyses", count=len(analyses))
        
        saved_count = 0
        
        try:
            with self.table.batch_writer() as batch:
                for analysis in analyses:
                    item = convert_floats_to_decimal(analysis.to_dynamodb_item())
                    batch.put_item(Item=item)
                    saved_count += 1
            
            logger.info("Batch save complete", saved=saved_count)
            return saved_count
        
        except ClientError as e:
            logger.error("Batch save failed", error=str(e), saved=saved_count)
            return saved_count
    
    async def save_trade_decision(self, decision: dict) -> bool:
        """Save a trade decision for audit trail."""
        logger.debug("Saving trade decision", symbol=decision.get("symbol"))
        
        try:
            # Use date as partition key and timestamp as sort key
            now = datetime.now()
            item = {
                "pk": f"DECISION#{now.strftime('%Y-%m-%d')}",
                "sk": now.isoformat(),
                **convert_floats_to_decimal(decision),
            }
            
            self.decisions_table.put_item(Item=item)
            return True
        
        except ClientError as e:
            logger.error("Failed to save decision", error=str(e))
            return False
    
    async def get_recent_decisions(self, limit: int = 50) -> list[dict]:
        """Get recent trade decisions."""
        logger.debug("Getting recent decisions", limit=limit)
        
        try:
            # Get today's decisions
            today = datetime.now().strftime("%Y-%m-%d")
            
            response = self.decisions_table.query(
                KeyConditionExpression="pk = :pk",
                ExpressionAttributeValues={":pk": f"DECISION#{today}"},
                ScanIndexForward=False,  # Newest first
                Limit=limit,
            )
            
            items = response.get("Items", [])
            return [convert_decimals_to_float(item) for item in items]
        
        except ClientError as e:
            logger.error("Failed to get decisions", error=str(e))
            return []
