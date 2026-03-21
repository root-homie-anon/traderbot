"""Detect performance failures and adjust rules automatically.

The self-corrector monitors trading performance for warning signs and
produces corrective actions — disabling signal types, tightening quality
thresholds, or flagging pairs for removal.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum

from src.learning.performance_tracker import PerformanceTracker, CONSECUTIVE_LOSS_LIMIT_DEFAULT

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
    session: str | None = None  # None = global; set = per-session only


# Thresholds
DISABLE_WIN_RATE = 0.30       # disable if win rate drops below 30%
WARN_WIN_RATE = 0.40          # warn if below 40%
RE_ENABLE_WIN_RATE = 0.50     # re-enable if recovered above 50%
REMOVE_PAIR_WIN_RATE = 0.25   # drop pair if below 25%
MIN_TRADES = 50               # minimum trades before acting
CONSECUTIVE_LOSS_LIMIT = CONSECUTIVE_LOSS_LIMIT_DEFAULT  # flag after 5 consecutive losses


class SelfCorrector:
    """Monitor performance and produce corrective actions.

    Disabled signals are tracked at two levels:
    - ``disabled_signals``: global set[str] — disabled in all sessions.
    - ``disabled_signals_by_session``: set[tuple[str, str]] — pairs of
      (signal_type, session) disabled only in that session.

    Usage:
        corrector = SelfCorrector(tracker)
        corrections = corrector.evaluate(session="London")
        for c in corrections:
            corrector.apply_correction(c)
    """

    def __init__(
        self,
        tracker: PerformanceTracker,
        min_trades: int = MIN_TRADES,
        disabled_signals: set[str] | None = None,
    ):
        self.tracker = tracker
        self.min_trades = min_trades
        # Global disables (signal_type)
        self.disabled_signals: set[str] = disabled_signals or set()
        # Per-session disables (signal_type, session)
        self.disabled_signals_by_session: set[tuple[str, str]] = set()

    def evaluate(
        self,
        signal_types: list[str] | None = None,
        pairs: list[str] | None = None,
        source: str | None = None,
        last_n: int | None = None,
        session: str | None = None,
    ) -> list[Correction]:
        """Run all checks and return corrective actions.

        When ``session`` is provided, aggregate checks (signal types, pairs)
        query only trades from that session and produce per-session corrections.
        Consecutive-loss checks always run against global history so short
        streaks are never missed due to thin session-specific data.
        """
        if signal_types is None:
            signal_types = ["reversal", "pullback", "buildup", "bos"]
        if pairs is None:
            pairs = self.tracker.get_all_pairs()

        corrections: list[Correction] = []

        corrections.extend(
            self._check_signal_types(signal_types, source, last_n, session)
        )
        corrections.extend(
            self._check_pairs(pairs, source, last_n, session)
        )
        corrections.extend(
            self._check_consecutive_losses(signal_types, source)
        )
        corrections.extend(
            self._check_consecutive_losses_pairs(pairs, source)
        )

        return corrections

    def _check_signal_types(
        self,
        signal_types: list[str],
        source: str | None,
        last_n: int | None,
        session: str | None = None,
    ) -> list[Correction]:
        corrections = []
        for sig_type in signal_types:
            stats = self.tracker.get_stats(
                signal_type=sig_type, source=source, last_n=last_n,
                session=session,
            )
            if stats.total_trades < self.min_trades:
                continue

            wr = stats.win_rate
            is_disabled = self._is_disabled(sig_type, session)

            if is_disabled:
                # Check for recovery
                if wr >= RE_ENABLE_WIN_RATE:
                    corrections.append(Correction(
                        action=ActionType.RE_ENABLE_SIGNAL,
                        target=sig_type,
                        detail=f"{sig_type} recovered to {wr:.0%} win rate"
                               + (f" in {session}" if session else ""),
                        severity="warning",
                        value=wr,
                        session=session,
                    ))
            elif wr <= DISABLE_WIN_RATE:
                corrections.append(Correction(
                    action=ActionType.DISABLE_SIGNAL,
                    target=sig_type,
                    detail=f"{sig_type} win rate {wr:.0%} below {DISABLE_WIN_RATE:.0%} threshold"
                           + (f" in {session}" if session else ""),
                    severity="critical",
                    value=wr,
                    session=session,
                ))
            elif wr <= WARN_WIN_RATE:
                corrections.append(Correction(
                    action=ActionType.RAISE_QUALITY_MIN,
                    target=sig_type,
                    detail=f"{sig_type} win rate {wr:.0%} is marginal — raising quality minimum"
                           + (f" in {session}" if session else ""),
                    severity="warning",
                    value=65,  # bump quality_score_min to 65
                    session=session,
                ))

            # Check if profit factor is terrible even with ok win rate
            if stats.profit_factor < 0.8 and wr > DISABLE_WIN_RATE:
                corrections.append(Correction(
                    action=ActionType.REDUCE_RISK,
                    target=sig_type,
                    detail=f"{sig_type} profit factor {stats.profit_factor:.2f} — reduce position size"
                           + (f" in {session}" if session else ""),
                    severity="warning",
                    value=0.5,
                    session=session,
                ))

        return corrections

    def _check_pairs(
        self,
        pairs: list[str],
        source: str | None,
        last_n: int | None,
        session: str | None = None,
    ) -> list[Correction]:
        corrections = []
        for pair in pairs:
            stats = self.tracker.get_stats(
                pair=pair, source=source, last_n=last_n, session=session,
            )
            if stats.total_trades < self.min_trades:
                continue

            if stats.win_rate <= REMOVE_PAIR_WIN_RATE:
                corrections.append(Correction(
                    action=ActionType.REMOVE_PAIR,
                    target=pair,
                    detail=f"{pair} win rate {stats.win_rate:.0%} — remove from active pairs"
                           + (f" in {session}" if session else ""),
                    severity="critical",
                    value=stats.win_rate,
                    session=session,
                ))

        return corrections

    def _is_disabled(self, signal_type: str, session: str | None) -> bool:
        """Return True if the signal is disabled globally or in this session."""
        if signal_type in self.disabled_signals:
            return True
        if session and (signal_type, session) in self.disabled_signals_by_session:
            return True
        return False

    def _check_consecutive_losses(
        self,
        signal_types: list[str],
        source: str | None,
    ) -> list[Correction]:
        """Disable a signal type immediately if its last N trades are all losses.

        Only fires for signal types not already disabled, so it complements
        the aggregate win-rate check rather than duplicating it.
        """
        corrections = []
        for sig_type in signal_types:
            if sig_type in self.disabled_signals:
                continue

            outcomes = self.tracker.get_recent_outcomes(
                signal_type=sig_type,
                source=source,
                last_n=CONSECUTIVE_LOSS_LIMIT,
            )

            # Need a full window of trades before acting
            if len(outcomes) < CONSECUTIVE_LOSS_LIMIT:
                continue

            if not any(outcomes):  # all losses
                corrections.append(Correction(
                    action=ActionType.DISABLE_SIGNAL,
                    target=sig_type,
                    detail=(
                        f"{sig_type} has {CONSECUTIVE_LOSS_LIMIT} consecutive losses "
                        f"— disabling immediately"
                    ),
                    severity="critical",
                    value=0.0,
                ))

        return corrections

    def _check_consecutive_losses_pairs(
        self,
        pairs: list[str],
        source: str | None,
    ) -> list[Correction]:
        """Reduce risk on a pair if its last N trades are all losses.

        Uses REDUCE_RISK rather than REMOVE_PAIR so it fires faster than
        the aggregate win-rate check, giving the system a chance to pull
        back before enough data accumulates for a full removal decision.
        """
        corrections = []
        for pair in pairs:
            outcomes = self.tracker.get_recent_outcomes(
                pair=pair,
                source=source,
                last_n=CONSECUTIVE_LOSS_LIMIT,
            )

            if len(outcomes) < CONSECUTIVE_LOSS_LIMIT:
                continue

            if not any(outcomes):  # all losses
                corrections.append(Correction(
                    action=ActionType.REDUCE_RISK,
                    target=pair,
                    detail=(
                        f"{pair} has {CONSECUTIVE_LOSS_LIMIT} consecutive losses "
                        f"— reducing position size"
                    ),
                    severity="critical",
                    value=0.5,
                ))

        return corrections

    def apply_correction(self, correction: Correction) -> None:
        """Apply a correction to the corrector's internal state."""
        if correction.action == ActionType.DISABLE_SIGNAL:
            if correction.session:
                self.disabled_signals_by_session.add(
                    (correction.target, correction.session)
                )
                logger.warning(
                    "Disabled signal type: %s in %s — %s",
                    correction.target, correction.session, correction.detail,
                )
            else:
                self.disabled_signals.add(correction.target)
                logger.warning(
                    "Disabled signal type: %s (global) — %s",
                    correction.target, correction.detail,
                )
        elif correction.action == ActionType.RE_ENABLE_SIGNAL:
            if correction.session:
                self.disabled_signals_by_session.discard(
                    (correction.target, correction.session)
                )
                logger.info(
                    "Re-enabled signal type: %s in %s — %s",
                    correction.target, correction.session, correction.detail,
                )
            else:
                self.disabled_signals.discard(correction.target)
                logger.info(
                    "Re-enabled signal type: %s (global) — %s",
                    correction.target, correction.detail,
                )

    def is_signal_enabled(self, signal_type: str, session: str | None = None) -> bool:
        """Check if a signal type is currently enabled.

        A signal is considered disabled if it is globally disabled OR if a
        ``session`` is given and it is disabled for that session.
        """
        return not self._is_disabled(signal_type, session)
