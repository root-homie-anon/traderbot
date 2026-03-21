"""Break of Structure (BOS) detection.

Detects when price breaks a previous swing high (bullish BOS) or
swing low (bearish BOS), signaling a potential trend change or
continuation.
"""

import pandas as pd
from dataclasses import dataclass
from enum import Enum

from src.analysis.support_resistance import find_pivots


class BOSType(Enum):
    BULLISH = "bullish"     # Break above swing high
    BEARISH = "bearish"     # Break below swing low


@dataclass
class BOSEvent:
    bos_type: BOSType
    broken_level: float     # The swing level that was broken
    break_bar: int          # Bar index where the break occurred
    break_timestamp: pd.Timestamp
    strength: float         # 0-100


def detect_bos(
    df: pd.DataFrame,
    pivot_left: int = 5,
    pivot_right: int = 5,
    confirmation_bars: int = 2,
) -> list[BOSEvent]:
    """Detect Break of Structure events.

    A bullish BOS occurs when price closes above a prior swing high.
    A bearish BOS occurs when price closes below a prior swing low.

    Args:
        confirmation_bars: number of bars that must close beyond the level
                           (1 = break bar only, 2 = break bar + 1 confirmation)
    """
    swing_highs, swing_lows = find_pivots(df, pivot_left, pivot_right)
    events = []

    # Track the most recent swing high/low that hasn't been broken
    for i, (sh_idx, sh_price, sh_ts) in enumerate(swing_highs):
        # Look for bars after this swing high that close above it
        for j in range(sh_idx + pivot_right + 1, len(df)):
            if df["close"].iloc[j] > sh_price:
                # Check confirmation
                confirmed = True
                for k in range(1, confirmation_bars):
                    if j + k >= len(df):
                        confirmed = False
                        break
                    if df["close"].iloc[j + k] <= sh_price:
                        confirmed = False
                        break

                if confirmed:
                    # Strength based on how decisively the level was broken
                    break_distance = (df["close"].iloc[j] - sh_price) / sh_price
                    strength = min(100, break_distance * 10000)

                    events.append(BOSEvent(
                        bos_type=BOSType.BULLISH,
                        broken_level=sh_price,
                        break_bar=j,
                        break_timestamp=df.index[j],
                        strength=strength,
                    ))
                break  # Only detect first break per swing

    for i, (sl_idx, sl_price, sl_ts) in enumerate(swing_lows):
        for j in range(sl_idx + pivot_right + 1, len(df)):
            if df["close"].iloc[j] < sl_price:
                confirmed = True
                for k in range(1, confirmation_bars):
                    if j + k >= len(df):
                        confirmed = False
                        break
                    if df["close"].iloc[j + k] >= sl_price:
                        confirmed = False
                        break

                if confirmed:
                    break_distance = (sl_price - df["close"].iloc[j]) / sl_price
                    strength = min(100, break_distance * 10000)

                    events.append(BOSEvent(
                        bos_type=BOSType.BEARISH,
                        broken_level=sl_price,
                        break_bar=j,
                        break_timestamp=df.index[j],
                        strength=strength,
                    ))
                break

    events.sort(key=lambda e: e.break_bar)
    return events


def latest_bos(df: pd.DataFrame, lookback: int = 50) -> BOSEvent | None:
    """Get the most recent BOS event within the lookback window."""
    window = df.iloc[-lookback:] if len(df) > lookback else df
    events = detect_bos(window)
    return events[-1] if events else None
