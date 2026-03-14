"""Build-up breakout detection.

A buildup signal occurs when:
1. Price consolidates tightly (narrowing ranges)
2. A breakout candle closes outside the consolidation zone
3. Breakout direction aligns with the higher timeframe trend
"""

import pandas as pd
import numpy as np

from src.analysis.price_action import detect_buildup
from src.analysis.trend_strength import calculate_trend_strength
from src.signals.signal_base import Signal, SignalDirection, SignalType


def detect_buildup_signals(
    df: pd.DataFrame,
    pair: str = "",
    timeframe: str = "",
    buildup_window: int = 5,
    range_shrink: float = 0.5,
    breakout_atr_multiple: float = 1.5,
    min_rr: float = 2.0,
) -> list[Signal]:
    """Scan for build-up breakout setups.

    Args:
        buildup_window: bars to check for consolidation
        range_shrink: how much the range must shrink vs prior bars
        breakout_atr_multiple: breakout candle must be this * ATR
        min_rr: minimum risk/reward ratio
    """
    signals = []
    buildups = detect_buildup(df, buildup_window, range_shrink)

    if not buildups:
        return signals

    # Only look at the most recent buildup
    latest = buildups[-1]
    if latest.index < len(df) - 3:
        return signals  # buildup is too old

    # Define the consolidation zone
    consol_start = max(0, latest.index - buildup_window)
    consol_zone = df.iloc[consol_start : latest.index + 1]
    zone_high = consol_zone["high"].max()
    zone_low = consol_zone["low"].min()
    zone_range = zone_high - zone_low

    # Check if the last candle broke out
    last = df.iloc[-1]

    # ATR for sizing
    ranges = (df["high"] - df["low"]).rolling(14).mean()
    atr = ranges.iloc[-1] if not pd.isna(ranges.iloc[-1]) else zone_range

    # Get trend context
    trend = calculate_trend_strength(df)

    # Bullish breakout
    if last["close"] > zone_high:
        breakout_size = last["close"] - zone_high
        if breakout_size >= atr * 0.3:  # meaningful breakout
            stop_loss = zone_low - atr * 0.2
            risk = last["close"] - stop_loss
            take_profit = last["close"] + risk * min_rr

            strength = min(100, latest.strength + (breakout_size / atr) * 30)
            trend_bonus = 20 if trend.direction == "bullish" else 0

            signals.append(Signal(
                signal_type=SignalType.BUILDUP,
                direction=SignalDirection.BUY,
                pair=pair,
                timeframe=timeframe,
                timestamp=df.index[-1],
                entry_price=last["close"],
                stop_loss=stop_loss,
                take_profit=take_profit,
                quality_score=min(100, strength + trend_bonus),
                confluence_level=0,
                confidence=min(100, strength + trend_bonus),
                reasons=[
                    f"Bullish breakout above buildup zone ({zone_low:.5f}-{zone_high:.5f})",
                    f"Breakout size: {breakout_size:.5f}",
                    f"Trend: {trend.direction} ({trend.score:.0f}/100)",
                    f"R:R = 1:{min_rr:.1f}",
                ],
            ))

    # Bearish breakout
    elif last["close"] < zone_low:
        breakout_size = zone_low - last["close"]
        if breakout_size >= atr * 0.3:
            stop_loss = zone_high + atr * 0.2
            risk = stop_loss - last["close"]
            take_profit = last["close"] - risk * min_rr

            strength = min(100, latest.strength + (breakout_size / atr) * 30)
            trend_bonus = 20 if trend.direction == "bearish" else 0

            signals.append(Signal(
                signal_type=SignalType.BUILDUP,
                direction=SignalDirection.SELL,
                pair=pair,
                timeframe=timeframe,
                timestamp=df.index[-1],
                entry_price=last["close"],
                stop_loss=stop_loss,
                take_profit=take_profit,
                quality_score=min(100, strength + trend_bonus),
                confluence_level=0,
                confidence=min(100, strength + trend_bonus),
                reasons=[
                    f"Bearish breakout below buildup zone ({zone_low:.5f}-{zone_high:.5f})",
                    f"Breakout size: {breakout_size:.5f}",
                    f"Trend: {trend.direction} ({trend.score:.0f}/100)",
                    f"R:R = 1:{min_rr:.1f}",
                ],
            ))

    return signals
