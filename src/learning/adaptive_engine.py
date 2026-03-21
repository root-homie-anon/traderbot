"""Adjust quality scores based on live performance.

The adaptive engine sits between the performance tracker and the quality
scorer.  It reads historical stats and produces adjusted weight multipliers
that the quality scorer can apply, so setups that are working get boosted
and setups that are failing get penalised.
"""

import logging
from dataclasses import dataclass, field

from src.learning.performance_tracker import PerformanceTracker

logger = logging.getLogger("pa_bot")

# Thresholds for adjustment
MIN_TRADES_FOR_ADJUSTMENT = 30
STRONG_WIN_RATE = 0.60
WEAK_WIN_RATE = 0.40
BOOST_FACTOR = 1.25
PENALTY_FACTOR = 0.70
NEUTRAL_FACTOR = 1.0


@dataclass
class ScoreAdjustment:
    """Multiplier and metadata for a particular setup."""

    signal_type: str
    pair: str
    timeframe: str
    multiplier: float = 1.0
    reason: str = ""
    win_rate: float = 0.0
    sample_size: int = 0


# Internal type for cache entries: (cycle_created, adjustment)
_CacheEntry = tuple[int, ScoreAdjustment]


class AdaptiveEngine:
    """Produce quality-score multipliers from tracked performance.

    Usage:
        engine = AdaptiveEngine(tracker)
        adj = engine.get_adjustment(signal_type="reversal", pair="EUR_USD", timeframe="H1")
        adjusted_score = base_score * adj.multiplier

    Call ``advance_cycle()`` once per trading cycle to evict stale cache
    entries.  Entries older than ``cache_ttl`` cycles are invalidated so
    that new trade data is picked up promptly without forcing a full cache
    flush every 10 cycles.
    """

    def __init__(
        self,
        tracker: PerformanceTracker,
        min_trades: int = MIN_TRADES_FOR_ADJUSTMENT,
        boost: float = BOOST_FACTOR,
        penalty: float = PENALTY_FACTOR,
        cache_ttl: int = 1,
    ):
        self.tracker = tracker
        self.min_trades = min_trades
        self.boost = boost
        self.penalty = penalty
        self.cache_ttl = cache_ttl
        self.cycle_number: int = 0
        self._cache: dict[tuple, _CacheEntry] = {}

    def advance_cycle(self) -> None:
        """Increment the cycle counter and evict cache entries older than cache_ttl cycles.

        Call this once per trading cycle so that adjustments reflect trade
        data recorded during the previous cycle(s) without requiring a full
        cache flush.
        """
        self.cycle_number += 1
        stale_threshold = self.cycle_number - self.cache_ttl
        stale_keys = [
            key
            for key, (cycle_created, _) in self._cache.items()
            if cycle_created <= stale_threshold
        ]
        for key in stale_keys:
            del self._cache[key]
        if stale_keys:
            logger.debug(
                "AdaptiveEngine cycle %d: evicted %d stale cache entries",
                self.cycle_number,
                len(stale_keys),
            )

    def get_adjustment(
        self,
        signal_type: str,
        pair: str = "*",
        timeframe: str = "*",
        source: str | None = None,
        last_n: int | None = None,
    ) -> ScoreAdjustment:
        """Get the score multiplier for a specific setup combination.

        Checks specificity in order: (pair+type+tf) → (type+tf) → (type) → neutral.
        """
        cache_key = (signal_type, pair, timeframe, source, last_n)
        if cache_key in self._cache:
            _cycle_created, cached_adj = self._cache[cache_key]
            return cached_adj

        # Try most specific first, then fall back
        lookups = [
            {"signal_type": signal_type, "pair": pair, "timeframe": timeframe},
            {"signal_type": signal_type, "timeframe": timeframe},
            {"signal_type": signal_type},
        ]
        if pair == "*":
            lookups = lookups[1:]  # skip pair-specific if not given

        for kwargs in lookups:
            # Filter None values
            query = {k: v for k, v in kwargs.items() if v != "*"}
            stats = self.tracker.get_stats(
                **query, source=source, last_n=last_n, weight_type="exponential"
            )
            if stats.total_trades >= self.min_trades:
                adj = self._compute_adjustment(
                    stats.win_rate, stats.total_trades, signal_type, pair, timeframe
                )
                self._cache[cache_key] = (self.cycle_number, adj)
                return adj

        # Not enough data — neutral
        adj = ScoreAdjustment(
            signal_type=signal_type,
            pair=pair,
            timeframe=timeframe,
            multiplier=NEUTRAL_FACTOR,
            reason="insufficient data",
        )
        self._cache[cache_key] = (self.cycle_number, adj)
        return adj

    def _compute_adjustment(
        self,
        win_rate: float,
        sample_size: int,
        signal_type: str,
        pair: str,
        timeframe: str,
    ) -> ScoreAdjustment:
        if win_rate >= STRONG_WIN_RATE:
            multiplier = self.boost
            reason = f"strong win rate ({win_rate:.0%})"
        elif win_rate <= WEAK_WIN_RATE:
            multiplier = self.penalty
            reason = f"weak win rate ({win_rate:.0%})"
        else:
            multiplier = NEUTRAL_FACTOR
            reason = f"neutral win rate ({win_rate:.0%})"

        # Blend toward neutral when sample is small
        confidence = min(1.0, sample_size / (self.min_trades * 3))
        multiplier = NEUTRAL_FACTOR + (multiplier - NEUTRAL_FACTOR) * confidence

        return ScoreAdjustment(
            signal_type=signal_type,
            pair=pair,
            timeframe=timeframe,
            multiplier=round(multiplier, 3),
            reason=reason,
            win_rate=win_rate,
            sample_size=sample_size,
        )

    def get_all_adjustments(
        self,
        pairs: list[str] | None = None,
        signal_types: list[str] | None = None,
        timeframes: list[str] | None = None,
        source: str | None = None,
    ) -> list[ScoreAdjustment]:
        """Get adjustments for all known combinations."""
        if pairs is None:
            pairs = self.tracker.get_all_pairs()
        if signal_types is None:
            signal_types = ["reversal", "pullback", "buildup", "bos"]
        if timeframes is None:
            timeframes = ["M15", "H1", "H4", "D"]

        adjustments = []
        for sig_type in signal_types:
            for pair in pairs:
                for tf in timeframes:
                    adj = self.get_adjustment(sig_type, pair, tf, source=source)
                    if adj.sample_size > 0:
                        adjustments.append(adj)
        return adjustments

    def clear_cache(self) -> None:
        """Clear the entire internal cache.

        Prefer ``advance_cycle()`` for per-cycle TTL-based eviction.
        This method is kept for compatibility and emergency resets.
        """
        self._cache.clear()
