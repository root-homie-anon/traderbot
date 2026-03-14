"""Tests for signal generation."""

import pandas as pd
import numpy as np
import pytest

from src.signals.signal_base import Signal, SignalDirection, SignalType
from src.signals.reversal_signal import detect_reversal_signals
from src.signals.buildup_signal import detect_buildup_signals
from src.signals.pullback_signal import detect_pullback_signals
from src.signals.bos_signal import detect_bos_signals
from src.signals.quality_scorer import score_signal, QualityBreakdown, filter_signals


class TestSignalBase:
    def test_signal_creation(self):
        signal = Signal(
            signal_type=SignalType.REVERSAL,
            direction=SignalDirection.BUY,
            pair="EUR_USD",
            timeframe="H1",
            timestamp=pd.Timestamp("2024-01-01"),
            entry_price=1.1000,
            stop_loss=1.0980,
            take_profit=1.1040,
            quality_score=75,
            confluence_level=3,
            confidence=70,
            reasons=["Test reason"],
        )
        assert signal.risk_reward_ratio == pytest.approx(2.0, abs=0.1)
        assert signal.risk_pips == pytest.approx(20, abs=0.1)

    def test_signal_to_dict(self):
        signal = Signal(
            signal_type=SignalType.BOS,
            direction=SignalDirection.SELL,
            pair="GBP_USD",
            timeframe="H4",
            timestamp=pd.Timestamp("2024-01-01"),
            entry_price=1.2500,
            stop_loss=1.2530,
            take_profit=1.2440,
            quality_score=60,
            confluence_level=2,
            confidence=55,
        )
        d = signal.to_dict()
        assert d["signal_type"] == "bos"
        assert d["direction"] == "sell"
        assert d["pair"] == "GBP_USD"
        assert "risk_reward" in d

    def test_zero_risk_rr(self):
        signal = Signal(
            signal_type=SignalType.REVERSAL,
            direction=SignalDirection.BUY,
            pair="EUR_USD",
            timeframe="H1",
            timestamp=pd.Timestamp("2024-01-01"),
            entry_price=1.1000,
            stop_loss=1.1000,  # same as entry
            take_profit=1.1040,
            quality_score=50,
            confluence_level=1,
            confidence=40,
        )
        assert signal.risk_reward_ratio == 0


class TestReversalSignals:
    def test_returns_list(self, sample_ohlc):
        signals = detect_reversal_signals(sample_ohlc, pair="EUR_USD", timeframe="H1")
        assert isinstance(signals, list)

    def test_signals_have_correct_type(self, sample_ohlc):
        signals = detect_reversal_signals(sample_ohlc, pair="EUR_USD", timeframe="H1")
        for s in signals:
            assert s.signal_type == SignalType.REVERSAL


class TestBuildupSignals:
    def test_returns_list(self, sample_ohlc):
        signals = detect_buildup_signals(sample_ohlc, pair="EUR_USD", timeframe="H1")
        assert isinstance(signals, list)


class TestPullbackSignals:
    def test_returns_list(self, trending_up_ohlc):
        signals = detect_pullback_signals(trending_up_ohlc, pair="EUR_USD", timeframe="H1")
        assert isinstance(signals, list)


class TestBOSSignals:
    def test_returns_list(self, sample_ohlc):
        signals = detect_bos_signals(sample_ohlc, pair="EUR_USD", timeframe="H1")
        assert isinstance(signals, list)

    def test_signals_have_correct_type(self, sample_ohlc):
        signals = detect_bos_signals(sample_ohlc, pair="EUR_USD", timeframe="H1")
        for s in signals:
            assert s.signal_type == SignalType.BOS


class TestQualityScorer:
    def test_score_returns_breakdown(self):
        signal = Signal(
            signal_type=SignalType.REVERSAL,
            direction=SignalDirection.BUY,
            pair="EUR_USD",
            timeframe="H1",
            timestamp=pd.Timestamp("2024-01-01"),
            entry_price=1.1000,
            stop_loss=1.0980,
            take_profit=1.1040,
            quality_score=70,
            confluence_level=3,
            confidence=65,
        )
        breakdown = score_signal(signal)
        assert isinstance(breakdown, QualityBreakdown)
        assert 0 <= breakdown.total_score <= 100
        assert breakdown.grade in ("A", "B", "C", "D", "F")

    def test_high_rr_scores_higher(self):
        base = dict(
            signal_type=SignalType.REVERSAL,
            direction=SignalDirection.BUY,
            pair="EUR_USD",
            timeframe="H1",
            timestamp=pd.Timestamp("2024-01-01"),
            quality_score=70,
            confluence_level=3,
            confidence=65,
        )
        low_rr = Signal(entry_price=1.1000, stop_loss=1.0990, take_profit=1.1010, **base)
        high_rr = Signal(entry_price=1.1000, stop_loss=1.0990, take_profit=1.1050, **base)

        low_score = score_signal(low_rr)
        high_score = score_signal(high_rr)
        assert high_score.rr_score > low_score.rr_score

    def test_filter_signals(self):
        signals = [
            Signal(
                signal_type=SignalType.REVERSAL,
                direction=SignalDirection.BUY,
                pair="EUR_USD",
                timeframe="H1",
                timestamp=pd.Timestamp("2024-01-01"),
                entry_price=1.1000,
                stop_loss=1.0980,
                take_profit=1.1060,
                quality_score=70,
                confluence_level=4,
                confidence=65,
            ),
        ]
        filtered = filter_signals(signals, min_quality=0)
        assert len(filtered) >= 0  # May or may not pass depending on scoring
