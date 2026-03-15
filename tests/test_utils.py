"""Tests for utility modules."""

import pytest
import pandas as pd
import numpy as np

from src.utils.helpers import (
    pips_to_price, price_to_pips, get_pip_value,
    timeframe_to_minutes, resample_ohlc,
)
from src.utils.validators import validate_ohlc, validate_signal, validate_pair
from src.utils.formatters import (
    format_pnl, format_pct, format_stats, format_trade_summary,
)
from src.signals.signal_base import Signal, SignalDirection, SignalType


# ──────────────────── Helpers ────────────────────


class TestHelpers:

    def test_pips_to_price(self):
        assert pips_to_price(10) == pytest.approx(0.0010)
        assert pips_to_price(10, pip_value=0.01) == pytest.approx(0.10)

    def test_price_to_pips(self):
        assert price_to_pips(0.0020) == pytest.approx(20)
        assert price_to_pips(0.20, pip_value=0.01) == pytest.approx(20)

    def test_price_to_pips_zero(self):
        assert price_to_pips(0.001, pip_value=0) == 0.0

    def test_get_pip_value(self):
        assert get_pip_value("EUR_USD") == 0.0001
        assert get_pip_value("USD_JPY") == 0.01
        assert get_pip_value("EUR_JPY") == 0.01
        assert get_pip_value("GBP_USD") == 0.0001

    def test_timeframe_to_minutes(self):
        assert timeframe_to_minutes("M15") == 15
        assert timeframe_to_minutes("H1") == 60
        assert timeframe_to_minutes("H4") == 240
        assert timeframe_to_minutes("D") == 1440
        assert timeframe_to_minutes("unknown") == 60  # default

    def test_resample_ohlc(self):
        dates = pd.date_range("2026-01-01", periods=240, freq="1min")
        df = pd.DataFrame({
            "open": np.random.uniform(1.09, 1.11, 240),
            "high": np.random.uniform(1.10, 1.12, 240),
            "low": np.random.uniform(1.08, 1.10, 240),
            "close": np.random.uniform(1.09, 1.11, 240),
            "volume": np.random.randint(100, 1000, 240),
        }, index=dates)
        resampled = resample_ohlc(df, "H1")
        assert len(resampled) == 4  # 240 min / 60 = 4 hours


# ──────────────────── Validators ────────────────────


class TestValidators:

    @pytest.fixture
    def good_df(self):
        dates = pd.date_range("2026-01-01", periods=10, freq="1h")
        return pd.DataFrame({
            "open": [1.1] * 10,
            "high": [1.12] * 10,
            "low": [1.09] * 10,
            "close": [1.11] * 10,
        }, index=dates)

    def test_valid_ohlc(self, good_df):
        errors = validate_ohlc(good_df)
        assert errors == []

    def test_missing_column(self, good_df):
        df = good_df.drop(columns=["close"])
        errors = validate_ohlc(df)
        assert any("close" in e for e in errors)

    def test_empty_df(self):
        df = pd.DataFrame(columns=["open", "high", "low", "close"])
        errors = validate_ohlc(df)
        assert any("empty" in e for e in errors)

    def test_bad_index(self, good_df):
        df = good_df.reset_index(drop=True)
        errors = validate_ohlc(df)
        assert any("DatetimeIndex" in e for e in errors)

    def test_high_below_low(self, good_df):
        df = good_df.copy()
        df.iloc[0, df.columns.get_loc("high")] = 1.08  # below low
        errors = validate_ohlc(df)
        assert any("high < low" in e for e in errors)

    def test_nan_values(self, good_df):
        df = good_df.copy()
        df.iloc[0, df.columns.get_loc("open")] = float("nan")
        errors = validate_ohlc(df)
        assert any("NaN" in e for e in errors)

    def test_valid_signal(self):
        signal = Signal(
            signal_type=SignalType.REVERSAL,
            direction=SignalDirection.BUY,
            pair="EUR_USD", timeframe="H1",
            timestamp=pd.Timestamp("2026-01-01"),
            entry_price=1.1000, stop_loss=1.0980, take_profit=1.1040,
            quality_score=70, confluence_level=3, confidence=65,
        )
        assert validate_signal(signal) == []

    def test_buy_stop_above_entry(self):
        signal = Signal(
            signal_type=SignalType.REVERSAL,
            direction=SignalDirection.BUY,
            pair="EUR_USD", timeframe="H1",
            timestamp=pd.Timestamp("2026-01-01"),
            entry_price=1.1000, stop_loss=1.1020, take_profit=1.1040,
            quality_score=70, confluence_level=3, confidence=65,
        )
        errors = validate_signal(signal)
        assert any("BUY stop loss" in e for e in errors)

    def test_sell_stop_below_entry(self):
        signal = Signal(
            signal_type=SignalType.REVERSAL,
            direction=SignalDirection.SELL,
            pair="EUR_USD", timeframe="H1",
            timestamp=pd.Timestamp("2026-01-01"),
            entry_price=1.1000, stop_loss=1.0980, take_profit=1.0960,
            quality_score=70, confluence_level=3, confidence=65,
        )
        errors = validate_signal(signal)
        assert any("SELL stop loss" in e for e in errors)

    def test_quality_score_out_of_range(self):
        signal = Signal(
            signal_type=SignalType.REVERSAL,
            direction=SignalDirection.BUY,
            pair="EUR_USD", timeframe="H1",
            timestamp=pd.Timestamp("2026-01-01"),
            entry_price=1.1000, stop_loss=1.0980, take_profit=1.1040,
            quality_score=150, confluence_level=3, confidence=65,
        )
        errors = validate_signal(signal)
        assert any("quality score" in e for e in errors)

    def test_validate_pair(self):
        assert validate_pair("EUR_USD")
        assert validate_pair("GBP_JPY")
        assert not validate_pair("")
        assert not validate_pair("EURUSD")
        assert not validate_pair("EU_USD")
        assert not validate_pair("EUR_US1")


# ──────────────────── Formatters ────────────────────


class TestFormatters:

    def test_format_pnl(self):
        assert format_pnl(5.5) == "+5.50"
        assert format_pnl(-3.2) == "-3.20"
        assert format_pnl(0) == "+0.00"

    def test_format_pct(self):
        assert format_pct(0.55) == "55.0%"
        assert format_pct(0.123, decimals=2) == "12.30%"

    def test_format_stats(self):
        from src.learning.performance_tracker import SetupStats
        stats = SetupStats(
            pair="EUR_USD", signal_type="reversal", timeframe="H1",
            total_trades=20, wins=12, losses=8,
            total_pnl=15.5, total_risk=20.0,
            gross_profit=24.0, gross_loss=8.5,
        )
        output = format_stats(stats)
        assert "EUR_USD" in output
        assert "reversal" in output
        assert "60.0%" in output

    def test_format_trade_summary(self):
        trade = {
            "direction": "buy",
            "pair": "EUR_USD",
            "pnl": 3.50,
            "exit_reason": "take_profit",
            "quality_score": 72.5,
        }
        output = format_trade_summary(trade)
        assert "BUY" in output
        assert "EUR_USD" in output
        assert "+3.50" in output
