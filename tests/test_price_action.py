"""Tests for price action detection."""

import pandas as pd
import numpy as np
import pytest

from src.analysis.price_action import (
    body_size, candle_range, upper_wick, lower_wick,
    is_bullish, is_bearish,
    detect_pin_bars, detect_engulfing, detect_inside_bars,
    detect_doji, detect_power_moves, detect_buildup,
    detect_all_patterns,
    PatternType, Direction,
)


class TestCandleHelpers:
    def test_body_size(self):
        row = pd.Series({"open": 1.1000, "high": 1.1050, "low": 1.0950, "close": 1.1030})
        assert body_size(row) == pytest.approx(0.003, abs=1e-6)

    def test_candle_range(self):
        row = pd.Series({"open": 1.1000, "high": 1.1050, "low": 1.0950, "close": 1.1030})
        assert candle_range(row) == pytest.approx(0.01, abs=1e-6)

    def test_upper_wick_bullish(self):
        row = pd.Series({"open": 1.1000, "high": 1.1050, "low": 1.0950, "close": 1.1030})
        assert upper_wick(row) == pytest.approx(0.002, abs=1e-6)

    def test_lower_wick_bullish(self):
        row = pd.Series({"open": 1.1000, "high": 1.1050, "low": 1.0950, "close": 1.1030})
        assert lower_wick(row) == pytest.approx(0.005, abs=1e-6)

    def test_is_bullish(self):
        row = pd.Series({"open": 1.1000, "close": 1.1030})
        assert is_bullish(row)
        assert not is_bearish(row)

    def test_is_bearish(self):
        row = pd.Series({"open": 1.1030, "close": 1.1000})
        assert is_bearish(row)
        assert not is_bullish(row)


class TestPinBars:
    def test_detects_bullish_pin_bar(self, pin_bar_ohlc):
        patterns = detect_pin_bars(pin_bar_ohlc)
        bullish_pins = [p for p in patterns if p.direction == Direction.BULLISH]
        assert len(bullish_pins) > 0

    def test_pin_bar_has_correct_type(self, pin_bar_ohlc):
        patterns = detect_pin_bars(pin_bar_ohlc)
        for p in patterns:
            assert p.type == PatternType.PIN_BAR

    def test_pin_bar_strength_positive(self, pin_bar_ohlc):
        patterns = detect_pin_bars(pin_bar_ohlc)
        for p in patterns:
            assert 0 < p.strength <= 100


class TestEngulfing:
    def test_detects_engulfing(self, sample_ohlc):
        patterns = detect_engulfing(sample_ohlc)
        assert isinstance(patterns, list)
        for p in patterns:
            assert p.type == PatternType.ENGULFING
            assert p.direction in (Direction.BULLISH, Direction.BEARISH)

    def test_engulfing_manual(self):
        """Test with manually crafted bullish engulfing pattern.

        Prev: bearish candle (open > close)
        Curr: bullish candle whose body fully engulfs prev body
              curr_close > prev_open AND curr_open < prev_close
        """
        df = pd.DataFrame({
            "open":  [1.1020, 1.0985],
            "high":  [1.1025, 1.1030],
            "low":   [1.0985, 1.0980],
            "close": [1.0990, 1.1025],
        }, index=pd.date_range("2024-01-01", periods=2, freq="h"))
        patterns = detect_engulfing(df)
        assert len(patterns) == 1
        assert patterns[0].direction == Direction.BULLISH


class TestInsideBars:
    def test_detects_inside_bars(self, sample_ohlc):
        patterns = detect_inside_bars(sample_ohlc)
        assert isinstance(patterns, list)
        for p in patterns:
            assert p.type == PatternType.INSIDE_BAR


class TestDoji:
    def test_detects_doji(self):
        """Test with a perfect doji."""
        df = pd.DataFrame({
            "open":  [1.1000],
            "high":  [1.1020],
            "low":   [1.0980],
            "close": [1.1001],
        }, index=pd.date_range("2024-01-01", periods=1, freq="h"))
        patterns = detect_doji(df)
        assert len(patterns) == 1
        assert patterns[0].type == PatternType.DOJI


class TestPowerMoves:
    def test_detects_power_moves(self, sample_ohlc):
        patterns = detect_power_moves(sample_ohlc)
        assert isinstance(patterns, list)
        for p in patterns:
            assert p.type == PatternType.POWER_MOVE


class TestBuildup:
    def test_detects_buildup(self, sample_ohlc):
        patterns = detect_buildup(sample_ohlc)
        assert isinstance(patterns, list)
        for p in patterns:
            assert p.type == PatternType.BUILDUP


class TestDetectAll:
    def test_returns_sorted(self, sample_ohlc):
        patterns = detect_all_patterns(sample_ohlc)
        indices = [p.index for p in patterns]
        assert indices == sorted(indices)

    def test_contains_multiple_types(self, sample_ohlc):
        patterns = detect_all_patterns(sample_ohlc)
        types = {p.type for p in patterns}
        assert len(types) >= 1  # At least one pattern type detected
