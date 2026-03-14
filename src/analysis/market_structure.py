"""Classify market structure: Accumulation, Advancing, Distribution, Declining.

Uses swing high/low analysis to determine current market phase.
"""

import pandas as pd
import numpy as np
from enum import Enum
from dataclasses import dataclass

from src.analysis.support_resistance import find_pivots


class MarketPhase(Enum):
    ACCUMULATION = "accumulation"   # Range after downtrend
    ADVANCING = "advancing"         # Uptrend (higher highs/lows)
    DISTRIBUTION = "distribution"   # Range after uptrend
    DECLINING = "declining"         # Downtrend (lower highs/lows)
    UNKNOWN = "unknown"


@dataclass
class StructureResult:
    phase: MarketPhase
    confidence: float           # 0-100
    swing_highs: list[float]    # Recent swing high prices
    swing_lows: list[float]     # Recent swing low prices
    higher_highs: bool
    higher_lows: bool
    lower_highs: bool
    lower_lows: bool


def classify_structure(
    df: pd.DataFrame,
    pivot_left: int = 5,
    pivot_right: int = 5,
    min_swings: int = 3,
    range_threshold: float = 0.005,
) -> StructureResult:
    """Classify the current market structure based on swing analysis.

    Args:
        df: OHLC DataFrame
        pivot_left: bars to the left for pivot detection
        pivot_right: bars to the right for pivot detection
        min_swings: minimum swing points needed for classification
        range_threshold: max price change % to consider "ranging"
    """
    swing_highs, swing_lows = find_pivots(df, pivot_left, pivot_right)

    # Extract recent swing prices
    sh_prices = [s[1] for s in swing_highs[-min_swings:]]
    sl_prices = [s[1] for s in swing_lows[-min_swings:]]

    if len(sh_prices) < 2 or len(sl_prices) < 2:
        return StructureResult(
            phase=MarketPhase.UNKNOWN,
            confidence=0,
            swing_highs=sh_prices,
            swing_lows=sl_prices,
            higher_highs=False, higher_lows=False,
            lower_highs=False, lower_lows=False,
        )

    # Check swing patterns
    higher_highs = all(sh_prices[i] > sh_prices[i - 1] for i in range(1, len(sh_prices)))
    higher_lows = all(sl_prices[i] > sl_prices[i - 1] for i in range(1, len(sl_prices)))
    lower_highs = all(sh_prices[i] < sh_prices[i - 1] for i in range(1, len(sh_prices)))
    lower_lows = all(sl_prices[i] < sl_prices[i - 1] for i in range(1, len(sl_prices)))

    # Overall price direction for ranging detection
    start_price = df["close"].iloc[0]
    end_price = df["close"].iloc[-1]
    price_change_pct = abs(end_price - start_price) / start_price

    # Determine if we're in a range
    is_ranging = price_change_pct < range_threshold

    # Prior trend detection (first half vs second half)
    mid = len(df) // 2
    first_half_trend = df["close"].iloc[mid] - df["close"].iloc[0]

    # Classification
    if higher_highs and higher_lows:
        phase = MarketPhase.ADVANCING
        confidence = 80 + min(20, len(sh_prices) * 5)
    elif lower_highs and lower_lows:
        phase = MarketPhase.DECLINING
        confidence = 80 + min(20, len(sh_prices) * 5)
    elif is_ranging and first_half_trend < 0:
        phase = MarketPhase.ACCUMULATION
        confidence = 50 + min(30, (1 - price_change_pct / range_threshold) * 30)
    elif is_ranging and first_half_trend > 0:
        phase = MarketPhase.DISTRIBUTION
        confidence = 50 + min(30, (1 - price_change_pct / range_threshold) * 30)
    elif is_ranging:
        # Ranging but no clear prior trend
        phase = MarketPhase.ACCUMULATION if end_price > start_price else MarketPhase.DISTRIBUTION
        confidence = 30
    else:
        # Trending but not clean HH/HL or LH/LL
        if end_price > start_price:
            phase = MarketPhase.ADVANCING
        else:
            phase = MarketPhase.DECLINING
        confidence = 40

    return StructureResult(
        phase=phase,
        confidence=min(100, confidence),
        swing_highs=sh_prices,
        swing_lows=sl_prices,
        higher_highs=higher_highs,
        higher_lows=higher_lows,
        lower_highs=lower_highs,
        lower_lows=lower_lows,
    )


def get_trend_direction(structure: StructureResult) -> str:
    """Simple helper: returns 'up', 'down', or 'range'."""
    if structure.phase == MarketPhase.ADVANCING:
        return "up"
    elif structure.phase == MarketPhase.DECLINING:
        return "down"
    else:
        return "range"
