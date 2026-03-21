"""Forex market session filtering.

Only trade pairs during their optimal liquidity windows.
Avoids low-liquidity periods, rollover, weekends, and off-session pairs.
"""

from datetime import datetime, timezone

# Optimal trading windows per pair (UTC hours).
# Tuple format: (start_hour, end_hour). When start > end, wraps midnight.
OPTIMAL_WINDOWS: dict[str, list[tuple[int, int]]] = {
    "EUR_USD": [(7, 17)],           # London + London-NY overlap (extended to capture full NY overlap)
    "GBP_USD": [(7, 17)],           # London + London-NY overlap (extended to capture full NY overlap)
    "USD_JPY": [(0, 9), (12, 17)],  # Tokyo + London-NY overlap (extended)
    "AUD_USD": [(22, 9)],           # Sydney open (22:00 UTC) + Tokyo (wraps midnight)
    "EUR_GBP": [(7, 16)],           # London session only
    "USD_CAD": [(12, 21)],          # NY session (extended to session close)
    "NZD_USD": [(21, 6)],           # Sydney/Tokyo (wraps midnight)
    "EUR_JPY": [(7, 16)],           # London (Tokyo-London overlap + London)
    "GBP_JPY": [(7, 16)],           # London (Tokyo-London overlap + London)
    "AUD_JPY": [(0, 9)],            # Full Asian session
}

# Market is closed on weekends
# Friday close: 21:00 UTC, Sunday open: 21:00 UTC
# Avoid: Friday after 19:00 UTC (liquidity drain), Sunday before 23:00 UTC (gaps)
FRIDAY_CUTOFF_HOUR = 19
SUNDAY_SAFE_HOUR = 23

# Daily rollover at 21:00 UTC (5 PM ET) — avoid 15 min window
ROLLOVER_HOUR = 21


def _in_window(hour: int, window: tuple[int, int]) -> bool:
    """Check if hour falls within a trading window (handles midnight wrap)."""
    start, end = window
    if start <= end:
        return start <= hour < end
    else:
        return hour >= start or hour < end


def is_pair_tradeable(pair: str, utc_now: datetime | None = None) -> bool:
    """Check if a pair should be traded at the current time.

    Returns False if:
    - Weekend (Saturday or Sunday before safe hour)
    - Friday after cutoff
    - Near daily rollover
    - Outside the pair's optimal trading window
    """
    if utc_now is None:
        utc_now = datetime.now(timezone.utc)

    weekday = utc_now.weekday()  # 0=Mon, 4=Fri, 5=Sat, 6=Sun
    hour = utc_now.hour

    # Saturday: market closed
    if weekday == 5:
        return False

    # Sunday: only after safe hour
    if weekday == 6 and hour < SUNDAY_SAFE_HOUR:
        return False

    # Friday: avoid after cutoff (liquidity drains)
    if weekday == 4 and hour >= FRIDAY_CUTOFF_HOUR:
        return False

    # Avoid rollover window (21:00 UTC +/- 15 min, simplify to hour check)
    if hour == ROLLOVER_HOUR:
        return False

    # Check pair-specific optimal window
    windows = OPTIMAL_WINDOWS.get(pair)
    if windows is None:
        return True  # Unknown pair, allow trading

    return any(_in_window(hour, w) for w in windows)


def get_tradeable_pairs(pairs: list[str], utc_now: datetime | None = None) -> list[str]:
    """Filter a list of pairs to only those tradeable right now."""
    return [p for p in pairs if is_pair_tradeable(p, utc_now)]


def get_session_name(utc_now: datetime | None = None) -> str:
    """Return the current active session name."""
    if utc_now is None:
        utc_now = datetime.now(timezone.utc)
    hour = utc_now.hour

    # Check most specific/narrow sessions first to avoid overlap masking
    if 12 <= hour < 16:
        return "London-NY Overlap"
    if 7 <= hour < 12:
        return "London"
    if 16 <= hour < 21:
        return "New York"
    if hour >= 21:
        return "Sydney"
    if 0 <= hour < 9:
        return "Tokyo"
    return "Transition"
