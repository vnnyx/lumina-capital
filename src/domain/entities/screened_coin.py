"""
Screened Coin Entity - Represents a coin that passed screening criteria.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class ScreenedCoin:
    """
    A coin that passed the screening criteria with its score.

    Attributes:
        ticker: Coin ticker (e.g., "BTC")
        symbol: Trading pair symbol (e.g., "BTCUSDT")
        score: Total screening score (higher = better candidate)
        current_price: Current price in USDT
        change_24h: 24-hour price change percentage
        change_7d: 7-day price change percentage (from CoinGecko)
        volume_24h: 24-hour trading volume in USDT
        volume_spike_ratio: Current volume / 7-day average volume
        market_cap: Market cap in USD (from CoinGecko)
        coin_age_days: Days since coin genesis (from CoinGecko)
        screening_reasons: List of reasons why this coin scored well
        deduction_reasons: List of reasons for score deductions
    """

    ticker: str
    symbol: str
    score: float
    current_price: float
    change_24h: float
    change_7d: Optional[float] = None
    volume_24h: float = 0.0
    volume_spike_ratio: Optional[float] = None
    market_cap: Optional[float] = None
    coin_age_days: Optional[int] = None
    screening_reasons: list[str] = field(default_factory=list)
    deduction_reasons: list[str] = field(default_factory=list)
    screened_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """Convert to dictionary for storage/logging."""
        return {
            "ticker": self.ticker,
            "symbol": self.symbol,
            "score": self.score,
            "current_price": self.current_price,
            "change_24h": self.change_24h,
            "change_7d": self.change_7d,
            "volume_24h": self.volume_24h,
            "volume_spike_ratio": self.volume_spike_ratio,
            "market_cap": self.market_cap,
            "coin_age_days": self.coin_age_days,
            "screening_reasons": self.screening_reasons,
            "deduction_reasons": self.deduction_reasons,
            "screened_at": self.screened_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ScreenedCoin":
        """Create from dictionary."""
        screened_at = data.get("screened_at")
        if isinstance(screened_at, str):
            screened_at = datetime.fromisoformat(screened_at)
        elif screened_at is None:
            screened_at = datetime.now()

        return cls(
            ticker=data.get("ticker", ""),
            symbol=data.get("symbol", ""),
            score=float(data.get("score", 0)),
            current_price=float(data.get("current_price", 0)),
            change_24h=float(data.get("change_24h", 0)),
            change_7d=data.get("change_7d"),
            volume_24h=float(data.get("volume_24h", 0)),
            volume_spike_ratio=data.get("volume_spike_ratio"),
            market_cap=data.get("market_cap"),
            coin_age_days=data.get("coin_age_days"),
            screening_reasons=data.get("screening_reasons", []),
            deduction_reasons=data.get("deduction_reasons", []),
            screened_at=screened_at,
        )

    @property
    def summary(self) -> str:
        """Get a summary string for logging."""
        reasons = ", ".join(self.screening_reasons[:3]) if self.screening_reasons else "N/A"
        return f"{self.ticker}: score={self.score:.0f}, 24h={self.change_24h:+.1f}%, reasons=[{reasons}]"
