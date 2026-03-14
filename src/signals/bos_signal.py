"""Break of Structure signal generation.

A BOS signal occurs when price breaks a key swing level,
confirming trend continuation or reversal.
"""

import pandas as pd

from src.analysis.break_of_structure import detect_bos, BOSType
from src.analysis.trend_strength import calculate_trend_strength
from src.signals.signal_base import Signal, SignalDirection, SignalType


def detect_bos_signals(
    df: pd.DataFrame,
    pair: str = "",
    timeframe: str = "",
    min_rr: float = 2.0,
    atr_period: int = 14,
) -> list[Signal]:
    """Scan for Break of Structure trade signals.

    Only generates signals for the most recent BOS events
    (last 3 bars).
    """
    signals = []
    events = detect_bos(df)

    if not events:
        return signals

    # ATR for stop/target calculation
    atr_series = (df["high"] - df["low"]).rolling(atr_period).mean()
    atr = atr_series.iloc[-1] if not pd.isna(atr_series.iloc[-1]) else 0

    if atr == 0:
        return signals

    trend = calculate_trend_strength(df)

    # Only look at BOS events in the last 3 bars
    recent_events = [e for e in events if e.break_bar >= len(df) - 3]

    for event in recent_events:
        current_price = df["close"].iloc[-1]

        if event.bos_type == BOSType.BULLISH:
            # Buy signal: stop below the broken level
            stop_loss = event.broken_level - atr * 0.5
            risk = current_price - stop_loss

            if risk <= 0:
                continue

            take_profit = current_price + risk * min_rr
            trend_bonus = 20 if trend.direction == "bullish" else 0

            signals.append(Signal(
                signal_type=SignalType.BOS,
                direction=SignalDirection.BUY,
                pair=pair,
                timeframe=timeframe,
                timestamp=df.index[-1],
                entry_price=current_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                quality_score=min(100, event.strength + trend_bonus),
                confluence_level=0,
                confidence=min(100, event.strength * 0.6 + trend.score * 0.4),
                reasons=[
                    f"Bullish BOS: broke above {event.broken_level:.5f}",
                    f"Trend: {trend.direction} ({trend.score:.0f}/100)",
                    f"R:R = 1:{min_rr:.1f}",
                ],
            ))

        elif event.bos_type == BOSType.BEARISH:
            stop_loss = event.broken_level + atr * 0.5
            risk = stop_loss - current_price

            if risk <= 0:
                continue

            take_profit = current_price - risk * min_rr
            trend_bonus = 20 if trend.direction == "bearish" else 0

            signals.append(Signal(
                signal_type=SignalType.BOS,
                direction=SignalDirection.SELL,
                pair=pair,
                timeframe=timeframe,
                timestamp=df.index[-1],
                entry_price=current_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                quality_score=min(100, event.strength + trend_bonus),
                confluence_level=0,
                confidence=min(100, event.strength * 0.6 + trend.score * 0.4),
                reasons=[
                    f"Bearish BOS: broke below {event.broken_level:.5f}",
                    f"Trend: {trend.direction} ({trend.score:.0f}/100)",
                    f"R:R = 1:{min_rr:.1f}",
                ],
            ))

    return signals
