"""Dynamic pair selection based on performance rankings.

Selects the top-performing pairs to trade based on historical metrics,
with configurable lookback and minimum trade thresholds.
"""

import logging
from dataclasses import dataclass

from src.learning.performance_tracker import PerformanceTracker, SetupStats
from src.config import TOP_PAIRS

logger = logging.getLogger("pa_bot")


@dataclass
class PairRanking:
    """A pair's ranking with supporting metrics."""

    pair: str
    rank: int
    expectancy: float
    win_rate: float
    profit_factor: float
    total_trades: int
    selected: bool


class PairSelector:
    """Select which pairs to actively trade based on performance data.

    Usage:
        selector = PairSelector(tracker, max_pairs=5)
        active_pairs = selector.select()
    """

    def __init__(
        self,
        tracker: PerformanceTracker,
        max_pairs: int = TOP_PAIRS,
        min_trades: int = 20,
        min_win_rate: float = 0.45,
        default_pairs: list[str] | None = None,
    ):
        self.tracker = tracker
        self.max_pairs = max_pairs
        self.min_trades = min_trades
        self.min_win_rate = min_win_rate
        self.default_pairs = default_pairs or [
            "EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "EUR_GBP",
        ]

    def select(
        self,
        source: str | None = None,
        last_n: int | None = None,
        session: str | None = None,
    ) -> list[str]:
        """Return the top pairs to trade, sorted by expectancy.

        When ``session`` is provided, ranks pairs using only trades from that
        session.  Falls back to global stats if session-specific data has fewer
        than ``min_trades`` qualifying pairs.  Falls back to ``default_pairs``
        if no pairs meet the selection criteria at all.
        """
        rankings = self.rank(source=source, last_n=last_n, session=session)
        selected = [r.pair for r in rankings if r.selected]

        if not selected:
            logger.info("No pairs meet criteria — using defaults")
            return self.default_pairs[: self.max_pairs]

        return selected

    def rank(
        self,
        source: str | None = None,
        last_n: int | None = None,
        session: str | None = None,
    ) -> list[PairRanking]:
        """Rank all pairs and mark which are selected.

        When ``session`` is provided, ranking uses session-scoped stats.  If
        fewer than ``min_trades`` qualifying pairs exist in that session, the
        method falls back transparently to global stats so selection is never
        left empty due to insufficient session data.
        """
        stats_list = self.tracker.get_pair_rankings(
            source=source, last_n=last_n, min_trades=self.min_trades,
            session=session,
        )

        if session and len(stats_list) < self.min_trades:
            logger.debug(
                "Session '%s' has only %d qualifying pair(s) — falling back to global stats",
                session, len(stats_list),
            )
            stats_list = self.tracker.get_pair_rankings(
                source=source, last_n=last_n, min_trades=self.min_trades,
            )

        # Filter out pairs below min win rate
        eligible = [s for s in stats_list if s.win_rate >= self.min_win_rate]

        rankings = []
        for i, stats in enumerate(stats_list):
            is_selected = stats in eligible and eligible.index(stats) < self.max_pairs
            rankings.append(PairRanking(
                pair=stats.pair,
                rank=i + 1,
                expectancy=round(stats.expectancy, 4),
                win_rate=round(stats.win_rate, 4),
                profit_factor=round(stats.profit_factor, 2) if stats.profit_factor != float("inf") else 999.0,
                total_trades=stats.total_trades,
                selected=is_selected,
            ))

        return rankings
