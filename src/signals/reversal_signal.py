"""Reversal setup detection at support/resistance.

A reversal signal occurs when:
1. Price reaches a strong S/R level
2. A rejection pattern forms (pin bar, engulfing, doji)
3. Market structure and trend support the reversal direction
"""

import math

import pandas as pd

from src.analysis.price_action import (
    detect_pin_bars, detect_engulfing, detect_doji,
    PatternType, Direction,
)
from src.analysis.support_resistance import (
    find_support_resistance, nearest_support, nearest_resistance,
)
from src.analysis.confluence import calculate_confluence
from src.signals.signal_base import Signal, SignalDirection, SignalType


def detect_reversal_signals(
    df: pd.DataFrame,
    pair: str = "",
    timeframe: str = "",
    sr_proximity_pct: float = 0.005,
    min_rr: float = 2.0,
    lookback_bars: int = 3,
) -> list[Signal]:
    """Scan for reversal setups at S/R levels.

    Args:
        sr_proximity_pct: how close price must be to S/R to consider
        min_rr: minimum risk/reward ratio
        lookback_bars: how many recent bars to check for patterns
    """
    signals = []
    levels = find_support_resistance(df)
    if not levels:
        return signals

    current_price = df["close"].iloc[-1]

    # Get recent patterns (last `lookback_bars` candles)
    recent_df = df.iloc[-lookback_bars:]
    pin_bars = detect_pin_bars(recent_df)
    engulfings = detect_engulfing(recent_df)
    dojis = detect_doji(recent_df)

    all_patterns = pin_bars + engulfings + dojis
    if not all_patterns:
        return signals

    # ATR over last 14 bars — used for stop placement on both sides
    _atr_raw = (df["high"] - df["low"]).rolling(14).mean().iloc[-1]
    atr: float = float(_atr_raw) if (len(df) >= 14 and not math.isnan(float(_atr_raw))) else float((df["high"] - df["low"]).mean())

    # Check for bullish reversal at support
    support = nearest_support(levels, current_price)
    if support:
        distance_pct = abs(current_price - support.price) / current_price
        if distance_pct <= sr_proximity_pct:
            bullish_patterns = [
                p for p in all_patterns
                if p.direction in (Direction.BULLISH, Direction.NEUTRAL)
            ]
            if bullish_patterns:
                best_pattern = max(bullish_patterns, key=lambda p: p.strength)
                stop_loss = support.price - atr * 0.5
                risk = current_price - stop_loss

                # Target: next resistance or min R:R
                resistance = nearest_resistance(levels, current_price)
                if resistance:
                    take_profit = resistance.price
                else:
                    take_profit = current_price + risk * min_rr

                rr = (take_profit - current_price) / risk if risk > 0 else 0
                if rr >= min_rr:
                    confluence = calculate_confluence(df, direction="bullish")
                    signals.append(Signal(
                        signal_type=SignalType.REVERSAL,
                        direction=SignalDirection.BUY,
                        pair=pair,
                        timeframe=timeframe,
                        timestamp=df.index[-1],
                        entry_price=current_price,
                        stop_loss=stop_loss,
                        take_profit=take_profit,
                        quality_score=best_pattern.strength,
                        confluence_level=confluence.score,
                        confidence=best_pattern.strength * 0.7 + support.strength * 0.3,
                        reasons=[
                            f"Bullish {best_pattern.type.value} at support {support.price:.5f}",
                            f"Support has {support.touches} touches",
                            f"R:R = 1:{rr:.1f}",
                        ],
                    ))

    # Check for bearish reversal at resistance
    resistance = nearest_resistance(levels, current_price)
    if resistance:
        distance_pct = abs(resistance.price - current_price) / current_price
        if distance_pct <= sr_proximity_pct:
            bearish_patterns = [
                p for p in all_patterns
                if p.direction in (Direction.BEARISH, Direction.NEUTRAL)
            ]
            if bearish_patterns:
                best_pattern = max(bearish_patterns, key=lambda p: p.strength)
                stop_loss = max(resistance.price, current_price) + atr * 0.3
                risk = stop_loss - current_price

                support = nearest_support(levels, current_price)
                if support:
                    take_profit = support.price
                else:
                    take_profit = current_price - risk * min_rr

                rr = (current_price - take_profit) / risk if risk > 0 else 0
                if rr >= min_rr:
                    confluence = calculate_confluence(df, direction="bearish")
                    signals.append(Signal(
                        signal_type=SignalType.REVERSAL,
                        direction=SignalDirection.SELL,
                        pair=pair,
                        timeframe=timeframe,
                        timestamp=df.index[-1],
                        entry_price=current_price,
                        stop_loss=stop_loss,
                        take_profit=take_profit,
                        quality_score=best_pattern.strength,
                        confluence_level=confluence.score,
                        confidence=best_pattern.strength * 0.7 + resistance.strength * 0.3,
                        reasons=[
                            f"Bearish {best_pattern.type.value} at resistance {resistance.price:.5f}",
                            f"Resistance has {resistance.touches} touches",
                            f"R:R = 1:{rr:.1f}",
                        ],
                    ))

    return signals
