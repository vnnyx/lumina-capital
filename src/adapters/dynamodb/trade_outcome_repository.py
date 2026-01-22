"""DynamoDB storage adapter for trade outcomes and P&L tracking."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

import boto3
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError

from src.domain.entities.trade_outcome import (
    TradeOutcome,
    OutcomeStatus,
    PositionPerformance,
    PortfolioStats,
)
from src.domain.ports.trade_outcome_port import TradeOutcomePort
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


class DynamoDBTradeOutcomeAdapter(TradeOutcomePort):
    """
    DynamoDB implementation of TradeOutcomePort.
    
    Table schema for trade outcomes:
        - PK (pk): "OUTCOME#{coin}" (e.g., "OUTCOME#BTC")
        - SK (sk): "{status}#{timestamp}#{outcome_id}" for ordering
        
    Table schema for position performance:
        - PK (pk): "POSITION_PERF"
        - SK (sk): coin ticker (e.g., "BTC")
        
    Table schema for portfolio stats:
        - PK (pk): "PORTFOLIO_STATS"
        - SK (sk): "CURRENT"
    """
    
    def __init__(self, settings: Settings):
        """Initialize DynamoDB adapter."""
        self.settings = settings
        self.table_name = f"{settings.dynamodb_table_name}_trade_outcomes"
        
        client_kwargs: dict[str, Any] = {
            "region_name": settings.aws_region,
        }
        
        if settings.use_local_dynamodb:
            client_kwargs["endpoint_url"] = settings.dynamodb_endpoint_url
            logger.info("Using local DynamoDB for trade outcomes", endpoint=settings.dynamodb_endpoint_url)
        
        self.dynamodb = boto3.resource("dynamodb", **client_kwargs)
        self.table = self.dynamodb.Table(self.table_name)
        
        logger.info("DynamoDB trade outcomes adapter initialized", table=self.table_name)
    
    async def initialize_table(self) -> None:
        """Create the DynamoDB table if it doesn't exist."""
        try:
            client = self.dynamodb.meta.client
            
            existing_tables = client.list_tables()["TableNames"]
            if self.table_name in existing_tables:
                logger.info("Trade outcomes table already exists", table=self.table_name)
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
            
            logger.info("Created trade outcomes table", table=self.table_name)
            
        except ClientError as e:
            if e.response["Error"]["Code"] != "ResourceInUseException":
                logger.error("Failed to create trade outcomes table", error=str(e))
                raise

    async def record_entry(
        self,
        symbol: str,
        coin: str,
        price: float,
        quantity: float,
        reasoning: str = "",
    ) -> TradeOutcome:
        """Record a new trade entry (buy)."""
        coin = coin.upper()
        now = datetime.now()
        
        outcome = TradeOutcome(
            symbol=symbol,
            coin=coin,
            entry_price=price,
            entry_quantity=quantity,
            entry_timestamp=now,
            entry_decision_reasoning=reasoning,
            status=OutcomeStatus.OPEN,
            remaining_quantity=quantity,
        )
        
        # Save to DynamoDB
        # SK format: {status}#{timestamp}#{id} for proper ordering
        sk = f"{outcome.status.value}#{now.isoformat()}#{outcome.outcome_id}"
        
        try:
            item = convert_floats_to_decimal(outcome.to_dict())
            item["pk"] = f"OUTCOME#{coin}"
            item["sk"] = sk
            self.table.put_item(Item=item)
            
            logger.info(
                "Trade entry recorded",
                outcome_id=outcome.outcome_id,
                coin=coin,
                price=price,
                quantity=quantity,
            )
        except ClientError as e:
            logger.error("Failed to save trade entry", error=str(e))
            raise
        
        return outcome

    async def record_exit(
        self,
        symbol: str,
        coin: str,
        price: float,
        quantity: float,
        reasoning: str = "",
    ) -> list[TradeOutcome]:
        """Record a trade exit using FIFO matching."""
        coin = coin.upper()
        remaining_to_exit = quantity
        closed_outcomes = []
        
        # Get open entries for this coin (FIFO order)
        open_entries = await self.get_open_entries(symbol)
        
        if not open_entries:
            logger.warning(
                "No open entries to match exit against",
                coin=coin,
                quantity=quantity,
            )
            return []
        
        for entry in open_entries:
            if remaining_to_exit <= 0:
                break
            
            # Determine how much of this entry to close
            exit_qty = min(entry.remaining_quantity, remaining_to_exit)
            
            # Record the exit
            entry.record_exit(
                exit_price=price,
                exit_quantity=exit_qty,
                reasoning=reasoning,
            )
            
            # Update in DynamoDB
            await self._update_outcome(entry)
            
            # Update position performance
            if entry.status == OutcomeStatus.CLOSED:
                await self._update_position_performance(entry)
                await self._update_portfolio_stats(entry)
            
            closed_outcomes.append(entry)
            remaining_to_exit -= exit_qty
            
            logger.info(
                "Trade exit matched",
                outcome_id=entry.outcome_id,
                coin=coin,
                entry_price=entry.entry_price,
                exit_price=price,
                exit_quantity=exit_qty,
                realized_pnl=entry.realized_pnl,
            )
        
        if remaining_to_exit > 0.001:  # Small threshold for floating point
            logger.warning(
                "Insufficient open entries for full exit",
                coin=coin,
                requested=quantity,
                matched=quantity - remaining_to_exit,
            )
        
        return closed_outcomes

    async def _update_outcome(self, outcome: TradeOutcome) -> None:
        """Update an outcome record, potentially moving it to a new SK."""
        coin = outcome.coin.upper()
        
        # Delete old record (need to find it first)
        try:
            # Query for this outcome_id
            response = self.table.query(
                KeyConditionExpression=Key("pk").eq(f"OUTCOME#{coin}"),
                FilterExpression=Attr("outcome_id").eq(outcome.outcome_id),
            )
            
            # Delete old records
            for item in response.get("Items", []):
                self.table.delete_item(
                    Key={"pk": item["pk"], "sk": item["sk"]}
                )
            
            # Create new record with updated status in SK
            timestamp = outcome.exit_timestamp or outcome.entry_timestamp
            sk = f"{outcome.status.value}#{timestamp.isoformat()}#{outcome.outcome_id}"
            
            item = convert_floats_to_decimal(outcome.to_dict())
            item["pk"] = f"OUTCOME#{coin}"
            item["sk"] = sk
            self.table.put_item(Item=item)
            
        except ClientError as e:
            logger.error("Failed to update outcome", error=str(e))
            raise

    async def _update_position_performance(self, outcome: TradeOutcome) -> None:
        """Update aggregated position performance after a trade closes."""
        coin = outcome.coin.upper()
        
        # Get existing performance or create new
        perf = await self.get_position_performance(coin)
        if perf is None:
            perf = PositionPerformance(
                symbol=outcome.symbol,
                coin=coin,
            )
        
        # Update with this outcome
        perf.update_from_outcome(outcome)
        
        # Save to DynamoDB
        try:
            item = convert_floats_to_decimal(perf.to_dict())
            item["pk"] = "POSITION_PERF"
            item["sk"] = coin
            self.table.put_item(Item=item)
        except ClientError as e:
            logger.error("Failed to update position performance", error=str(e))

    async def _update_portfolio_stats(self, outcome: TradeOutcome) -> None:
        """Update portfolio-wide statistics after a trade closes."""
        stats = await self.get_portfolio_stats()
        
        # Update counts
        stats.total_trades += 1
        if outcome.is_winner:
            stats.winning_trades += 1
            stats.current_streak = max(1, stats.current_streak + 1) if stats.current_streak >= 0 else 1
            stats.max_winning_streak = max(stats.max_winning_streak, stats.current_streak)
        else:
            stats.losing_trades += 1
            stats.current_streak = min(-1, stats.current_streak - 1) if stats.current_streak <= 0 else -1
            stats.max_losing_streak = max(stats.max_losing_streak, abs(stats.current_streak))
        
        # Update P&L
        if outcome.realized_pnl is not None:
            stats.total_realized_pnl += outcome.realized_pnl
            if outcome.realized_pnl > stats.largest_win:
                stats.largest_win = outcome.realized_pnl
            if outcome.realized_pnl < stats.largest_loss:
                stats.largest_loss = outcome.realized_pnl
        
        # Update timestamps
        if outcome.exit_timestamp:
            if stats.first_trade_at is None:
                stats.first_trade_at = outcome.exit_timestamp
            stats.last_trade_at = outcome.exit_timestamp
        
        # Save to DynamoDB
        try:
            item = convert_floats_to_decimal(stats.to_dict())
            item["pk"] = "PORTFOLIO_STATS"
            item["sk"] = "CURRENT"
            self.table.put_item(Item=item)
        except ClientError as e:
            logger.error("Failed to update portfolio stats", error=str(e))

    async def get_open_entries(self, symbol: Optional[str] = None) -> list[TradeOutcome]:
        """Get all open trade entries, optionally filtered by symbol."""
        outcomes = []
        
        try:
            if symbol:
                # Extract coin from symbol (e.g., BTCUSDT -> BTC)
                coin = symbol.replace("USDT", "").upper()
                
                # Query for open and partial statuses
                for status in [OutcomeStatus.OPEN.value, OutcomeStatus.PARTIAL.value]:
                    response = self.table.query(
                        KeyConditionExpression=(
                            Key("pk").eq(f"OUTCOME#{coin}") &
                            Key("sk").begins_with(f"{status}#")
                        ),
                    )
                    for item in response.get("Items", []):
                        outcomes.append(TradeOutcome.from_dict(convert_decimals_to_float(item)))
            else:
                # Scan for all open entries (less efficient but needed for portfolio view)
                response = self.table.scan(
                    FilterExpression=(
                        Attr("status").eq(OutcomeStatus.OPEN.value) |
                        Attr("status").eq(OutcomeStatus.PARTIAL.value)
                    ),
                )
                for item in response.get("Items", []):
                    if item.get("pk", "").startswith("OUTCOME#"):
                        outcomes.append(TradeOutcome.from_dict(convert_decimals_to_float(item)))
            
            # Sort by entry timestamp (FIFO)
            outcomes.sort(key=lambda x: x.entry_timestamp)
            
        except ClientError as e:
            logger.error("Failed to get open entries", error=str(e))
        
        return outcomes

    async def get_recent_outcomes(
        self,
        limit: int = 20,
        symbol: Optional[str] = None,
    ) -> list[TradeOutcome]:
        """Get recent closed trade outcomes."""
        outcomes = []
        
        try:
            if symbol:
                coin = symbol.replace("USDT", "").upper()
                response = self.table.query(
                    KeyConditionExpression=(
                        Key("pk").eq(f"OUTCOME#{coin}") &
                        Key("sk").begins_with(f"{OutcomeStatus.CLOSED.value}#")
                    ),
                    ScanIndexForward=False,  # Newest first
                    Limit=limit,
                )
                for item in response.get("Items", []):
                    outcomes.append(TradeOutcome.from_dict(convert_decimals_to_float(item)))
            else:
                # Scan for all closed outcomes
                response = self.table.scan(
                    FilterExpression=Attr("status").eq(OutcomeStatus.CLOSED.value),
                )
                for item in response.get("Items", []):
                    if item.get("pk", "").startswith("OUTCOME#"):
                        outcomes.append(TradeOutcome.from_dict(convert_decimals_to_float(item)))
                
                # Sort by exit timestamp descending and limit
                outcomes.sort(key=lambda x: x.exit_timestamp or datetime.min, reverse=True)
                outcomes = outcomes[:limit]
            
        except ClientError as e:
            logger.error("Failed to get recent outcomes", error=str(e))
        
        return outcomes

    async def get_position_performance(self, coin: str) -> Optional[PositionPerformance]:
        """Get aggregated performance for a specific coin."""
        try:
            response = self.table.get_item(
                Key={"pk": "POSITION_PERF", "sk": coin.upper()}
            )
            item = response.get("Item")
            if item:
                return PositionPerformance.from_dict(convert_decimals_to_float(item))
            return None
        except ClientError as e:
            logger.error("Failed to get position performance", error=str(e))
            return None

    async def get_all_position_performance(self) -> list[PositionPerformance]:
        """Get performance metrics for all traded coins."""
        performances = []
        
        try:
            response = self.table.query(
                KeyConditionExpression=Key("pk").eq("POSITION_PERF")
            )
            for item in response.get("Items", []):
                performances.append(
                    PositionPerformance.from_dict(convert_decimals_to_float(item))
                )
        except ClientError as e:
            logger.error("Failed to get all position performance", error=str(e))
        
        return performances

    async def get_portfolio_stats(self) -> PortfolioStats:
        """Get portfolio-wide statistics."""
        try:
            response = self.table.get_item(
                Key={"pk": "PORTFOLIO_STATS", "sk": "CURRENT"}
            )
            item = response.get("Item")
            if item:
                data = convert_decimals_to_float(item)
                
                # Parse timestamps
                first_trade = data.get("first_trade_at")
                if isinstance(first_trade, str):
                    first_trade = datetime.fromisoformat(first_trade.replace("Z", "+00:00"))
                
                last_trade = data.get("last_trade_at")
                if isinstance(last_trade, str):
                    last_trade = datetime.fromisoformat(last_trade.replace("Z", "+00:00"))
                
                return PortfolioStats(
                    total_trades=data.get("total_trades", 0),
                    winning_trades=data.get("winning_trades", 0),
                    losing_trades=data.get("losing_trades", 0),
                    total_realized_pnl=data.get("total_realized_pnl", 0.0),
                    largest_win=data.get("largest_win", 0.0),
                    largest_loss=data.get("largest_loss", 0.0),
                    current_streak=data.get("current_streak", 0),
                    max_winning_streak=data.get("max_winning_streak", 0),
                    max_losing_streak=data.get("max_losing_streak", 0),
                    unique_coins_traded=data.get("unique_coins_traded", 0),
                    first_trade_at=first_trade,
                    last_trade_at=last_trade,
                )
        except ClientError as e:
            logger.error("Failed to get portfolio stats", error=str(e))
        
        return PortfolioStats()

    async def recalculate_stats(self) -> None:
        """Recalculate all statistics from trade history."""
        logger.info("Recalculating trade outcome statistics...")
        
        # Reset position performances
        performances: dict[str, PositionPerformance] = {}
        stats = PortfolioStats()
        unique_coins: set[str] = set()
        
        # Get all closed outcomes
        try:
            response = self.table.scan(
                FilterExpression=Attr("status").eq(OutcomeStatus.CLOSED.value),
            )
            
            outcomes = []
            for item in response.get("Items", []):
                if item.get("pk", "").startswith("OUTCOME#"):
                    outcomes.append(TradeOutcome.from_dict(convert_decimals_to_float(item)))
            
            # Sort by exit timestamp
            outcomes.sort(key=lambda x: x.exit_timestamp or datetime.min)
            
            for outcome in outcomes:
                coin = outcome.coin.upper()
                unique_coins.add(coin)
                
                # Update position performance
                if coin not in performances:
                    performances[coin] = PositionPerformance(
                        symbol=outcome.symbol,
                        coin=coin,
                    )
                performances[coin].update_from_outcome(outcome)
                
                # Update portfolio stats
                stats.total_trades += 1
                if outcome.is_winner:
                    stats.winning_trades += 1
                    stats.current_streak = max(1, stats.current_streak + 1) if stats.current_streak >= 0 else 1
                    stats.max_winning_streak = max(stats.max_winning_streak, stats.current_streak)
                else:
                    stats.losing_trades += 1
                    stats.current_streak = min(-1, stats.current_streak - 1) if stats.current_streak <= 0 else -1
                    stats.max_losing_streak = max(stats.max_losing_streak, abs(stats.current_streak))
                
                if outcome.realized_pnl is not None:
                    stats.total_realized_pnl += outcome.realized_pnl
                    if outcome.realized_pnl > stats.largest_win:
                        stats.largest_win = outcome.realized_pnl
                    if outcome.realized_pnl < stats.largest_loss:
                        stats.largest_loss = outcome.realized_pnl
                
                if outcome.exit_timestamp:
                    if stats.first_trade_at is None:
                        stats.first_trade_at = outcome.exit_timestamp
                    stats.last_trade_at = outcome.exit_timestamp
            
            stats.unique_coins_traded = len(unique_coins)
            
            # Save all position performances
            for coin, perf in performances.items():
                item = convert_floats_to_decimal(perf.to_dict())
                item["pk"] = "POSITION_PERF"
                item["sk"] = coin
                self.table.put_item(Item=item)
            
            # Save portfolio stats
            item = convert_floats_to_decimal(stats.to_dict())
            item["pk"] = "PORTFOLIO_STATS"
            item["sk"] = "CURRENT"
            self.table.put_item(Item=item)
            
            logger.info(
                "Statistics recalculated",
                total_trades=stats.total_trades,
                total_pnl=stats.total_realized_pnl,
                win_rate=stats.win_rate,
            )
            
        except ClientError as e:
            logger.error("Failed to recalculate stats", error=str(e))
            raise
