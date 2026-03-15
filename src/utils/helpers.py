"""General utility functions."""

import pandas as pd


def pips_to_price(pips: float, pip_value: float = 0.0001) -> float:
    """Convert pips to price distance."""
    return pips * pip_value


def price_to_pips(price_distance: float, pip_value: float = 0.0001) -> float:
    """Convert price distance to pips."""
    if pip_value == 0:
        return 0.0
    return price_distance / pip_value


def get_pip_value(pair: str) -> float:
    """Get pip value for a pair (0.0001 for most, 0.01 for JPY pairs)."""
    if "JPY" in pair.upper():
        return 0.01
    return 0.0001


def timeframe_to_minutes(timeframe: str) -> int:
    """Convert timeframe string to minutes (e.g. 'H1' -> 60)."""
    mapping = {
        "M1": 1, "M5": 5, "M15": 15, "M30": 30,
        "H1": 60, "H4": 240,
        "D": 1440, "W": 10080, "MN": 43200,
    }
    return mapping.get(timeframe.upper(), 60)


def resample_ohlc(df: pd.DataFrame, target_tf: str) -> pd.DataFrame:
    """Resample OHLC data to a higher timeframe.

    Args:
        df: DataFrame with datetime index and open/high/low/close columns
        target_tf: target timeframe (e.g. "H4", "D")
    """
    minutes = timeframe_to_minutes(target_tf)
    rule = f"{minutes}min"

    return df.resample(rule).agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna()
