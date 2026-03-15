"""Detect performance failures and adjust rules automatically.

The self-corrector monitors trading performance for warning signs and
produces corrective actions — disabling signal types, tightening quality
thresholds, or flagging pairs for removal.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum

from src.learning.performance_tracker import PerformanceTracker

logger = logging.getLogger("pa_bot")


class ActionType(Enum):
    DISABLE_SIGNAL = "disable_signal"
    RAISE_QUALITY_MIN = "raise_quality_min"
    REMOVE_PAIR = "remove_pair"
    REDUCE_RISK = "reduce_risk"
    RE_ENABLE_SIGNAL = "re_enable_signal"
    LOWER_QUALITY_MIN = "lower_quality_min"


@dataclass
class Correction:
    """A corrective action recommended by the self-corrector."""

    action: ActionType
    target: str          # e.g. signal type, pair name
    detail: str          # human-readable explanation
    severity: str = ""   # "warning" or "critical"
    value: float = 0.0   # optional numeric value (e.g. new quality min)


# Thresholds
DISABLE_WIN_RATE = 0.30       # disable if win rate drops below 30%
WARN_WIN_RATE = 0.40          # warn if below 40%
RE_ENABLE_WIN_RATE = 0.50     # re-enable if recovered above 50%
REMOVE_PAIR_WIN_RATE = 0.25   # drop pair if below 25%
MIN_TRADES = 15               # minimum trades before acting
CONSECUTIVE_LOSS_LIMIT = 5    # flag after 5 consecutive losses


class SelfCorrector:
    """Monitor performance and produce corrective actions.

    Usage:
        corrector = SelfCorrector(tracker)
        corrections = corrector.evaluate()
        for c in corrections:
            apply_correction(c)
    """

    def __init__(
        self,
        tracker: PerformanceTracker,
        min_trades: int = MIN_TRADES,
        disabled_signals: set[str] | None = None,
    ):
        self.tracker = tracker
        self.min_trades = min_trades
        self.disabled_signals: set[str] = disabled_signals or set()

    def evaluate(
        self,
        signal_types: list[str] | None = None,
        pairs: list[str] | None = None,
        source: str | None = None,
        last_n: int | None = None,
    ) -> list[Correction]:
        """Run all checks and return corrective actions."""
        if signal_types is None:
            signal_types = ["reversal", "pullback", "buildup", "bos"]
        if pairs is None:
            pairs = self.tracker.get_all_pairs()

        corrections: list[Correction] = []

        corrections.extend(
            self._check_signal_types(signal_types, source, last_n)
        )
        corrections.extend(
            self._check_pairs(pairs, source, last_n)
        )

        return corrections

    def _check_signal_types(
        self,
        signal_types: list[str],
        source: str | None,
        last_n: int | None,
    ) -> list[Correction]:
        corrections = []
        for sig_type in signal_types:
            stats = self.tracker.get_stats(
                signal_type=sig_type, source=source, last_n=last_n
            )
            if stats.total_trades < self.min_trades:
                continue

            wr = stats.win_rate

            if sig_type in self.disabled_signals:
                # Check for recovery
                if wr >= RE_ENABLE_WIN_RATE:
                    corrections.append(Correction(
                        action=ActionType.RE_ENABLE_SIGNAL,
                        target=sig_type,
                        detail=f"{sig_type} recovered to {wr:.0%} win rate",
                        severity="warning",
                        value=wr,
                    ))
            elif wr <= DISABLE_WIN_RATE:
                corrections.append(Correction(
                    action=ActionType.DISABLE_SIGNAL,
                    target=sig_type,
                    detail=f"{sig_type} win rate {wr:.0%} below {DISABLE_WIN_RATE:.0%} threshold",
                    severity="critical",
                    value=wr,
                ))
            elif wr <= WARN_WIN_RATE:
                corrections.append(Correction(
                    action=ActionType.RAISE_QUALITY_MIN,
                    target=sig_type,
                    detail=f"{sig_type} win rate {wr:.0%} is marginal — raising quality minimum",
                    severity="warning",
                    value=65,  # bump quality_score_min to 65
                ))

            # Check if profit factor is terrible even with ok win rate
            if stats.profit_factor < 0.8 and wr > DISABLE_WIN_RATE:
                corrections.append(Correction(
                    action=ActionType.REDUCE_RISK,
                    target=sig_type,
                    detail=f"{sig_type} profit factor {stats.profit_factor:.2f} — reduce position size",
                    severity="warning",
                    value=0.5,
                ))

        return corrections

    def _check_pairs(
        self,
        pairs: list[str],
        source: str | None,
        last_n: int | None,
    ) -> list[Correction]:
        corrections = []
        for pair in pairs:
            stats = self.tracker.get_stats(
                pair=pair, source=source, last_n=last_n
            )
            if stats.total_trades < self.min_trades:
                continue

            if stats.win_rate <= REMOVE_PAIR_WIN_RATE:
                corrections.append(Correction(
                    action=ActionType.REMOVE_PAIR,
                    target=pair,
                    detail=f"{pair} win rate {stats.win_rate:.0%} — remove from active pairs",
                    severity="critical",
                    value=stats.win_rate,
                ))

        return corrections

    def apply_correction(self, correction: Correction) -> None:
        """Apply a correction to the corrector's internal state."""
        if correction.action == ActionType.DISABLE_SIGNAL:
            self.disabled_signals.add(correction.target)
            logger.warning("Disabled signal type: %s — %s", correction.target, correction.detail)
        elif correction.action == ActionType.RE_ENABLE_SIGNAL:
            self.disabled_signals.discard(correction.target)
            logger.info("Re-enabled signal type: %s — %s", correction.target, correction.detail)

    def is_signal_enabled(self, signal_type: str) -> bool:
        """Check if a signal type is currently enabled."""
        return signal_type not in self.disabled_signals
