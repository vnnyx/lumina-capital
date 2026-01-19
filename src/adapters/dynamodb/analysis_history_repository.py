"""DynamoDB storage adapter for analysis history."""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Optional

import boto3
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError

from src.domain.entities.analysis_history import AnalysisHistoryEntry, AnalysisOutcome
from src.domain.ports.analysis_history_port import AnalysisHistoryPort
from src.infrastructure.config import Settings
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)


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


class DynamoDBAnalysisHistoryAdapter(AnalysisHistoryPort):
    """
    DynamoDB implementation of AnalysisHistoryPort.
    
    Table schema:
        - PK (pk): ticker (e.g., "BTC")
        - SK (sk): timestamp ISO string (e.g., "2026-01-19T12:00:00")
        - TTL (ttl): Unix timestamp, auto-expires after 30 days
    """
    
    def __init__(self, settings: Settings):
        """Initialize DynamoDB adapter."""
        self.settings = settings
        self.table_name = f"{settings.dynamodb_table_name}_analysis_history"
        
        # Configure DynamoDB client
        client_kwargs: dict[str, Any] = {
            "region_name": settings.aws_region,
        }
        
        if settings.use_local_dynamodb:
            client_kwargs["endpoint_url"] = settings.dynamodb_endpoint_url
            logger.info("Using local DynamoDB", endpoint=settings.dynamodb_endpoint_url)
        
        self.dynamodb = boto3.resource("dynamodb", **client_kwargs)
        self.table = self.dynamodb.Table(self.table_name)
        
        logger.info("DynamoDB analysis history adapter initialized", table=self.table_name)
    
    async def initialize_table(self) -> None:
        """Create the DynamoDB table if it doesn't exist."""
        try:
            client = self.dynamodb.meta.client
            
            # Check if table exists
            existing_tables = client.list_tables()["TableNames"]
            if self.table_name in existing_tables:
                logger.info("Analysis history table already exists", table=self.table_name)
                return
            
            # Create table
            client.create_table(
                TableName=self.table_name,
                KeySchema=[
                    {"AttributeName": "pk", "KeyType": "HASH"},  # Partition key
                    {"AttributeName": "sk", "KeyType": "RANGE"},  # Sort key
                ],
                AttributeDefinitions=[
                    {"AttributeName": "pk", "AttributeType": "S"},
                    {"AttributeName": "sk", "AttributeType": "S"},
                ],
                BillingMode="PAY_PER_REQUEST",
            )
            
            # Wait for table to be created
            waiter = client.get_waiter("table_exists")
            waiter.wait(TableName=self.table_name)
            
            # Enable TTL
            client.update_time_to_live(
                TableName=self.table_name,
                TimeToLiveSpecification={
                    "Enabled": True,
                    "AttributeName": "ttl",
                },
            )
            
            logger.info("Created analysis history table", table=self.table_name)
            
        except ClientError as e:
            if e.response["Error"]["Code"] != "ResourceInUseException":
                logger.error("Failed to create analysis history table", error=str(e))
                raise

    async def save_history(self, entry: AnalysisHistoryEntry) -> bool:
        """Save an analysis history entry."""
        try:
            item = convert_floats_to_decimal(entry.to_dict())
            item["pk"] = entry.ticker
            item["sk"] = entry.timestamp.isoformat()
            
            self.table.put_item(Item=item)
            
            logger.debug(
                "saved_analysis_history",
                ticker=entry.ticker,
                timestamp=entry.timestamp.isoformat(),
            )
            return True
        except ClientError as e:
            logger.error("failed_to_save_history", error=str(e))
            return False

    async def get_pending_outcomes(self) -> list[AnalysisHistoryEntry]:
        """Get entries that are ready for outcome recording."""
        try:
            cutoff = (datetime.now() - timedelta(hours=4)).isoformat()
            
            # Scan for entries without outcome that are older than 4h
            # Note: In production, consider using a GSI for better performance
            response = self.table.scan(
                FilterExpression=Attr("sk").lt(cutoff) & Attr("outcome").not_exists()
            )
            
            items = response.get("Items", [])
            
            # Handle pagination
            while "LastEvaluatedKey" in response:
                response = self.table.scan(
                    FilterExpression=Attr("sk").lt(cutoff) & Attr("outcome").not_exists(),
                    ExclusiveStartKey=response["LastEvaluatedKey"]
                )
                items.extend(response.get("Items", []))
            
            return [
                AnalysisHistoryEntry.from_dict(convert_decimals_to_float(item))
                for item in items
            ]
        except ClientError as e:
            logger.error("failed_to_get_pending_outcomes", error=str(e))
            return []

    async def update_outcome(
        self,
        history_key: str,
        actual_price: float,
        price_change_pct: float,
        outcome_label: str,
        prediction_correct: Optional[bool],
    ) -> bool:
        """Update an entry with its outcome data."""
        try:
            # Parse history_key: TICKER#TIMESTAMP
            parts = history_key.split("#")
            if len(parts) != 2:
                logger.error("invalid_history_key", history_key=history_key)
                return False
            
            ticker = parts[0]
            # Convert YYYYMMDDHHMMSS to ISO format
            ts_str = parts[1]
            timestamp = datetime.strptime(ts_str, "%Y%m%d%H%M%S").isoformat()
            
            outcome = {
                "actual_price_after_4h": Decimal(str(actual_price)),
                "price_change_pct": Decimal(str(price_change_pct)),
                "prediction_correct": prediction_correct,
                "outcome_label": outcome_label,
                "recorded_at": datetime.now().isoformat(),
            }
            
            self.table.update_item(
                Key={"pk": ticker, "sk": timestamp},
                UpdateExpression="SET outcome = :outcome",
                ExpressionAttributeValues={":outcome": outcome},
            )
            
            logger.info(
                "updated_outcome",
                history_key=history_key,
                outcome_label=outcome_label,
            )
            return True
        except ClientError as e:
            logger.error("failed_to_update_outcome", error=str(e))
            return False

    async def get_history_for_ticker(
        self,
        ticker: str,
        limit: int = 100,
    ) -> list[AnalysisHistoryEntry]:
        """Get historical entries for a specific ticker."""
        try:
            response = self.table.query(
                KeyConditionExpression=Key("pk").eq(ticker),
                ScanIndexForward=False,  # Newest first
                Limit=limit,
            )
            
            return [
                AnalysisHistoryEntry.from_dict(convert_decimals_to_float(item))
                for item in response.get("Items", [])
            ]
        except ClientError as e:
            logger.error("failed_to_get_history", ticker=ticker, error=str(e))
            return []

    async def get_all_history(
        self,
        with_outcome_only: bool = False,
        limit: int = 500,
    ) -> list[AnalysisHistoryEntry]:
        """Get all historical entries."""
        try:
            scan_kwargs: dict[str, Any] = {}
            if with_outcome_only:
                scan_kwargs["FilterExpression"] = Attr("outcome").exists()
            
            response = self.table.scan(**scan_kwargs)
            items = response.get("Items", [])
            
            # Handle pagination up to limit
            while "LastEvaluatedKey" in response and len(items) < limit:
                scan_kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]
                response = self.table.scan(**scan_kwargs)
                items.extend(response.get("Items", []))
            
            # Sort by timestamp descending
            items.sort(key=lambda x: x.get("sk", ""), reverse=True)
            
            return [
                AnalysisHistoryEntry.from_dict(convert_decimals_to_float(item))
                for item in items[:limit]
            ]
        except ClientError as e:
            logger.error("failed_to_get_all_history", error=str(e))
            return []

    async def get_accuracy_stats(self, ticker: Optional[str] = None) -> dict:
        """Calculate prediction accuracy statistics."""
        try:
            if ticker:
                entries = await self.get_history_for_ticker(ticker, limit=500)
            else:
                entries = await self.get_all_history(with_outcome_only=True, limit=500)
            
            with_outcomes = [e for e in entries if e.has_outcome]
            
            total = len(with_outcomes)
            correct = sum(1 for e in with_outcomes if e.outcome and e.outcome.outcome_label == "correct")
            wrong = sum(1 for e in with_outcomes if e.outcome and e.outcome.outcome_label == "wrong")
            neutral = sum(1 for e in with_outcomes if e.outcome and e.outcome.outcome_label == "neutral")
            
            accuracy_pct = (correct / total * 100) if total > 0 else 0.0
            
            return {
                "total": total,
                "correct": correct,
                "wrong": wrong,
                "neutral": neutral,
                "accuracy_pct": round(accuracy_pct, 2),
                "ticker": ticker,
            }
        except Exception as e:
            logger.error("failed_to_get_accuracy_stats", error=str(e))
            return {"total": 0, "correct": 0, "wrong": 0, "neutral": 0, "accuracy_pct": 0.0}
