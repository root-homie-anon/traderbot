"""Pytest fixtures for the trading bot test suite."""

import pytest
import pandas as pd
import numpy as np
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_ohlc():
    """Generate sample OHLC DataFrame for testing (100 bars, random walk)."""
    np.random.seed(42)
    n = 100
    dates = pd.date_range("2024-01-01", periods=n, freq="h")
    close = 1.1000 + np.cumsum(np.random.randn(n) * 0.001)
    high = close + np.abs(np.random.randn(n) * 0.0005)
    low = close - np.abs(np.random.randn(n) * 0.0005)
    open_ = close + np.random.randn(n) * 0.0003

    high = np.maximum(high, np.maximum(open_, close))
    low = np.minimum(low, np.minimum(open_, close))

    return pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": np.random.randint(100, 10000, n),
    }, index=dates)


@pytest.fixture
def trending_up_ohlc():
    """OHLC data with a clear uptrend (higher highs and higher lows)."""
    np.random.seed(123)
    n = 100
    dates = pd.date_range("2024-01-01", periods=n, freq="h")

    # Strong uptrend with small retracements
    trend = np.linspace(0, 0.05, n)
    noise = np.random.randn(n) * 0.001
    close = 1.1000 + trend + noise

    high = close + np.abs(np.random.randn(n) * 0.0003)
    low = close - np.abs(np.random.randn(n) * 0.0002)
    open_ = close - np.abs(np.random.randn(n) * 0.0001)  # mostly bullish

    high = np.maximum(high, np.maximum(open_, close))
    low = np.minimum(low, np.minimum(open_, close))

    return pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": np.random.randint(100, 10000, n),
    }, index=dates)


@pytest.fixture
def trending_down_ohlc():
    """OHLC data with a clear downtrend."""
    np.random.seed(456)
    n = 100
    dates = pd.date_range("2024-01-01", periods=n, freq="h")

    trend = np.linspace(0, -0.05, n)
    noise = np.random.randn(n) * 0.001
    close = 1.1000 + trend + noise

    high = close + np.abs(np.random.randn(n) * 0.0002)
    low = close - np.abs(np.random.randn(n) * 0.0003)
    open_ = close + np.abs(np.random.randn(n) * 0.0001)  # mostly bearish

    high = np.maximum(high, np.maximum(open_, close))
    low = np.minimum(low, np.minimum(open_, close))

    return pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": np.random.randint(100, 10000, n),
    }, index=dates)


@pytest.fixture
def ranging_ohlc():
    """OHLC data with sideways price action."""
    np.random.seed(789)
    n = 100
    dates = pd.date_range("2024-01-01", periods=n, freq="h")

    # Oscillate around 1.1000
    close = 1.1000 + np.sin(np.linspace(0, 4 * np.pi, n)) * 0.002 + np.random.randn(n) * 0.0005

    high = close + np.abs(np.random.randn(n) * 0.0003)
    low = close - np.abs(np.random.randn(n) * 0.0003)
    open_ = close + np.random.randn(n) * 0.0002

    high = np.maximum(high, np.maximum(open_, close))
    low = np.minimum(low, np.minimum(open_, close))

    return pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": np.random.randint(100, 10000, n),
    }, index=dates)


@pytest.fixture
def pin_bar_ohlc():
    """OHLC data with a clear bullish pin bar at the end."""
    np.random.seed(42)
    n = 30
    dates = pd.date_range("2024-01-01", periods=n, freq="h")
    close = 1.1000 + np.cumsum(np.random.randn(n) * 0.0005)

    high = close + np.abs(np.random.randn(n) * 0.0003)
    low = close - np.abs(np.random.randn(n) * 0.0003)
    open_ = close + np.random.randn(n) * 0.0002

    high = np.maximum(high, np.maximum(open_, close))
    low = np.minimum(low, np.minimum(open_, close))

    # Create a clear bullish pin bar at the last candle
    last_close = close[-1]
    open_[-1] = last_close - 0.0001  # small body
    close[-1] = last_close
    high[-1] = last_close + 0.0001   # tiny upper wick
    low[-1] = last_close - 0.0020    # long lower wick

    return pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": np.random.randint(100, 10000, n),
    }, index=dates)
