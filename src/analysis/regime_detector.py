"""ADX-based market regime detection.

Classifies the current market state into one of four regimes by computing
the 14-period ADX (Wilder smoothing) from OHLC data.  Each regime carries
a set of signal-type multipliers that the paper trader applies on top of the
base quality score so that the right signal types are favoured in the right
market conditions.

Regime boundaries (ADX):
    <  20  →  ranging
    20–25  →  transitioning
    25–40  →  trending
    >  40  →  strong_trend
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd

logger = logging.getLogger("pa_bot")

# Minimum rows required to produce a reliable 14-period ADX
_MIN_ROWS: int = 30

# Wilder smoothing period
_ADX_PERIOD: int = 14

# Regime thresholds
_THRESHOLD_RANGING: float = 20.0
_THRESHOLD_TRANSITIONING: float = 25.0
_THRESHOLD_STRONG_TREND: float = 40.0

_SIGNAL_MULTIPLIERS: dict[str, dict[str, float]] = {
    "ranging":       {"reversal": 1.2, "pullback": 0.8, "buildup": 1.0, "bos": 0.8},
    "transitioning": {"reversal": 1.0, "pullback": 1.0, "buildup": 1.0, "bos": 1.0},
    "trending":      {"reversal": 0.8, "pullback": 1.2, "buildup": 1.0, "bos": 1.2},
    "strong_trend":  {"reversal": 0.5, "pullback": 1.3, "buildup": 1.0, "bos": 1.3},
}


class RegimeType(str, Enum):
    RANGING = "ranging"
    TRANSITIONING = "transitioning"
    TRENDING = "trending"
    STRONG_TREND = "strong_trend"


@dataclass
class MarketRegime:
    regime_type: str                      # one of RegimeType values
    adx_value: float                      # most-recent ADX reading
    signal_multipliers: dict[str, float]  # multipliers keyed by signal type


def _wilder_smooth(series: np.ndarray, period: int) -> np.ndarray:
    """Apply Wilder's smoothing to a 1-D NumPy array.

    First value is the plain sum of the first ``period`` elements.
    Subsequent values: prev * (period - 1) / period + current.
    Returns an array of the same length; values before index ``period - 1``
    are filled with NaN.
    """
    result = np.full(len(series), np.nan)
    if len(series) < period:
        return result

    # Seed with the straight sum of the first window
    result[period - 1] = float(np.sum(series[:period]))

    for i in range(period, len(series)):
        result[i] = result[i - 1] * (period - 1) / period + series[i]

    return result


def _calculate_adx(df: pd.DataFrame, period: int = _ADX_PERIOD) -> float:
    """Calculate the most-recent ADX value from an OHLC DataFrame.

    Requires columns: high, low, close (case-insensitive lookup not performed —
    caller is expected to pass a standard DataFrame).

    Returns NaN when there is insufficient data.
    """
    if len(df) < _MIN_ROWS:
        return float("nan")

    high: np.ndarray = df["high"].to_numpy(dtype=float)
    low: np.ndarray = df["low"].to_numpy(dtype=float)
    close: np.ndarray = df["close"].to_numpy(dtype=float)
    n = len(high)

    # True Range and directional movement
    tr = np.full(n, np.nan)
    plus_dm = np.full(n, np.nan)
    minus_dm = np.full(n, np.nan)

    for i in range(1, n):
        tr[i] = max(
            high[i] - low[i],
            abs(high[i] - close[i - 1]),
            abs(low[i] - close[i - 1]),
        )
        up_move = high[i] - high[i - 1]
        down_move = low[i - 1] - low[i]

        plus_dm[i] = up_move if (up_move > down_move and up_move > 0) else 0.0
        minus_dm[i] = down_move if (down_move > up_move and down_move > 0) else 0.0

    # Wilder-smooth TR, +DM, -DM (skip index 0 which is NaN)
    smoothed_tr = _wilder_smooth(tr[1:], period)
    smoothed_plus_dm = _wilder_smooth(plus_dm[1:], period)
    smoothed_minus_dm = _wilder_smooth(minus_dm[1:], period)

    # +DI / -DI
    with np.errstate(divide="ignore", invalid="ignore"):
        plus_di = np.where(smoothed_tr > 0, smoothed_plus_dm / smoothed_tr * 100, 0.0)
        minus_di = np.where(smoothed_tr > 0, smoothed_minus_dm / smoothed_tr * 100, 0.0)

    # DX
    di_sum = plus_di + minus_di
    with np.errstate(divide="ignore", invalid="ignore"):
        dx = np.where(di_sum > 0, np.abs(plus_di - minus_di) / di_sum * 100, 0.0)

    # Smooth DX → ADX
    adx = _wilder_smooth(dx, period)

    # Return the last valid value
    valid = adx[~np.isnan(adx)]
    if len(valid) == 0:
        return float("nan")
    return float(valid[-1])


def _regime_from_adx(adx: float) -> RegimeType:
    if adx < _THRESHOLD_RANGING:
        return RegimeType.RANGING
    if adx < _THRESHOLD_TRANSITIONING:
        return RegimeType.TRANSITIONING
    if adx < _THRESHOLD_STRONG_TREND:
        return RegimeType.TRENDING
    return RegimeType.STRONG_TREND


class RegimeDetector:
    """Stateless ADX-based market regime classifier.

    Usage::

        detector = RegimeDetector()
        regime = detector.detect_regime(df)
        multiplier = regime.signal_multipliers["reversal"]
    """

    def detect_regime(self, df: pd.DataFrame) -> MarketRegime:
        """Detect the current market regime from an OHLC DataFrame.

        Args:
            df: DataFrame with columns high, low, close (at minimum).
                Expects at least 30 rows for a meaningful result.

        Returns:
            MarketRegime with regime_type, adx_value, and signal_multipliers.
            Falls back to ``transitioning`` (neutral multipliers) when ADX
            cannot be computed due to insufficient data.
        """
        adx = _calculate_adx(df)

        if np.isnan(adx):
            logger.debug(
                "ADX calculation returned NaN (rows=%d) — defaulting to transitioning",
                len(df),
            )
            regime_type = RegimeType.TRANSITIONING
            adx = 0.0
        else:
            regime_type = _regime_from_adx(adx)

        return MarketRegime(
            regime_type=regime_type.value,
            adx_value=round(adx, 2),
            signal_multipliers=_SIGNAL_MULTIPLIERS[regime_type.value],
        )
