"""Input validation utilities."""

import pandas as pd

from src.signals.signal_base import Signal, SignalDirection


def validate_ohlc(df: pd.DataFrame) -> list[str]:
    """Validate that a DataFrame has proper OHLC structure.

    Returns a list of error messages (empty if valid).
    """
    errors = []
    required = ["open", "high", "low", "close"]

    for col in required:
        if col not in df.columns:
            errors.append(f"missing column: {col}")

    if errors:
        return errors

    if len(df) == 0:
        errors.append("dataframe is empty")
        return errors

    if not isinstance(df.index, pd.DatetimeIndex):
        errors.append("index must be DatetimeIndex")

    # Check for high >= low
    bad_bars = (df["high"] < df["low"]).sum()
    if bad_bars > 0:
        errors.append(f"{bad_bars} bars have high < low")

    # Check for NaN
    nan_count = df[required].isna().sum().sum()
    if nan_count > 0:
        errors.append(f"{nan_count} NaN values in OHLC data")

    return errors


def validate_signal(signal: Signal) -> list[str]:
    """Validate a trading signal for logical consistency.

    Returns a list of error messages (empty if valid).
    """
    errors = []

    if signal.entry_price <= 0:
        errors.append("entry price must be positive")
    if signal.stop_loss <= 0:
        errors.append("stop loss must be positive")
    if signal.take_profit <= 0:
        errors.append("take profit must be positive")

    if signal.direction == SignalDirection.BUY:
        if signal.stop_loss >= signal.entry_price:
            errors.append("BUY stop loss must be below entry")
        if signal.take_profit <= signal.entry_price:
            errors.append("BUY take profit must be above entry")
    else:
        if signal.stop_loss <= signal.entry_price:
            errors.append("SELL stop loss must be above entry")
        if signal.take_profit >= signal.entry_price:
            errors.append("SELL take profit must be below entry")

    if signal.quality_score < 0 or signal.quality_score > 100:
        errors.append("quality score must be 0-100")

    if signal.risk_reward_ratio < 0:
        errors.append("risk/reward must be non-negative")

    return errors


def validate_pair(pair: str) -> bool:
    """Check if a pair string looks valid (e.g. 'EUR_USD')."""
    if not pair or not isinstance(pair, str):
        return False
    parts = pair.upper().split("_")
    if len(parts) != 2:
        return False
    return all(len(p) == 3 and p.isalpha() for p in parts)
