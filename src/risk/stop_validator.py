"""Validate stop loss placement relative to market structure."""

import pandas as pd


def validate_stop(
    entry_price: float,
    stop_loss: float,
    direction: str,
    df: pd.DataFrame | None = None,
    min_stop_pips: float = 5.0,
    max_stop_pips: float = 100.0,
    pip_value: float = 0.0001,
) -> dict:
    """Validate that a stop loss is sensible.

    Args:
        entry_price: planned entry price
        stop_loss: planned stop loss price
        direction: "buy" or "sell"
        df: OHLC data for ATR-based validation
        min_stop_pips: minimum stop distance in pips
        max_stop_pips: maximum stop distance in pips
        pip_value: value of one pip

    Returns:
        dict with valid (bool), reason (str), adjusted_stop (float or None)
    """
    stop_distance = abs(entry_price - stop_loss)
    stop_pips = stop_distance / pip_value

    # Direction check
    if direction == "buy" and stop_loss >= entry_price:
        return {"valid": False, "reason": "Stop must be below entry for buys", "adjusted_stop": None}
    if direction == "sell" and stop_loss <= entry_price:
        return {"valid": False, "reason": "Stop must be above entry for sells", "adjusted_stop": None}

    # Min/max distance
    if stop_pips < min_stop_pips:
        return {"valid": False, "reason": f"Stop too tight ({stop_pips:.1f} pips < {min_stop_pips})", "adjusted_stop": None}
    if stop_pips > max_stop_pips:
        return {"valid": False, "reason": f"Stop too wide ({stop_pips:.1f} pips > {max_stop_pips})", "adjusted_stop": None}

    # ATR-based validation if data provided
    if df is not None and len(df) >= 14:
        atr = (df["high"] - df["low"]).rolling(14).mean().iloc[-1]
        if not pd.isna(atr) and atr > 0:
            if stop_distance < atr * 0.3:
                return {"valid": False, "reason": "Stop tighter than 0.3x ATR", "adjusted_stop": None}
            if stop_distance > atr * 5:
                return {"valid": False, "reason": "Stop wider than 5x ATR", "adjusted_stop": None}

    return {"valid": True, "reason": "OK", "adjusted_stop": None}
