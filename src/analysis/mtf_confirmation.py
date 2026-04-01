"""Multi-timeframe trend confirmation.

Checks whether higher timeframes (H4, Daily) agree with the H1 signal direction.
Aligned signals are higher probability; conflicting signals get penalized.
"""

import logging
from dataclasses import dataclass

import pandas as pd

from src.analysis.trend_strength import calculate_trend_strength, TrendStrengthResult
from src.broker.oanda_connector import OandaConnector

logger = logging.getLogger("pa_bot")


@dataclass
class MTFResult:
    """Multi-timeframe confirmation result."""

    h1_direction: str          # "bullish" or "bearish"
    h4_direction: str          # "bullish", "bearish", or "unknown"
    d1_direction: str          # "bullish", "bearish", or "unknown"
    h4_strength: float         # 0-100
    d1_strength: float         # 0-100
    alignment_score: float     # -1.0 (fully conflicting) to 1.0 (fully aligned)
    aligned_count: int         # 0, 1, or 2 (how many higher TFs agree)

    @property
    def quality_multiplier(self) -> float:
        """Return a multiplier for quality score.

        Full alignment: 1.15 (15% boost)
        Partial alignment: 1.05 (5% boost)
        Neutral: 1.0
        Partial conflict: 0.90 (10% penalty)
        Full conflict: 0.80 (20% penalty)
        """
        if self.alignment_score >= 0.8:
            return 1.15
        elif self.alignment_score >= 0.3:
            return 1.05
        elif self.alignment_score >= -0.3:
            return 1.0
        elif self.alignment_score >= -0.8:
            return 0.90
        else:
            return 0.80


class MTFAnalyzer:
    """Fetch higher-timeframe data and confirm H1 signal direction."""

    def __init__(self, connector: OandaConnector):
        self.connector = connector
        # Cache per cycle to avoid redundant API calls
        self._h4_cache: dict[str, TrendStrengthResult] = {}
        self._d1_cache: dict[str, TrendStrengthResult] = {}
        self._cache_cycle: int = -1

    def confirm(
        self, pair: str, direction: str, cycle: int = 0,
    ) -> MTFResult:
        """Check if higher timeframes confirm the signal direction.

        Args:
            pair: currency pair
            direction: "buy" or "sell" (from the H1 signal)
            cycle: current cycle number for caching
        """
        h1_dir = "bullish" if direction == "buy" else "bearish"

        # Reset cache on new cycle
        if cycle != self._cache_cycle:
            self._h4_cache.clear()
            self._d1_cache.clear()
            self._cache_cycle = cycle

        h4_trend = self._get_trend(pair, "H4", self._h4_cache)
        d1_trend = self._get_trend(pair, "D", self._d1_cache)

        h4_dir = h4_trend.direction if h4_trend else "unknown"
        d1_dir = d1_trend.direction if d1_trend else "unknown"
        h4_str = h4_trend.score if h4_trend else 0
        d1_str = d1_trend.score if d1_trend else 0

        # Calculate alignment score
        alignment = 0.0
        aligned_count = 0

        if h4_dir != "unknown":
            if h4_dir == h1_dir:
                alignment += 0.4 + (h4_str / 100) * 0.1  # 0.4-0.5
                aligned_count += 1
            else:
                alignment -= 0.4 + (h4_str / 100) * 0.1

        if d1_dir != "unknown":
            if d1_dir == h1_dir:
                alignment += 0.4 + (d1_str / 100) * 0.1  # 0.4-0.5
                aligned_count += 1
            else:
                alignment -= 0.4 + (d1_str / 100) * 0.1

        return MTFResult(
            h1_direction=h1_dir,
            h4_direction=h4_dir,
            d1_direction=d1_dir,
            h4_strength=h4_str,
            d1_strength=d1_str,
            alignment_score=max(-1.0, min(1.0, alignment)),
            aligned_count=aligned_count,
        )

    def _get_trend(
        self, pair: str, timeframe: str, cache: dict[str, TrendStrengthResult],
    ) -> TrendStrengthResult | None:
        """Fetch candles and calculate trend, using cache."""
        if pair in cache:
            return cache[pair]

        try:
            # Fewer bars needed for higher timeframes
            count = 50 if timeframe == "D" else 100
            df = self.connector.get_candles(pair, timeframe, count=count)
            if len(df) < 20:
                return None
            trend = calculate_trend_strength(df)
            cache[pair] = trend
            return trend
        except Exception as e:
            logger.debug("MTF: failed to fetch %s %s: %s", pair, timeframe, e)
            return None
