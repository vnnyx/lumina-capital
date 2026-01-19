"""
Outcome Backfill Service - Auto-records price outcomes for analysis history.

Run this service every hour to:
1. Find analyses from 4+ hours ago without outcomes
2. Fetch current prices from Bitget
3. Calculate if predictions were correct
4. Update history with outcomes
"""

from datetime import datetime
from typing import Any, Optional

from src.domain.entities.analysis_history import AnalysisHistoryEntry
from src.domain.ports.analysis_history_port import AnalysisHistoryPort
from src.domain.ports.market_data_port import MarketDataPort
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)


# Thresholds for outcome classification
CORRECT_THRESHOLD = 0.5  # >0.5% in predicted direction = correct
WRONG_THRESHOLD = -0.5   # <-0.5% (opposite direction) = wrong
# Between -0.5% and 0.5% = neutral


class OutcomeBackfillService:
    """
    Service to backfill price outcomes for analysis history entries.
    
    Determines if Gemini's predictions were correct by comparing
    the predicted trend against actual price movement after 4 hours.
    """
    
    def __init__(
        self,
        history_port: AnalysisHistoryPort,
        market_data_port: MarketDataPort,
    ):
        self.history = history_port
        self.market_data = market_data_port
    
    def _evaluate_prediction(
        self,
        predicted_trend: str,
        price_change_pct: float,
    ) -> tuple[str, Optional[bool]]:
        """
        Evaluate if prediction was correct.
        
        Args:
            predicted_trend: "bullish", "bearish", or "sideways"
            price_change_pct: Actual price change percentage
            
        Returns:
            Tuple of (outcome_label, prediction_correct)
            - outcome_label: "correct", "wrong", or "neutral"
            - prediction_correct: True, False, or None (for neutral)
        """
        # Determine expected direction
        if predicted_trend == "bullish":
            # Bullish = expecting price increase
            if price_change_pct > CORRECT_THRESHOLD:
                return "correct", True
            elif price_change_pct < WRONG_THRESHOLD:
                return "wrong", False
            else:
                return "neutral", None
                
        elif predicted_trend == "bearish":
            # Bearish = expecting price decrease
            if price_change_pct < -CORRECT_THRESHOLD:
                return "correct", True
            elif price_change_pct > -WRONG_THRESHOLD:
                return "wrong", False
            else:
                return "neutral", None
                
        else:  # sideways
            # Sideways = expecting minimal movement
            if abs(price_change_pct) <= CORRECT_THRESHOLD:
                return "correct", True
            else:
                return "wrong", False
    
    async def backfill_pending(self) -> dict:
        """
        Process all pending entries and record their outcomes.
        
        Returns:
            Dict with processing stats: processed, success, failed, skipped
        """
        stats = {"processed": 0, "success": 0, "failed": 0, "skipped": 0}
        
        # Get entries ready for outcome recording
        pending = await self.history.get_pending_outcomes()
        logger.info("found_pending_outcomes", count=len(pending))
        
        if not pending:
            return stats
        
        # Fetch current prices for all symbols
        try:
            all_tickers = await self.market_data.get_all_tickers()
            prices = {t.symbol: float(t.last_price) for t in all_tickers}
        except Exception as e:
            logger.error("failed_to_fetch_prices", error=str(e))
            return stats
        
        # Process each pending entry
        for entry in pending:
            stats["processed"] += 1
            
            # Get current price
            current_price = prices.get(entry.symbol)
            if current_price is None:
                logger.warning("price_not_found", symbol=entry.symbol)
                stats["skipped"] += 1
                continue
            
            # Calculate price change
            if entry.price_at_analysis <= 0:
                logger.warning("invalid_analysis_price", symbol=entry.symbol)
                stats["skipped"] += 1
                continue
                
            price_change_pct = (
                (current_price - entry.price_at_analysis) 
                / entry.price_at_analysis 
                * 100
            )
            
            # Evaluate prediction
            outcome_label, prediction_correct = self._evaluate_prediction(
                entry.predicted_trend,
                price_change_pct,
            )
            
            # Update history
            success = await self.history.update_outcome(
                history_key=entry.history_key,
                actual_price=current_price,
                price_change_pct=price_change_pct,
                outcome_label=outcome_label,
                prediction_correct=prediction_correct,
            )
            
            if success:
                stats["success"] += 1
                logger.info(
                    "recorded_outcome",
                    ticker=entry.ticker,
                    predicted=entry.predicted_trend,
                    actual_change=f"{price_change_pct:.2f}%",
                    outcome=outcome_label,
                )
            else:
                stats["failed"] += 1
        
        logger.info("backfill_complete", **stats)
        return stats
    
    async def get_performance_report(self, ticker: Optional[str] = None) -> dict:
        """
        Generate a performance report for predictions.
        
        Args:
            ticker: Optional ticker to filter by
            
        Returns:
            Dict with accuracy stats and trend breakdown
        """
        stats = await self.history.get_accuracy_stats(ticker)
        
        # Get detailed breakdown by trend
        if ticker:
            entries = await self.history.get_history_for_ticker(ticker)
        else:
            entries = await self.history.get_all_history(with_outcome_only=True)
        
        trend_stats: dict[str, dict[str, Any]] = {
            "bullish": {"total": 0, "correct": 0}, 
            "bearish": {"total": 0, "correct": 0},
            "sideways": {"total": 0, "correct": 0},
        }
        
        for entry in entries:
            if not entry.has_outcome:
                continue
            trend = entry.predicted_trend
            if trend in trend_stats:
                trend_stats[trend]["total"] += 1
                if entry.outcome and entry.outcome.outcome_label == "correct":
                    trend_stats[trend]["correct"] += 1
        
        # Calculate per-trend accuracy
        for trend, data in trend_stats.items():
            if data["total"] > 0:
                data["accuracy_pct"] = round(data["correct"] / data["total"] * 100, 2)
            else:
                data["accuracy_pct"] = 0.0
        
        return {
            "overall": stats,
            "by_trend": trend_stats,
        }
