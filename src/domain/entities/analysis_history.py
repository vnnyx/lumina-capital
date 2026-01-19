"""
Analysis History Entity - Stores historical analyses for prompt fine-tuning.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.domain.entities.coin_analysis import CoinAnalysis


@dataclass
class AnalysisOutcome:
    """Outcome data recorded after the prediction window."""
    
    actual_price_after_4h: float
    price_change_pct: float  # Percentage change from analysis price
    prediction_correct: Optional[bool]  # True if prediction matched outcome
    outcome_label: str  # "correct", "wrong", "neutral"
    recorded_at: datetime
    
    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "actual_price_after_4h": self.actual_price_after_4h,
            "price_change_pct": self.price_change_pct,
            "prediction_correct": self.prediction_correct,
            "outcome_label": self.outcome_label,
            "recorded_at": self.recorded_at.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "AnalysisOutcome":
        """Create from dictionary."""
        recorded_at = data["recorded_at"]
        if isinstance(recorded_at, str):
            recorded_at = datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))
        
        return cls(
            actual_price_after_4h=float(data["actual_price_after_4h"]),
            price_change_pct=float(data["price_change_pct"]),
            prediction_correct=data.get("prediction_correct"),
            outcome_label=data.get("outcome_label", "unknown"),
            recorded_at=recorded_at,
        )


@dataclass
class AnalysisHistoryEntry:
    """
    Historical analysis entry for tracking prediction accuracy.
    
    Used to correlate Gemini's predictions with actual price outcomes
    to enable prompt fine-tuning and model performance analysis.
    """
    
    # Identifiers
    ticker: str
    symbol: str
    timestamp: datetime  # When analysis was performed
    
    # Analysis data
    price_at_analysis: float
    change_24h_at_analysis: float
    predicted_trend: str  # bullish, bearish, sideways
    predicted_momentum: str  # strong, moderate, weak
    volatility_score: float
    volume_trend: str
    key_observations: list[str] = field(default_factory=list)
    
    # Outcome (populated later by backfill job)
    outcome: Optional[AnalysisOutcome] = None
    
    # TTL for auto-expiration (30 days from creation)
    ttl: Optional[int] = None  # Unix timestamp for DynamoDB TTL
    
    def __post_init__(self):
        """Set TTL if not provided."""
        if self.ttl is None:
            # 30 days from now
            ttl_datetime = datetime.now() + timedelta(days=30)
            self.ttl = int(ttl_datetime.timestamp())
    
    @property
    def history_key(self) -> str:
        """Unique key for this history entry: TICKER#TIMESTAMP."""
        ts_str = self.timestamp.strftime("%Y%m%d%H%M%S")
        return f"{self.ticker}#{ts_str}"
    
    @property
    def has_outcome(self) -> bool:
        """Check if outcome has been recorded."""
        return self.outcome is not None
    
    @property
    def is_ready_for_outcome(self) -> bool:
        """Check if 4 hours have passed since analysis."""
        return datetime.now() >= self.timestamp + timedelta(hours=4)
    
    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        data = {
            "ticker": self.ticker,
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "price_at_analysis": self.price_at_analysis,
            "change_24h_at_analysis": self.change_24h_at_analysis,
            "predicted_trend": self.predicted_trend,
            "predicted_momentum": self.predicted_momentum,
            "volatility_score": self.volatility_score,
            "volume_trend": self.volume_trend,
            "key_observations": self.key_observations,
            "ttl": self.ttl,
        }
        
        if self.outcome:
            data["outcome"] = self.outcome.to_dict()
        
        return data
    
    @classmethod
    def from_dict(cls, data: dict) -> "AnalysisHistoryEntry":
        """Create from dictionary."""
        timestamp = data["timestamp"]
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        
        outcome = None
        if data.get("outcome"):
            outcome = AnalysisOutcome.from_dict(data["outcome"])
        
        return cls(
            ticker=data["ticker"],
            symbol=data["symbol"],
            timestamp=timestamp,
            price_at_analysis=float(data["price_at_analysis"]),
            change_24h_at_analysis=float(data["change_24h_at_analysis"]),
            predicted_trend=data["predicted_trend"],
            predicted_momentum=data["predicted_momentum"],
            volatility_score=float(data["volatility_score"]),
            volume_trend=data["volume_trend"],
            key_observations=data.get("key_observations", []),
            outcome=outcome,
            ttl=data.get("ttl"),
        )
    
    @classmethod
    def from_coin_analysis(cls, analysis: "CoinAnalysis") -> "AnalysisHistoryEntry":
        """Create history entry from a CoinAnalysis."""
        insight = analysis.gemini_insight
        
        return cls(
            ticker=analysis.ticker,
            symbol=analysis.symbol,
            timestamp=analysis.analysis_timestamp or datetime.now(),
            price_at_analysis=float(analysis.current_price),
            change_24h_at_analysis=float(analysis.price_change_24h),
            predicted_trend=insight.trend if insight else "unknown",
            predicted_momentum=insight.momentum if insight else "unknown",
            volatility_score=insight.volatility_score if insight else 0.5,
            volume_trend=insight.volume_trend if insight else "unknown",
            key_observations=insight.key_observations[:3] if insight else [],
        )
