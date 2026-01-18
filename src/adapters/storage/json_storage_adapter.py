"""JSON file storage adapter for local development."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import structlog

from src.domain.entities.coin_analysis import CoinAnalysis, GeminiInsight
from src.domain.ports.storage_port import StoragePort

logger = structlog.get_logger()


class JSONStorageAdapter(StoragePort):
    """Storage adapter using local JSON file."""

    def __init__(self, file_path: str = "data/coin_analyses.json"):
        self.file_path = Path(file_path)
        self.decisions_path = self.file_path.parent / "trade_decisions.json"
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_file_exists()

    def _ensure_file_exists(self) -> None:
        """Create the JSON files if they don't exist."""
        if not self.file_path.exists():
            self._write_data(self.file_path, {"analyses": {}})
            logger.info("created_json_storage_file", path=str(self.file_path))
        if not self.decisions_path.exists():
            self._write_data(self.decisions_path, {"decisions": []})
            logger.info("created_decisions_file", path=str(self.decisions_path))

    def _read_data(self, path: Path) -> dict[str, Any]:
        """Read all data from JSON file."""
        try:
            with open(path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {}

    def _write_data(self, path: Path, data: dict[str, Any]) -> None:
        """Write all data to JSON file."""
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def _analysis_to_dict(self, analysis: CoinAnalysis) -> dict[str, Any]:
        """Convert CoinAnalysis to dictionary."""
        return {
            "partition_key": analysis.partition_key,
            "ticker": analysis.ticker,
            "coin_name": analysis.coin_name,
            "symbol": analysis.symbol,
            "current_price": analysis.current_price,
            "price_change_24h": analysis.price_change_24h,
            "volume_24h": analysis.volume_24h,
            "volume_rank": analysis.volume_rank,
            "price_history": analysis.price_history,
            "gemini_insight": analysis.gemini_insight.to_dict() if analysis.gemini_insight else None,
            "analysis_timestamp": analysis.analysis_timestamp.isoformat(),
            "data_source": analysis.data_source,
            "version": analysis.version,
        }

    def _dict_to_analysis(self, data: dict[str, Any]) -> CoinAnalysis:
        """Convert dictionary to CoinAnalysis."""
        gemini_insight = None
        if data.get("gemini_insight"):
            gemini_insight = GeminiInsight.from_dict(data["gemini_insight"])
        
        return CoinAnalysis(
            partition_key=data["partition_key"],
            ticker=data["ticker"],
            coin_name=data["coin_name"],
            symbol=data.get("symbol", f"{data['ticker']}USDT"),
            current_price=data["current_price"],
            price_change_24h=data["price_change_24h"],
            volume_24h=data["volume_24h"],
            volume_rank=data["volume_rank"],
            price_history=data.get("price_history", []),
            gemini_insight=gemini_insight,
            analysis_timestamp=datetime.fromisoformat(data["analysis_timestamp"]),
            data_source=data.get("data_source", "bitget"),
            version=data.get("version", "1.0"),
        )

    async def save_coin_analysis(self, analysis: CoinAnalysis) -> bool:
        """Save a coin analysis to JSON file."""
        try:
            partition_key = f"{analysis.ticker}-{analysis.coin_name}"
            data = self._read_data(self.file_path)
            if "analyses" not in data:
                data["analyses"] = {}
            data["analyses"][partition_key] = self._analysis_to_dict(analysis)
            self._write_data(self.file_path, data)

            logger.debug(
                "saved_analysis_to_json",
                ticker=analysis.ticker,
                coin_name=analysis.coin_name,
            )
            return True
        except Exception as e:
            logger.error("failed_to_save_analysis", error=str(e))
            return False

    async def get_coin_analysis(self, partition_key: str) -> Optional[CoinAnalysis]:
        """Retrieve a coin analysis by partition key."""
        data = self._read_data(self.file_path)
        analyses = data.get("analyses", {})

        if partition_key not in analyses:
            return None

        return self._dict_to_analysis(analyses[partition_key])

    async def get_all_analyses(self) -> list[CoinAnalysis]:
        """Retrieve all coin analyses from JSON file."""
        data = self._read_data(self.file_path)
        analyses = data.get("analyses", {})
        return [self._dict_to_analysis(item) for item in analyses.values()]

    async def get_analyses_by_volume_rank(
        self, 
        min_rank: int = 1, 
        max_rank: int = 200
    ) -> list[CoinAnalysis]:
        """Retrieve analyses within a volume rank range."""
        all_analyses = await self.get_all_analyses()
        
        # Filter by volume rank
        filtered = [
            a for a in all_analyses 
            if hasattr(a, "volume_rank") and min_rank <= a.volume_rank <= max_rank
        ]
        
        # Sort by volume rank
        filtered.sort(key=lambda a: getattr(a, "volume_rank", 999))
        return filtered

    async def delete_coin_analysis(self, partition_key: str) -> bool:
        """Delete a coin analysis from JSON file."""
        try:
            data = self._read_data(self.file_path)
            analyses = data.get("analyses", {})

            if partition_key in analyses:
                del analyses[partition_key]
                data["analyses"] = analyses
                self._write_data(self.file_path, data)
                logger.debug("deleted_analysis_from_json", partition_key=partition_key)
                return True
            return False
        except Exception as e:
            logger.error("failed_to_delete_analysis", error=str(e))
            return False

    async def batch_save_analyses(self, analyses: list[CoinAnalysis]) -> int:
        """Batch save multiple analyses to JSON file."""
        data = self._read_data(self.file_path)
        if "analyses" not in data:
            data["analyses"] = {}

        saved_count = 0
        for analysis in analyses:
            try:
                partition_key = f"{analysis.ticker}-{analysis.coin_name}"
                data["analyses"][partition_key] = self._analysis_to_dict(analysis)
                saved_count += 1
            except Exception as e:
                logger.error("failed_to_save_in_batch", ticker=analysis.ticker, error=str(e))

        self._write_data(self.file_path, data)
        logger.info("batch_saved_analyses_to_json", count=saved_count)
        return saved_count

    async def save_trade_decision(self, decision: dict) -> bool:
        """Save a trade decision for audit trail."""
        try:
            data = self._read_data(self.decisions_path)
            if "decisions" not in data:
                data["decisions"] = []
            
            # Add timestamp if not present
            if "timestamp" not in decision:
                decision["timestamp"] = datetime.now().isoformat()
            
            data["decisions"].append(decision)
            self._write_data(self.decisions_path, data)
            
            logger.debug("saved_trade_decision", decision=decision)
            return True
        except Exception as e:
            logger.error("failed_to_save_decision", error=str(e))
            return False

    async def get_recent_decisions(self, limit: int = 50) -> list[dict]:
        """Get recent trade decisions."""
        data = self._read_data(self.decisions_path)
        decisions = data.get("decisions", [])
        
        # Sort by timestamp descending and limit
        sorted_decisions = sorted(
            decisions,
            key=lambda d: d.get("timestamp", ""),
            reverse=True
        )
        return sorted_decisions[:limit]

        self._write_data(data)
        logger.info("batch_saved_analyses_to_json", count=len(analyses))
