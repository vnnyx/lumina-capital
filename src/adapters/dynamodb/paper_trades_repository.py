"""DynamoDB storage adapter for paper trades."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from src.domain.ports.paper_trades_port import PaperPosition, PaperTradesPort
from src.infrastructure.config import Settings
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)


def convert_floats_to_decimal(obj: Any) -> Any:
    """Convert float values to Decimal for DynamoDB."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    elif isinstance(obj, dict):
        return {k: convert_floats_to_decimal(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_floats_to_decimal(v) for v in obj]
    return obj


def convert_decimals_to_float(obj: Any) -> Any:
    """Convert Decimal values back to float."""
    if isinstance(obj, Decimal):
        if obj % 1 == 0:
            return int(obj)
        return float(obj)
    elif isinstance(obj, dict):
        return {k: convert_decimals_to_float(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_decimals_to_float(v) for v in obj]
    return obj


class DynamoDBPaperTradesAdapter(PaperTradesPort):
    """
    DynamoDB implementation of PaperTradesPort.
    
    Table schema for positions:
        - PK (pk): "POSITION"
        - SK (sk): coin ticker (e.g., "BTC")
    
    Table schema for trade history:
        - PK (pk): "TRADE"
        - SK (sk): timestamp ISO string
    """
    
    def __init__(self, settings: Settings):
        """Initialize DynamoDB adapter."""
        self.settings = settings
        self.table_name = f"{settings.dynamodb_table_name}_paper_trades"
        
        client_kwargs: dict[str, Any] = {
            "region_name": settings.aws_region,
        }
        
        if settings.use_local_dynamodb:
            client_kwargs["endpoint_url"] = settings.dynamodb_endpoint_url
            logger.info("Using local DynamoDB", endpoint=settings.dynamodb_endpoint_url)
        
        self.dynamodb = boto3.resource("dynamodb", **client_kwargs)
        self.table = self.dynamodb.Table(self.table_name)
        
        logger.info("DynamoDB paper trades adapter initialized", table=self.table_name)
    
    async def initialize_table(self) -> None:
        """Create the DynamoDB table if it doesn't exist."""
        try:
            client = self.dynamodb.meta.client
            
            existing_tables = client.list_tables()["TableNames"]
            if self.table_name in existing_tables:
                logger.info("Paper trades table already exists", table=self.table_name)
                return
            
            client.create_table(
                TableName=self.table_name,
                KeySchema=[
                    {"AttributeName": "pk", "KeyType": "HASH"},
                    {"AttributeName": "sk", "KeyType": "RANGE"},
                ],
                AttributeDefinitions=[
                    {"AttributeName": "pk", "AttributeType": "S"},
                    {"AttributeName": "sk", "AttributeType": "S"},
                ],
                BillingMode="PAY_PER_REQUEST",
            )
            
            waiter = client.get_waiter("table_exists")
            waiter.wait(TableName=self.table_name)
            
            logger.info("Created paper trades table", table=self.table_name)
            
        except ClientError as e:
            if e.response["Error"]["Code"] != "ResourceInUseException":
                logger.error("Failed to create paper trades table", error=str(e))
                raise

    async def record_buy(
        self,
        coin: str,
        quantity: float,
        price: float,
    ) -> PaperPosition:
        """Record a paper buy trade."""
        coin = coin.upper()
        now = datetime.now()
        
        # Get existing position
        existing = await self.get_position(coin)
        
        if existing:
            # Update with weighted average
            new_total_cost = existing.total_cost + (quantity * price)
            new_quantity = existing.quantity + quantity
            new_avg_price = new_total_cost / new_quantity if new_quantity > 0 else 0
            
            position = PaperPosition(
                coin=coin,
                quantity=new_quantity,
                avg_entry_price=new_avg_price,
                total_cost=new_total_cost,
                created_at=existing.created_at,
                updated_at=now,
            )
        else:
            position = PaperPosition(
                coin=coin,
                quantity=quantity,
                avg_entry_price=price,
                total_cost=quantity * price,
                created_at=now,
                updated_at=now,
            )
        
        # Save position
        try:
            item = convert_floats_to_decimal(position.to_dict())
            item["pk"] = "POSITION"
            item["sk"] = coin
            self.table.put_item(Item=item)
        except ClientError as e:
            logger.error("Failed to save paper position", error=str(e))
            raise
        
        # Record trade history
        await self._record_trade("buy", coin, quantity, price)
        
        logger.info(
            "Paper buy recorded",
            coin=coin,
            quantity=quantity,
            price=price,
            new_avg_price=position.avg_entry_price,
        )
        
        return position

    async def record_sell(
        self,
        coin: str,
        quantity: float,
        price: float,
    ) -> Optional[PaperPosition]:
        """Record a paper sell trade."""
        coin = coin.upper()
        now = datetime.now()
        
        existing = await self.get_position(coin)
        if not existing:
            logger.warning("No paper position to sell", coin=coin)
            return None
        
        new_quantity = existing.quantity - quantity
        realized_pnl = (price - existing.avg_entry_price) * quantity
        
        if new_quantity <= 0:
            # Position fully closed - delete it
            try:
                self.table.delete_item(Key={"pk": "POSITION", "sk": coin})
            except ClientError as e:
                logger.error("Failed to delete paper position", error=str(e))
            result = None
        else:
            # Reduce position
            new_total_cost = new_quantity * existing.avg_entry_price
            position = PaperPosition(
                coin=coin,
                quantity=new_quantity,
                avg_entry_price=existing.avg_entry_price,
                total_cost=new_total_cost,
                created_at=existing.created_at,
                updated_at=now,
            )
            
            try:
                item = convert_floats_to_decimal(position.to_dict())
                item["pk"] = "POSITION"
                item["sk"] = coin
                self.table.put_item(Item=item)
            except ClientError as e:
                logger.error("Failed to update paper position", error=str(e))
                raise
            
            result = position
        
        # Record trade history
        await self._record_trade("sell", coin, quantity, price, realized_pnl)
        
        logger.info(
            "Paper sell recorded",
            coin=coin,
            quantity=quantity,
            price=price,
            realized_pnl=realized_pnl,
        )
        
        return result

    async def _record_trade(
        self,
        trade_type: str,
        coin: str,
        quantity: float,
        price: float,
        realized_pnl: Optional[float] = None,
    ) -> None:
        """Record a trade in history."""
        now = datetime.now()
        trade = {
            "pk": "TRADE",
            "sk": now.isoformat(),
            "type": trade_type,
            "coin": coin,
            "quantity": Decimal(str(quantity)),
            "price": Decimal(str(price)),
            "timestamp": now.isoformat(),
        }
        if realized_pnl is not None:
            trade["realized_pnl"] = Decimal(str(realized_pnl))
        
        try:
            self.table.put_item(Item=trade)
        except ClientError as e:
            logger.warning("Failed to record trade history", error=str(e))

    async def get_position(self, coin: str) -> Optional[PaperPosition]:
        """Get paper position for a coin."""
        try:
            response = self.table.get_item(Key={"pk": "POSITION", "sk": coin.upper()})
            item = response.get("Item")
            if item:
                return PaperPosition.from_dict(convert_decimals_to_float(item))
            return None
        except ClientError as e:
            logger.error("Failed to get paper position", error=str(e))
            return None

    async def get_all_positions(self) -> dict[str, PaperPosition]:
        """Get all paper positions."""
        try:
            response = self.table.query(
                KeyConditionExpression=Key("pk").eq("POSITION")
            )
            positions = {}
            for item in response.get("Items", []):
                pos = PaperPosition.from_dict(convert_decimals_to_float(item))
                positions[pos.coin] = pos
            return positions
        except ClientError as e:
            logger.error("Failed to get all paper positions", error=str(e))
            return {}

    async def get_cost_basis(self, coin: str) -> Optional[float]:
        """Get average entry price for a coin."""
        position = await self.get_position(coin)
        return position.avg_entry_price if position else None

    async def clear_all(self) -> None:
        """Clear all paper positions and trade history."""
        try:
            # Delete all positions
            positions = await self.get_all_positions()
            for coin in positions:
                self.table.delete_item(Key={"pk": "POSITION", "sk": coin})
            
            # Delete trade history
            response = self.table.query(
                KeyConditionExpression=Key("pk").eq("TRADE")
            )
            for item in response.get("Items", []):
                self.table.delete_item(Key={"pk": "TRADE", "sk": item["sk"]})
            
            logger.info("Paper trades cleared")
        except ClientError as e:
            logger.error("Failed to clear paper trades", error=str(e))

    async def get_trade_history(self, limit: int = 100) -> list[dict]:
        """Get recent trade history."""
        try:
            response = self.table.query(
                KeyConditionExpression=Key("pk").eq("TRADE"),
                ScanIndexForward=False,  # Newest first
                Limit=limit,
            )
            return [convert_decimals_to_float(item) for item in response.get("Items", [])]
        except ClientError as e:
            logger.error("Failed to get trade history", error=str(e))
            return []
