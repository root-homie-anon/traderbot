"""Download OHLC data from Yahoo Finance or broker APIs."""

import pandas as pd
import numpy as np
from pathlib import Path

from src.config import DATA_DIR


def load_csv(filepath: str | Path) -> pd.DataFrame:
    """Load OHLC data from a CSV file.

    Expected columns: open, high, low, close, volume (case-insensitive).
    Index should be datetime or a 'date'/'datetime' column.
    """
    df = pd.read_csv(filepath, parse_dates=True, index_col=0)
    df.columns = [c.lower().strip() for c in df.columns]

    required = {"open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {missing}")

    if "volume" not in df.columns:
        df["volume"] = 0

    df.sort_index(inplace=True)
    return df


def load_pair(pair: str, timeframe: str = "D") -> pd.DataFrame:
    """Load historical data for a specific pair and timeframe.

    Looks for file at data/historical/{PAIR}_{TF}.csv
    e.g. data/historical/EUR_USD_D.csv
    """
    filename = f"{pair}_{timeframe}.csv"
    filepath = DATA_DIR / "historical" / filename
    if not filepath.exists():
        raise FileNotFoundError(
            f"No data file found at {filepath}. "
            f"Download data first or place CSV at this path."
        )
    return load_csv(filepath)


def generate_sample_data(
    pair: str = "EUR_USD",
    periods: int = 1000,
    freq: str = "h",
    start_price: float = 1.1000,
    seed: int = 42,
) -> pd.DataFrame:
    """Generate synthetic OHLC data for testing."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2023-01-01", periods=periods, freq=freq)

    # Random walk for close prices
    returns = rng.normal(0, 0.001, periods)
    close = start_price * np.exp(np.cumsum(returns))

    # Generate OHLC around close
    spread = np.abs(rng.normal(0, 0.0005, periods))
    high = close + spread
    low = close - spread
    open_ = close + rng.normal(0, 0.0003, periods)

    # Ensure OHLC consistency
    high = np.maximum(high, np.maximum(open_, close))
    low = np.minimum(low, np.minimum(open_, close))

    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": rng.integers(100, 10000, periods),
        },
        index=dates,
    )
