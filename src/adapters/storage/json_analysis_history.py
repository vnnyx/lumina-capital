"""JSON file storage adapter for analysis history."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import structlog

from src.domain.entities.analysis_history import AnalysisHistoryEntry, AnalysisOutcome
from src.domain.ports.analysis_history_port import AnalysisHistoryPort

logger = structlog.get_logger()


class JsonAnalysisHistoryAdapter(AnalysisHistoryPort):
    """Analysis history storage using local JSON file."""

    def __init__(self, file_path: str = "data/analysis_history.json"):
        self.file_path = Path(file_path)
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_file_exists()

    def _ensure_file_exists(self) -> None:
        """Create the JSON file if it doesn't exist."""
        if not self.file_path.exists():
            self._write_data({"history": []})
            logger.info("created_analysis_history_file", path=str(self.file_path))

    def _read_data(self) -> dict[str, Any]:
        """Read all data from JSON file."""
        try:
            with open(self.file_path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {"history": []}

    def _write_data(self, data: dict[str, Any]) -> None:
        """Write all data to JSON file."""
        with open(self.file_path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def _filter_expired(self, entries: list[dict]) -> list[dict]:
        """Filter out entries older than 30 days (TTL)."""
        now = datetime.now().timestamp()
        return [e for e in entries if e.get("ttl", float("inf")) > now]

    async def save_history(self, entry: AnalysisHistoryEntry) -> bool:
        """Save an analysis history entry."""
        try:
            data = self._read_data()
            history = data.get("history", [])
            
            # Filter expired entries while we're at it
            history = self._filter_expired(history)
            
            # Add new entry
            history.append(entry.to_dict())
            
            data["history"] = history
            self._write_data(data)
            
            logger.debug(
                "saved_analysis_history",
                ticker=entry.ticker,
                timestamp=entry.timestamp.isoformat(),
            )
            return True
        except Exception as e:
            logger.error("failed_to_save_history", error=str(e))
            return False

    async def get_pending_outcomes(self) -> list[AnalysisHistoryEntry]:
        """Get entries that are ready for outcome recording."""
        data = self._read_data()
        history = self._filter_expired(data.get("history", []))
        
        cutoff = datetime.now() - timedelta(hours=4)
        pending = []
        
        for entry_dict in history:
            # Skip if already has outcome
            if entry_dict.get("outcome"):
                continue
            
            # Parse timestamp
            timestamp = entry_dict["timestamp"]
            if isinstance(timestamp, str):
                timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            
            # Check if 4 hours have passed
            if timestamp <= cutoff:
                pending.append(AnalysisHistoryEntry.from_dict(entry_dict))
        
        return pending

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
            data = self._read_data()
            history = data.get("history", [])
            
            for entry_dict in history:
                entry = AnalysisHistoryEntry.from_dict(entry_dict)
                if entry.history_key == history_key:
                    entry_dict["outcome"] = {
                        "actual_price_after_4h": actual_price,
                        "price_change_pct": price_change_pct,
                        "prediction_correct": prediction_correct,
                        "outcome_label": outcome_label,
                        "recorded_at": datetime.now().isoformat(),
                    }
                    self._write_data(data)
                    logger.info(
                        "updated_outcome",
                        history_key=history_key,
                        outcome_label=outcome_label,
                    )
                    return True
            
            logger.warning("history_entry_not_found", history_key=history_key)
            return False
        except Exception as e:
            logger.error("failed_to_update_outcome", error=str(e))
            return False

    async def get_history_for_ticker(
        self,
        ticker: str,
        limit: int = 100,
    ) -> list[AnalysisHistoryEntry]:
        """Get historical entries for a specific ticker."""
        data = self._read_data()
        history = self._filter_expired(data.get("history", []))
        
        # Filter by ticker
        filtered = [e for e in history if e["ticker"] == ticker]
        
        # Sort by timestamp descending (newest first)
        filtered.sort(key=lambda e: e["timestamp"], reverse=True)
        
        # Apply limit and convert
        return [AnalysisHistoryEntry.from_dict(e) for e in filtered[:limit]]

    async def get_all_history(
        self,
        with_outcome_only: bool = False,
        limit: int = 500,
    ) -> list[AnalysisHistoryEntry]:
        """Get all historical entries."""
        data = self._read_data()
        history = self._filter_expired(data.get("history", []))
        
        if with_outcome_only:
            history = [e for e in history if e.get("outcome")]
        
        # Sort by timestamp descending
        history.sort(key=lambda e: e["timestamp"], reverse=True)
        
        return [AnalysisHistoryEntry.from_dict(e) for e in history[:limit]]

    async def get_accuracy_stats(self, ticker: Optional[str] = None) -> dict:
        """Calculate prediction accuracy statistics."""
        data = self._read_data()
        history = self._filter_expired(data.get("history", []))
        
        # Filter by ticker if specified
        if ticker:
            history = [e for e in history if e["ticker"] == ticker]
        
        # Only count entries with outcomes
        with_outcomes = [e for e in history if e.get("outcome")]
        
        total = len(with_outcomes)
        correct = sum(1 for e in with_outcomes if e["outcome"]["outcome_label"] == "correct")
        wrong = sum(1 for e in with_outcomes if e["outcome"]["outcome_label"] == "wrong")
        neutral = sum(1 for e in with_outcomes if e["outcome"]["outcome_label"] == "neutral")
        
        accuracy_pct = (correct / total * 100) if total > 0 else 0.0
        
        return {
            "total": total,
            "correct": correct,
            "wrong": wrong,
            "neutral": neutral,
            "accuracy_pct": round(accuracy_pct, 2),
            "ticker": ticker,
        }
