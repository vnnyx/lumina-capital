"""
JSON Trade Outcome Tracker - JSON file storage for trade outcomes and P&L tracking.

Provides the same functionality as DynamoDB adapter but stores data in local JSON files.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.domain.entities.trade_outcome import (
    TradeOutcome,
    OutcomeStatus,
    PositionPerformance,
    PortfolioStats,
)
from src.domain.ports.trade_outcome_port import TradeOutcomePort
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)


class JsonTradeOutcomeAdapter(TradeOutcomePort):
    """
    JSON file implementation of TradeOutcomePort.
    
    Stores trade outcomes, position performance, and portfolio stats in a JSON file.
    Uses FIFO matching for exit orders.
    """
    
    def __init__(self, storage_path: str = "data/trade_outcomes.json"):
        """
        Initialize JSON trade outcome adapter.
        
        Args:
            storage_path: Path to the JSON storage file
        """
        self.storage_path = Path(storage_path)
        self._outcomes: list[TradeOutcome] = []
        self._position_perfs: dict[str, PositionPerformance] = {}
        self._portfolio_stats: PortfolioStats = PortfolioStats()
        self._load()
    
    def _load(self) -> None:
        """Load data from disk."""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, "r") as f:
                    data = json.load(f)
                
                # Load outcomes
                self._outcomes = [
                    TradeOutcome.from_dict(o) for o in data.get("outcomes", [])
                ]
                
                # Load position performances
                self._position_perfs = {
                    coin: PositionPerformance.from_dict(perf)
                    for coin, perf in data.get("position_performances", {}).items()
                }
                
                # Load portfolio stats
                stats_data = data.get("portfolio_stats", {})
                if stats_data:
                    first_trade = stats_data.get("first_trade_at")
                    if isinstance(first_trade, str):
                        first_trade = datetime.fromisoformat(first_trade.replace("Z", "+00:00"))
                    
                    last_trade = stats_data.get("last_trade_at")
                    if isinstance(last_trade, str):
                        last_trade = datetime.fromisoformat(last_trade.replace("Z", "+00:00"))
                    
                    self._portfolio_stats = PortfolioStats(
                        total_trades=stats_data.get("total_trades", 0),
                        winning_trades=stats_data.get("winning_trades", 0),
                        losing_trades=stats_data.get("losing_trades", 0),
                        total_realized_pnl=stats_data.get("total_realized_pnl", 0.0),
                        largest_win=stats_data.get("largest_win", 0.0),
                        largest_loss=stats_data.get("largest_loss", 0.0),
                        current_streak=stats_data.get("current_streak", 0),
                        max_winning_streak=stats_data.get("max_winning_streak", 0),
                        max_losing_streak=stats_data.get("max_losing_streak", 0),
                        unique_coins_traded=stats_data.get("unique_coins_traded", 0),
                        first_trade_at=first_trade,
                        last_trade_at=last_trade,
                    )
                
                logger.debug(
                    "Trade outcomes loaded",
                    outcomes=len(self._outcomes),
                    positions=len(self._position_perfs),
                )
            except Exception as e:
                logger.warning("Failed to load trade outcomes", error=str(e))
                self._outcomes = []
                self._position_perfs = {}
                self._portfolio_stats = PortfolioStats()
        else:
            self._outcomes = []
            self._position_perfs = {}
            self._portfolio_stats = PortfolioStats()
    
    def _save(self) -> None:
        """Save data to disk."""
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            
            data = {
                "outcomes": [o.to_dict() for o in self._outcomes],
                "position_performances": {
                    coin: perf.to_dict()
                    for coin, perf in self._position_perfs.items()
                },
                "portfolio_stats": self._portfolio_stats.to_dict(),
                "last_updated": datetime.now().isoformat(),
            }
            
            with open(self.storage_path, "w") as f:
                json.dump(data, f, indent=2)
            
            logger.debug("Trade outcomes saved", path=str(self.storage_path))
        except Exception as e:
            logger.warning("Failed to save trade outcomes", error=str(e))

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
        
        self._outcomes.append(outcome)
        self._save()
        
        logger.info(
            "Trade entry recorded",
            outcome_id=outcome.outcome_id,
            coin=coin,
            price=price,
            quantity=quantity,
        )
        
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
            
            # Update position performance and portfolio stats if closed
            if entry.status == OutcomeStatus.CLOSED:
                self._update_position_performance(entry)
                self._update_portfolio_stats(entry)
            
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
        
        self._save()
        return closed_outcomes

    def _update_position_performance(self, outcome: TradeOutcome) -> None:
        """Update aggregated position performance after a trade closes."""
        coin = outcome.coin.upper()
        
        if coin not in self._position_perfs:
            self._position_perfs[coin] = PositionPerformance(
                symbol=outcome.symbol,
                coin=coin,
            )
        
        self._position_perfs[coin].update_from_outcome(outcome)

    def _update_portfolio_stats(self, outcome: TradeOutcome) -> None:
        """Update portfolio-wide statistics after a trade closes."""
        stats = self._portfolio_stats
        
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
        
        # Update unique coins count
        stats.unique_coins_traded = len(self._position_perfs)

    async def get_open_entries(self, symbol: Optional[str] = None) -> list[TradeOutcome]:
        """Get all open trade entries, optionally filtered by symbol."""
        open_statuses = {OutcomeStatus.OPEN, OutcomeStatus.PARTIAL}
        
        if symbol:
            coin = symbol.replace("USDT", "").upper()
            entries = [
                o for o in self._outcomes
                if o.status in open_statuses and o.coin.upper() == coin
            ]
        else:
            entries = [o for o in self._outcomes if o.status in open_statuses]
        
        # Sort by entry timestamp (FIFO)
        entries.sort(key=lambda x: x.entry_timestamp)
        return entries

    async def get_recent_outcomes(
        self,
        limit: int = 20,
        symbol: Optional[str] = None,
    ) -> list[TradeOutcome]:
        """Get recent closed trade outcomes."""
        closed = [o for o in self._outcomes if o.status == OutcomeStatus.CLOSED]
        
        if symbol:
            coin = symbol.replace("USDT", "").upper()
            closed = [o for o in closed if o.coin.upper() == coin]
        
        # Sort by exit timestamp descending
        closed.sort(key=lambda x: x.exit_timestamp or datetime.min, reverse=True)
        return closed[:limit]

    async def get_position_performance(self, coin: str) -> Optional[PositionPerformance]:
        """Get aggregated performance for a specific coin."""
        return self._position_perfs.get(coin.upper())

    async def get_all_position_performance(self) -> list[PositionPerformance]:
        """Get performance metrics for all traded coins."""
        return list(self._position_perfs.values())

    async def get_portfolio_stats(self) -> PortfolioStats:
        """Get portfolio-wide statistics."""
        return self._portfolio_stats

    async def recalculate_stats(self) -> None:
        """Recalculate all statistics from trade history."""
        logger.info("Recalculating trade outcome statistics...")
        
        # Reset
        self._position_perfs = {}
        self._portfolio_stats = PortfolioStats()
        unique_coins: set[str] = set()
        
        # Get all closed outcomes sorted by exit timestamp
        closed = [o for o in self._outcomes if o.status == OutcomeStatus.CLOSED]
        closed.sort(key=lambda x: x.exit_timestamp or datetime.min)
        
        for outcome in closed:
            coin = outcome.coin.upper()
            unique_coins.add(coin)
            
            # Update position performance
            self._update_position_performance(outcome)
            
            # Update portfolio stats (without double-counting)
            # Note: _update_portfolio_stats increments counts, so we call it directly
            stats = self._portfolio_stats
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
        
        self._portfolio_stats.unique_coins_traded = len(unique_coins)
        self._save()
        
        logger.info(
            "Statistics recalculated",
            total_trades=self._portfolio_stats.total_trades,
            total_pnl=self._portfolio_stats.total_realized_pnl,
            win_rate=self._portfolio_stats.win_rate,
        )
