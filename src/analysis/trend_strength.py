"""Trend strength analysis via candle size comparison.

Strong trends show large candles in the trend direction and small
retracement candles. This module quantifies that observation.
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass

from src.analysis.price_action import body_size, is_bullish, is_bearish


@dataclass
class TrendStrengthResult:
    score: float            # 0-100, higher = stronger trend
    direction: str          # "bullish", "bearish", or "neutral"
    avg_trend_body: float   # average body size of trend candles
    avg_retrace_body: float # average body size of retracement candles
    trend_candle_pct: float # % of candles in trend direction
    momentum: float         # rate of price change


def calculate_trend_strength(
    df: pd.DataFrame, lookback: int = 20
) -> TrendStrengthResult:
    """Calculate trend strength over the lookback window.

    Factors:
    1. Ratio of trend candle bodies vs retracement candle bodies
    2. Percentage of candles in trend direction
    3. Momentum (net price change relative to total range)
    """
    if len(df) < lookback:
        lookback = len(df)

    window = df.iloc[-lookback:]

    # Determine overall direction
    net_change = window["close"].iloc[-1] - window["close"].iloc[0]

    if abs(net_change) < 1e-10:
        return TrendStrengthResult(
            score=0, direction="neutral",
            avg_trend_body=0, avg_retrace_body=0,
            trend_candle_pct=50, momentum=0,
        )

    direction = "bullish" if net_change > 0 else "bearish"

    # Separate trend vs retracement candles
    bodies = window.apply(body_size, axis=1)
    if direction == "bullish":
        trend_mask = window.apply(is_bullish, axis=1)
    else:
        trend_mask = window.apply(is_bearish, axis=1)

    trend_bodies = bodies[trend_mask]
    retrace_bodies = bodies[~trend_mask]

    avg_trend = trend_bodies.mean() if len(trend_bodies) > 0 else 0
    avg_retrace = retrace_bodies.mean() if len(retrace_bodies) > 0 else 0

    # Factor 1: body ratio (trend candles bigger = stronger)
    if avg_retrace > 0:
        body_ratio_score = min(40, (avg_trend / avg_retrace - 1) * 20)
    else:
        body_ratio_score = 40  # No retracement = very strong

    # Factor 2: candle direction percentage
    trend_pct = len(trend_bodies) / len(bodies) * 100
    pct_score = min(30, (trend_pct - 50) * 0.6)  # 50% = 0, 100% = 30

    # Factor 3: momentum
    total_range = window["high"].max() - window["low"].min()
    if total_range > 0:
        momentum = abs(net_change) / total_range
        momentum_score = min(30, momentum * 30)
    else:
        momentum = 0
        momentum_score = 0

    score = max(0, min(100, body_ratio_score + pct_score + momentum_score))

    return TrendStrengthResult(
        score=score,
        direction=direction,
        avg_trend_body=avg_trend,
        avg_retrace_body=avg_retrace,
        trend_candle_pct=trend_pct,
        momentum=momentum,
    )


def is_strong_trend(df: pd.DataFrame, min_score: float = 40, lookback: int = 20) -> bool:
    """Quick check: is the trend strong enough to trade?"""
    result = calculate_trend_strength(df, lookback)
    return result.score >= min_score
