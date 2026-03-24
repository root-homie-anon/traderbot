"""Correlation guard — prevent over-concentration in correlated currency pairs.

Within each correlation group, all pairs share the same underlying directional
exposure.  For example every pair in USD_WEAK rises when the dollar weakens, so
two BUY trades inside that group are the same bet placed twice.

The guard counts how many *open* trades in a correlation group share the
incoming trade's effective direction, and blocks the new trade when that count
would meet or exceed `max_correlated`.
"""

# ---------------------------------------------------------------------------
# Correlation groups
# ---------------------------------------------------------------------------
# Within a group, BUY on any pair is the *same* directional bet.
# SELL on any pair is the *opposite* bet.
# There is no cross-group direction inversion needed here: group membership
# already encodes the semantic relationship.
# ---------------------------------------------------------------------------

CORRELATION_GROUPS: dict[str, list[str]] = {
    "USD_WEAK": ["EUR_USD", "GBP_USD", "AUD_USD", "NZD_USD"],
    "USD_STRONG": ["USD_JPY", "USD_CAD", "USD_CHF"],
    "JPY_WEAK": ["USD_JPY", "EUR_JPY", "GBP_JPY", "AUD_JPY"],
}

# Pre-computed reverse index: pair -> list of group names it belongs to
_PAIR_TO_GROUPS: dict[str, list[str]] = {}
for _group, _pairs in CORRELATION_GROUPS.items():
    for _pair in _pairs:
        _PAIR_TO_GROUPS.setdefault(_pair, []).append(_group)


class CorrelationGuard:
    """Block new trades that would exceed the correlated-position cap.

    Args:
        max_correlated: Maximum number of same-direction trades allowed within
            a single correlation group at any one time.  Defaults to 2, meaning
            a third correlated trade is blocked.
    """

    def __init__(self, max_correlated: int = 2) -> None:
        self.max_correlated = max_correlated

    def can_open_trade(
        self,
        pair: str,
        direction: str,
        open_trades: dict[str, dict[str, str]],
    ) -> tuple[bool, str]:
        """Check whether a new trade is permitted under correlation rules.

        Args:
            pair:        Instrument to be traded, e.g. ``"EUR_USD"``.
            direction:   ``"buy"`` or ``"sell"`` (``SignalDirection.value``).
            open_trades: Current open positions keyed by order ID.
                         Each value must contain ``"pair"`` and
                         ``"direction"`` string fields.

        Returns:
            A ``(allowed, reason)`` tuple.  When *allowed* is ``True``,
            *reason* is an empty string.  When ``False``, *reason* describes
            which group caused the block.
        """
        groups_for_pair = _PAIR_TO_GROUPS.get(pair, [])

        for group in groups_for_pair:
            group_pairs = set(CORRELATION_GROUPS[group])
            count = sum(
                1
                for trade in open_trades.values()
                if trade["pair"] in group_pairs
                and trade["direction"] == direction
            )
            if count >= self.max_correlated:
                return (
                    False,
                    f"max correlated positions in {group} reached",
                )

        return (True, "")
