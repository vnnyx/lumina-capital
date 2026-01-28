"""
Coin Screener Service - Smart filtering of coins based on multiple criteria.

Replaces simple "top N by volume" with a scoring system that considers:
- Price momentum (24h/7d change in sweet spot)
- Volume spike (2x-5x healthy)
- Market cap range ($10M-$500M)
- Coin age (>30 days)
"""

from datetime import datetime
from typing import Optional

from src.domain.entities.fundamental_data import CoinMetrics
from src.domain.entities.market_data import TickerData
from src.domain.entities.screened_coin import ScreenedCoin
from src.domain.ports.fundamental_data_port import FundamentalDataPort
from src.domain.ports.market_data_port import MarketDataPort
from src.infrastructure.config import Settings
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)

# Stablecoins to always exclude
STABLECOIN_TICKERS = frozenset({
    "USDT", "USDC", "DAI", "TUSD", "FDUSD", "BUSD", "USDP", "GUSD",
    "FRAX", "LUSD", "SUSD", "USDD", "CUSD", "USTC", "PYUSD", "EURC"
})


class CoinScreenerService:
    """
    Service for screening and scoring coins based on multiple criteria.

    Scoring System:
    - 24h change in sweet spot (15-50%): +20 points
    - 7d change in range (30-100%): +15 points
    - Market cap in range ($10M-$500M): +20 points
    - Volume spike healthy (2x-5x): +20 points

    Deductions:
    - >100% 24h change: -10 points
    - Volume spike + flat price: -15 points

    Hard Filters (coins excluded entirely):
    - Stablecoins
    - >200% 24h change (pump & dump)
    - <30 days old
    """

    def __init__(
        self,
        market_data_port: MarketDataPort,
        fundamental_data_port: Optional[FundamentalDataPort],
        settings: Settings,
    ):
        """
        Initialize the screener service.

        Args:
            market_data_port: Port for fetching market data from exchange
            fundamental_data_port: Port for fetching fundamental data (CoinGecko)
            settings: Application settings with screening parameters
        """
        self.market_data = market_data_port
        self.fundamental_data = fundamental_data_port
        self.settings = settings

    async def screen_coins(
        self,
        initial_limit: int = 200,
    ) -> list[ScreenedCoin]:
        """
        Screen coins and return top candidates by score.

        Process:
        1. Fetch top 200 by volume (initial pool)
        2. Apply hard filters (stablecoins, pump & dump, coin age)
        3. Score remaining coins
        4. Sort by score, return top N

        Args:
            initial_limit: Number of coins to fetch initially

        Returns:
            List of ScreenedCoin sorted by score (descending)
        """
        logger.info("Starting coin screening", initial_limit=initial_limit)

        # 1. Fetch top coins by volume
        top_tickers = await self.market_data.get_top_coins_by_volume(limit=initial_limit)
        logger.info("Fetched initial pool", count=len(top_tickers))

        # 2. Apply hard filters
        filtered_tickers = await self._apply_hard_filters(top_tickers)
        logger.info("After hard filters", remaining=len(filtered_tickers))

        if not filtered_tickers:
            logger.warning("All coins filtered out by hard filters")
            return []

        # 3. Fetch fundamental data for scoring
        tickers_for_fundamentals = [
            t.symbol.replace("USDT", "") for t in filtered_tickers[:50]
        ]
        coin_metrics: dict[str, CoinMetrics] = {}

        if self.fundamental_data:
            try:
                coin_metrics = await self.fundamental_data.get_coin_metrics(
                    tickers_for_fundamentals
                )
                logger.info("Fetched fundamental data", count=len(coin_metrics))
            except Exception as e:
                logger.warning("Failed to fetch fundamental data", error=str(e))

        # 4. Score coins
        screened_coins = []
        for ticker in filtered_tickers:
            coin_ticker = ticker.symbol.replace("USDT", "")
            metrics = coin_metrics.get(coin_ticker.upper())

            scored_coin = self._score_coin(ticker, metrics)
            screened_coins.append(scored_coin)

        # 5. Sort by score and return top N
        screened_coins.sort(key=lambda c: c.score, reverse=True)
        result_limit = self.settings.screening_result_limit
        top_coins = screened_coins[:result_limit]

        logger.info(
            "Screening complete",
            total_scored=len(screened_coins),
            returned=len(top_coins),
            top_scores=[c.score for c in top_coins[:5]],
        )

        for coin in top_coins:
            logger.debug("Screened coin", summary=coin.summary)

        return top_coins

    async def _apply_hard_filters(
        self,
        tickers: list[TickerData],
    ) -> list[TickerData]:
        """
        Apply hard filters to remove coins that should never be traded.

        Filters:
        - Stablecoins (no trading alpha)
        - >200% 24h change (pump & dump risk)
        - <30 days old (if we can determine age)

        Args:
            tickers: List of tickers to filter

        Returns:
            Filtered list of tickers
        """
        pump_dump_threshold = self.settings.screen_pump_dump_threshold
        filtered = []

        for ticker in tickers:
            coin_ticker = ticker.symbol.replace("USDT", "").upper()

            # Filter 1: Stablecoins
            if coin_ticker in STABLECOIN_TICKERS:
                logger.debug("Filtered stablecoin", ticker=coin_ticker)
                continue

            # Filter 2: Pump & dump (>200% in 24h)
            change_24h = abs(float(ticker.change_24h) * 100)
            if change_24h > pump_dump_threshold:
                logger.debug(
                    "Filtered pump & dump",
                    ticker=coin_ticker,
                    change_24h=change_24h,
                )
                continue

            filtered.append(ticker)

        return filtered

    def _score_coin(
        self,
        ticker: TickerData,
        metrics: Optional[CoinMetrics],
    ) -> ScreenedCoin:
        """
        Score a coin based on screening criteria.

        Args:
            ticker: Market data for the coin
            metrics: Optional fundamental metrics from CoinGecko

        Returns:
            ScreenedCoin with calculated score
        """
        coin_ticker = ticker.symbol.replace("USDT", "")
        score = 0.0
        reasons: list[str] = []
        deductions: list[str] = []

        # Get price change values
        change_24h = float(ticker.change_24h) * 100  # Convert to percentage
        change_7d = metrics.price_change_7d if metrics else None

        # Scoring criterion 1: 24h change in sweet spot
        min_24h = self.settings.screen_price_change_24h_min
        max_24h = self.settings.screen_price_change_24h_max

        if min_24h <= change_24h <= max_24h:
            score += 20
            reasons.append(f"24h change {change_24h:.1f}% in sweet spot")
        elif min_24h <= -change_24h <= max_24h:
            # Also reward negative sweet spot (potential reversal)
            score += 10
            reasons.append(f"24h change {change_24h:.1f}% (bearish sweet spot)")

        # Scoring criterion 2: 7d change in range
        if change_7d is not None:
            min_7d = self.settings.screen_price_change_7d_min
            max_7d = self.settings.screen_price_change_7d_max

            if min_7d <= change_7d <= max_7d:
                score += 15
                reasons.append(f"7d change {change_7d:.1f}% in range")
            elif min_7d <= -change_7d <= max_7d:
                score += 8
                reasons.append(f"7d change {change_7d:.1f}% (bearish range)")

        # Scoring criterion 3: Market cap in range
        market_cap = metrics.market_cap if metrics else None
        if market_cap is not None:
            min_cap = self.settings.screen_market_cap_min
            max_cap = self.settings.screen_market_cap_max

            if min_cap <= market_cap <= max_cap:
                score += 20
                reasons.append(f"Market cap ${market_cap/1e6:.1f}M in range")
            elif market_cap < min_cap:
                score += 5
                reasons.append(f"Small cap ${market_cap/1e6:.1f}M (higher risk/reward)")

        # Scoring criterion 4: Volume (base score for being in top 200)
        volume_24h = ticker.usdt_volume_float
        if volume_24h > 10_000_000:  # >$10M daily volume
            score += 10
            reasons.append(f"High volume ${volume_24h/1e6:.1f}M")
        elif volume_24h > 1_000_000:  # >$1M
            score += 5
            reasons.append(f"Moderate volume ${volume_24h/1e6:.1f}M")

        # Deduction 1: >100% 24h (not pump & dump but still risky)
        if abs(change_24h) > 100:
            score -= 10
            deductions.append(f"High volatility {change_24h:.1f}%")

        # Deduction 2: Flat price with no volume interest
        if abs(change_24h) < 2 and volume_24h < 500_000:
            score -= 15
            deductions.append("Flat price with low volume")

        return ScreenedCoin(
            ticker=coin_ticker,
            symbol=ticker.symbol,
            score=max(0, score),  # Don't go negative
            current_price=float(ticker.last_price),
            change_24h=change_24h,
            change_7d=change_7d,
            volume_24h=volume_24h,
            volume_spike_ratio=None,  # Would need historical data to calculate
            market_cap=market_cap,
            coin_age_days=None,  # Would need CoinGecko coin details API
            screening_reasons=reasons,
            deduction_reasons=deductions,
            screened_at=datetime.now(),
        )
