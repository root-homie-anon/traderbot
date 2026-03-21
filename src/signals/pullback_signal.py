"""First pullback detection after breakout.

A pullback signal occurs when:
1. A strong move / breakout has occurred recently
2. Price retraces to a key level (previous breakout zone, S/R, or Fib level)
3. A rejection pattern forms at the pullback level
"""

import pandas as pd
import numpy as np

from src.analysis.price_action import detect_pin_bars, detect_engulfing, Direction
from src.analysis.trend_strength import calculate_trend_strength
from src.analysis.confluence import calculate_confluence
from src.signals.signal_base import Signal, SignalDirection, SignalType


def detect_pullback_signals(
    df: pd.DataFrame,
    pair: str = "",
    timeframe: str = "",
    lookback: int = 20,
    retrace_min: float = 0.3,
    retrace_max: float = 0.7,
    min_rr: float = 2.0,
) -> list[Signal]:
    """Scan for first pullback setups after a strong move.

    Args:
        lookback: bars to look back for the initial move
        retrace_min: minimum retracement ratio (0.3 = 30%)
        retrace_max: maximum retracement ratio (0.7 = 70%)
        min_rr: minimum risk/reward ratio
    """
    signals = []

    if len(df) < lookback + 5:
        return signals

    window = df.iloc[-lookback:]
    trend = calculate_trend_strength(window)

    if trend.score < 30:
        return signals  # Need a clear prior move

    # Find the swing extreme of the initial move
    if trend.direction == "bullish":
        swing_low_idx = window["low"].idxmin()
        swing_high_idx = window["high"].idxmax()

        # Swing low must come before swing high (upward move)
        if swing_low_idx >= swing_high_idx:
            return signals

        swing_low = window.loc[swing_low_idx, "low"]
        swing_high = window.loc[swing_high_idx, "high"]
        move_size = swing_high - swing_low

        if move_size <= 0:
            return signals

        # Check if current price has pulled back
        current_price = df["close"].iloc[-1]
        retracement = (swing_high - current_price) / move_size

        if retrace_min <= retracement <= retrace_max:
            # Look for rejection pattern
            recent = df.iloc[-3:]
            pins = detect_pin_bars(recent)
            engulfs = detect_engulfing(recent)
            bullish_patterns = [
                p for p in pins + engulfs
                if p.direction == Direction.BULLISH
            ]

            if bullish_patterns:
                best = max(bullish_patterns, key=lambda p: p.strength)
                stop_loss = current_price - move_size * 0.2
                risk = current_price - stop_loss
                take_profit = swing_high + risk * 0.5  # Target beyond previous high

                rr = (take_profit - current_price) / risk if risk > 0 else 0
                if rr >= min_rr:
                    confluence = calculate_confluence(df, direction="bullish")
                    signals.append(Signal(
                        signal_type=SignalType.PULLBACK,
                        direction=SignalDirection.BUY,
                        pair=pair,
                        timeframe=timeframe,
                        timestamp=df.index[-1],
                        entry_price=current_price,
                        stop_loss=stop_loss,
                        take_profit=take_profit,
                        quality_score=min(100, best.strength + trend.score * 0.5),
                        confluence_level=confluence.score,
                        confidence=min(100, best.strength * 0.5 + trend.score * 0.5),
                        reasons=[
                            f"Bullish pullback ({retracement:.0%} retracement)",
                            f"Move: {swing_low:.5f} → {swing_high:.5f}",
                            f"{best.type.value} rejection pattern",
                            f"Trend strength: {trend.score:.0f}/100",
                        ],
                    ))

    elif trend.direction == "bearish":
        swing_high_idx = window["high"].idxmax()
        swing_low_idx = window["low"].idxmin()

        if swing_high_idx >= swing_low_idx:
            return signals

        swing_high = window.loc[swing_high_idx, "high"]
        swing_low = window.loc[swing_low_idx, "low"]
        move_size = swing_high - swing_low

        if move_size <= 0:
            return signals

        current_price = df["close"].iloc[-1]
        retracement = (current_price - swing_low) / move_size

        if retrace_min <= retracement <= retrace_max:
            recent = df.iloc[-3:]
            pins = detect_pin_bars(recent)
            engulfs = detect_engulfing(recent)
            bearish_patterns = [
                p for p in pins + engulfs
                if p.direction == Direction.BEARISH
            ]

            if bearish_patterns:
                best = max(bearish_patterns, key=lambda p: p.strength)
                stop_loss = current_price + move_size * 0.2
                risk = stop_loss - current_price
                take_profit = swing_low - risk * 0.5

                rr = (current_price - take_profit) / risk if risk > 0 else 0
                if rr >= min_rr:
                    confluence = calculate_confluence(df, direction="bearish")
                    signals.append(Signal(
                        signal_type=SignalType.PULLBACK,
                        direction=SignalDirection.SELL,
                        pair=pair,
                        timeframe=timeframe,
                        timestamp=df.index[-1],
                        entry_price=current_price,
                        stop_loss=stop_loss,
                        take_profit=take_profit,
                        quality_score=min(100, best.strength + trend.score * 0.5),
                        confluence_level=confluence.score,
                        confidence=min(100, best.strength * 0.5 + trend.score * 0.5),
                        reasons=[
                            f"Bearish pullback ({retracement:.0%} retracement)",
                            f"Move: {swing_high:.5f} → {swing_low:.5f}",
                            f"{best.type.value} rejection pattern",
                            f"Trend strength: {trend.score:.0f}/100",
                        ],
                    ))

    return signals
