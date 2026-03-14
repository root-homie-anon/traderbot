"""Core price action pattern detection.

Detects candlestick patterns: pin bars, engulfing, inside bars, doji,
power moves, and build-up (tight consolidation) zones.
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass
from enum import Enum


class PatternType(Enum):
    PIN_BAR = "pin_bar"
    ENGULFING = "engulfing"
    INSIDE_BAR = "inside_bar"
    DOJI = "doji"
    POWER_MOVE = "power_move"
    BUILDUP = "buildup"


class Direction(Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


@dataclass
class Pattern:
    type: PatternType
    direction: Direction
    index: int  # bar index in the dataframe
    timestamp: pd.Timestamp
    strength: float  # 0-100


def body_size(row: pd.Series) -> float:
    """Absolute size of candle body."""
    return abs(row["close"] - row["open"])


def candle_range(row: pd.Series) -> float:
    """Full range from high to low."""
    return row["high"] - row["low"]


def upper_wick(row: pd.Series) -> float:
    """Upper wick/shadow size."""
    return row["high"] - max(row["open"], row["close"])


def lower_wick(row: pd.Series) -> float:
    """Lower wick/shadow size."""
    return min(row["open"], row["close"]) - row["low"]


def is_bullish(row: pd.Series) -> bool:
    return row["close"] > row["open"]


def is_bearish(row: pd.Series) -> bool:
    return row["close"] < row["open"]


def detect_pin_bars(
    df: pd.DataFrame, wick_ratio: float = 2.0, body_max_pct: float = 0.33
) -> list[Pattern]:
    """Detect pin bar / hammer / shooting star patterns.

    A pin bar has a long wick (>= wick_ratio * body) and a small body
    (body <= body_max_pct of total range).
    """
    patterns = []
    for i in range(len(df)):
        row = df.iloc[i]
        cr = candle_range(row)
        if cr == 0:
            continue

        bs = body_size(row)
        uw = upper_wick(row)
        lw = lower_wick(row)

        body_pct = bs / cr
        if body_pct > body_max_pct:
            continue

        # Bullish pin bar: long lower wick
        if lw >= wick_ratio * bs and lw > uw:
            strength = min(100, (lw / cr) * 100)
            patterns.append(Pattern(
                type=PatternType.PIN_BAR,
                direction=Direction.BULLISH,
                index=i,
                timestamp=df.index[i],
                strength=strength,
            ))

        # Bearish pin bar: long upper wick
        elif uw >= wick_ratio * bs and uw > lw:
            strength = min(100, (uw / cr) * 100)
            patterns.append(Pattern(
                type=PatternType.PIN_BAR,
                direction=Direction.BEARISH,
                index=i,
                timestamp=df.index[i],
                strength=strength,
            ))

    return patterns


def detect_engulfing(df: pd.DataFrame) -> list[Pattern]:
    """Detect bullish and bearish engulfing patterns.

    Current candle's body fully engulfs previous candle's body.
    """
    patterns = []
    for i in range(1, len(df)):
        prev = df.iloc[i - 1]
        curr = df.iloc[i]

        prev_open, prev_close = prev["open"], prev["close"]
        curr_open, curr_close = curr["open"], curr["close"]

        curr_body = body_size(curr)
        prev_body = body_size(prev)

        if prev_body == 0:
            continue

        # Bullish engulfing: prev bearish, current bullish, body engulfs
        if (is_bearish(prev) and is_bullish(curr)
                and curr_close > prev_open and curr_open < prev_close):
            strength = min(100, (curr_body / prev_body) * 50)
            patterns.append(Pattern(
                type=PatternType.ENGULFING,
                direction=Direction.BULLISH,
                index=i,
                timestamp=df.index[i],
                strength=strength,
            ))

        # Bearish engulfing: prev bullish, current bearish, body engulfs
        elif (is_bullish(prev) and is_bearish(curr)
                and curr_open > prev_close and curr_close < prev_open):
            strength = min(100, (curr_body / prev_body) * 50)
            patterns.append(Pattern(
                type=PatternType.ENGULFING,
                direction=Direction.BEARISH,
                index=i,
                timestamp=df.index[i],
                strength=strength,
            ))

    return patterns


def detect_inside_bars(df: pd.DataFrame) -> list[Pattern]:
    """Detect inside bars (current bar's range within previous bar's range)."""
    patterns = []
    for i in range(1, len(df)):
        prev = df.iloc[i - 1]
        curr = df.iloc[i]

        if curr["high"] <= prev["high"] and curr["low"] >= prev["low"]:
            # Direction based on close relative to midpoint
            mid = (prev["high"] + prev["low"]) / 2
            if curr["close"] > mid:
                direction = Direction.BULLISH
            elif curr["close"] < mid:
                direction = Direction.BEARISH
            else:
                direction = Direction.NEUTRAL

            # Strength based on how tight the inside bar is
            prev_range = candle_range(prev)
            curr_range = candle_range(curr)
            tightness = 1 - (curr_range / prev_range) if prev_range > 0 else 0
            strength = min(100, tightness * 100)

            patterns.append(Pattern(
                type=PatternType.INSIDE_BAR,
                direction=direction,
                index=i,
                timestamp=df.index[i],
                strength=strength,
            ))

    return patterns


def detect_doji(df: pd.DataFrame, body_max_pct: float = 0.1) -> list[Pattern]:
    """Detect doji candles (very small body relative to range)."""
    patterns = []
    for i in range(len(df)):
        row = df.iloc[i]
        cr = candle_range(row)
        if cr == 0:
            continue

        bs = body_size(row)
        if bs / cr <= body_max_pct:
            strength = min(100, (1 - bs / cr) * 100)
            patterns.append(Pattern(
                type=PatternType.DOJI,
                direction=Direction.NEUTRAL,
                index=i,
                timestamp=df.index[i],
                strength=strength,
            ))

    return patterns


def detect_power_moves(
    df: pd.DataFrame, lookback: int = 20, threshold: float = 2.0
) -> list[Pattern]:
    """Detect power moves — candles significantly larger than average.

    A power move is a candle whose body is >= threshold * average body
    over the lookback period.
    """
    patterns = []
    bodies = df.apply(body_size, axis=1)
    avg_body = bodies.rolling(window=lookback, min_periods=lookback).mean()

    for i in range(lookback, len(df)):
        if avg_body.iloc[i] == 0:
            continue
        ratio = bodies.iloc[i] / avg_body.iloc[i]
        if ratio >= threshold:
            row = df.iloc[i]
            direction = Direction.BULLISH if is_bullish(row) else Direction.BEARISH
            strength = min(100, ratio * 30)
            patterns.append(Pattern(
                type=PatternType.POWER_MOVE,
                direction=direction,
                index=i,
                timestamp=df.index[i],
                strength=strength,
            ))

    return patterns


def detect_buildup(
    df: pd.DataFrame, window: int = 5, range_shrink: float = 0.5
) -> list[Pattern]:
    """Detect build-up zones — tight consolidation (narrowing ranges).

    Looks for `window` consecutive bars where the average range shrinks
    to `range_shrink` * the range of bars before the window.
    """
    patterns = []
    if len(df) < window * 2:
        return patterns

    ranges = df["high"] - df["low"]

    for i in range(window, len(df)):
        pre_avg = ranges.iloc[i - window * 2 : i - window].mean()
        curr_avg = ranges.iloc[i - window : i].mean()

        if pre_avg == 0:
            continue

        if curr_avg / pre_avg <= range_shrink:
            strength = min(100, (1 - curr_avg / pre_avg) * 100)
            patterns.append(Pattern(
                type=PatternType.BUILDUP,
                direction=Direction.NEUTRAL,
                index=i,
                timestamp=df.index[i],
                strength=strength,
            ))

    return patterns


def detect_all_patterns(df: pd.DataFrame) -> list[Pattern]:
    """Run all pattern detectors and return combined results sorted by index."""
    all_patterns = []
    all_patterns.extend(detect_pin_bars(df))
    all_patterns.extend(detect_engulfing(df))
    all_patterns.extend(detect_inside_bars(df))
    all_patterns.extend(detect_doji(df))
    all_patterns.extend(detect_power_moves(df))
    all_patterns.extend(detect_buildup(df))
    all_patterns.sort(key=lambda p: p.index)
    return all_patterns
