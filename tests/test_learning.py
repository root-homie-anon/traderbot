"""Tests for adaptive learning system."""

import pytest
import tempfile
import os

from src.learning.performance_tracker import PerformanceTracker, SetupStats
from src.learning.adaptive_engine import AdaptiveEngine
from src.learning.self_corrector import SelfCorrector, ActionType
from src.learning.pair_selector import PairSelector


def _make_trade(pair="EUR_USD", signal_type="reversal", timeframe="H1",
                direction="buy", pnl=1.0, risk_amount=1.0,
                exit_reason="take_profit"):
    return {
        "timestamp": "2026-01-01T00:00:00",
        "pair": pair,
        "signal_type": signal_type,
        "timeframe": timeframe,
        "direction": direction,
        "entry_price": 1.1000,
        "exit_price": 1.1020 if pnl > 0 else 1.0980,
        "stop_loss": 1.0980,
        "take_profit": 1.1040,
        "pnl": pnl,
        "risk_amount": risk_amount,
        "exit_reason": exit_reason,
        "quality_score": 65,
        "confluence_level": 3,
    }


@pytest.fixture
def tracker(tmp_path):
    db = tmp_path / "test_perf.db"
    return PerformanceTracker(db_path=db)


@pytest.fixture
def loaded_tracker(tracker):
    """Tracker with 20 trades: 13 wins, 7 losses (65% WR) on EUR_USD reversal.

    Interleaved to avoid triggering consecutive loss detection.
    Ends on wins so recency-weighted WR stays above STRONG_WIN_RATE (0.60).
    """
    # 13 wins (2.0) and 7 losses (-1.0), interleaved
    # L W W L W W L W W L W W L W W L W W W W
    pattern = [-1.0, 2.0, 2.0, -1.0, 2.0, 2.0, -1.0, 2.0, 2.0, -1.0,
               2.0, 2.0, -1.0, 2.0, 2.0, -1.0, 2.0, 2.0, -1.0, 2.0]
    trades = []
    for pnl in pattern:
        reason = "take_profit" if pnl > 0 else "stop_loss"
        trades.append(_make_trade(pnl=pnl, risk_amount=1.0, exit_reason=reason))
    tracker.record_trades(trades)
    return tracker


# ──────────────────── PerformanceTracker ────────────────────


class TestPerformanceTracker:

    def test_record_and_get_stats(self, tracker):
        tracker.record_trade(_make_trade(pnl=5.0))
        tracker.record_trade(_make_trade(pnl=-2.0, exit_reason="stop_loss"))
        stats = tracker.get_stats()
        assert stats.total_trades == 2
        assert stats.wins == 1
        assert stats.losses == 1
        assert stats.total_pnl == pytest.approx(3.0)
        assert stats.win_rate == pytest.approx(0.5)

    def test_filter_by_pair(self, tracker):
        tracker.record_trade(_make_trade(pair="EUR_USD", pnl=1.0))
        tracker.record_trade(_make_trade(pair="GBP_USD", pnl=-1.0))
        eur = tracker.get_stats(pair="EUR_USD")
        gbp = tracker.get_stats(pair="GBP_USD")
        assert eur.total_trades == 1
        assert eur.wins == 1
        assert gbp.total_trades == 1
        assert gbp.losses == 1

    def test_filter_by_signal_type(self, tracker):
        tracker.record_trade(_make_trade(signal_type="reversal", pnl=1.0))
        tracker.record_trade(_make_trade(signal_type="pullback", pnl=-1.0))
        rev = tracker.get_stats(signal_type="reversal")
        pull = tracker.get_stats(signal_type="pullback")
        assert rev.wins == 1
        assert pull.losses == 1

    def test_filter_by_source(self, tracker):
        tracker.record_trade(_make_trade(pnl=1.0), source="backtest")
        tracker.record_trade(_make_trade(pnl=-1.0), source="paper")
        bt = tracker.get_stats(source="backtest")
        paper = tracker.get_stats(source="paper")
        assert bt.total_trades == 1
        assert paper.total_trades == 1

    def test_last_n(self, tracker):
        for i in range(10):
            tracker.record_trade(_make_trade(pnl=1.0))
        for i in range(5):
            tracker.record_trade(_make_trade(pnl=-1.0, exit_reason="stop_loss"))
        recent = tracker.get_stats(last_n=5)
        assert recent.total_trades == 5
        assert recent.losses == 5

    def test_get_win_rate(self, loaded_tracker):
        wr = loaded_tracker.get_win_rate()
        assert wr == pytest.approx(0.65)

    def test_get_all_pairs(self, tracker):
        tracker.record_trade(_make_trade(pair="EUR_USD"))
        tracker.record_trade(_make_trade(pair="GBP_USD"))
        pairs = tracker.get_all_pairs()
        assert set(pairs) == {"EUR_USD", "GBP_USD"}

    def test_pair_rankings(self, tracker):
        for _ in range(10):
            tracker.record_trade(_make_trade(pair="EUR_USD", pnl=2.0))
        for _ in range(10):
            tracker.record_trade(_make_trade(pair="GBP_USD", pnl=-1.0, exit_reason="stop_loss"))
        rankings = tracker.get_pair_rankings(min_trades=5)
        assert len(rankings) == 2
        assert rankings[0].pair == "EUR_USD"
        assert rankings[1].pair == "GBP_USD"

    def test_clear(self, loaded_tracker):
        loaded_tracker.clear()
        stats = loaded_tracker.get_stats()
        assert stats.total_trades == 0

    def test_clear_by_source(self, tracker):
        tracker.record_trade(_make_trade(pnl=1.0), source="backtest")
        tracker.record_trade(_make_trade(pnl=1.0), source="paper")
        tracker.clear(source="backtest")
        stats = tracker.get_stats()
        assert stats.total_trades == 1

    def test_stats_properties(self, tracker):
        tracker.record_trade(_make_trade(pnl=3.0, risk_amount=1.0))
        tracker.record_trade(_make_trade(pnl=-1.0, risk_amount=1.0, exit_reason="stop_loss"))
        stats = tracker.get_stats()
        assert stats.profit_factor == pytest.approx(3.0)
        assert stats.expectancy == pytest.approx(1.0)
        assert stats.avg_r == pytest.approx(1.0)

    def test_empty_stats(self, tracker):
        stats = tracker.get_stats()
        assert stats.total_trades == 0
        assert stats.win_rate == 0.0
        assert stats.expectancy == 0.0
        assert stats.profit_factor == 0.0
        assert stats.avg_r == 0.0


# ──────────────────── AdaptiveEngine ────────────────────


class TestAdaptiveEngine:

    def test_neutral_with_no_data(self, tracker):
        engine = AdaptiveEngine(tracker)
        adj = engine.get_adjustment("reversal")
        assert adj.multiplier == pytest.approx(1.0)
        assert adj.reason == "insufficient data"

    def test_boost_strong_performer(self, loaded_tracker):
        engine = AdaptiveEngine(loaded_tracker, min_trades=5)
        adj = engine.get_adjustment("reversal")
        assert adj.multiplier > 1.0
        assert "strong" in adj.reason

    def test_penalty_weak_performer(self, tracker):
        for _ in range(20):
            tracker.record_trade(
                _make_trade(signal_type="bos", pnl=-1.0, exit_reason="stop_loss")
            )
        for _ in range(5):
            tracker.record_trade(
                _make_trade(signal_type="bos", pnl=1.0)
            )
        engine = AdaptiveEngine(tracker, min_trades=10)
        adj = engine.get_adjustment("bos")
        assert adj.multiplier < 1.0
        assert "weak" in adj.reason

    def test_cache(self, loaded_tracker):
        engine = AdaptiveEngine(loaded_tracker, min_trades=5)
        adj1 = engine.get_adjustment("reversal")
        adj2 = engine.get_adjustment("reversal")
        assert adj1 is adj2

    def test_clear_cache(self, loaded_tracker):
        engine = AdaptiveEngine(loaded_tracker, min_trades=5)
        engine.get_adjustment("reversal")
        engine.clear_cache()
        assert len(engine._cache) == 0

    def test_get_all_adjustments(self, loaded_tracker):
        engine = AdaptiveEngine(loaded_tracker, min_trades=5)
        adjs = engine.get_all_adjustments()
        assert len(adjs) > 0

    def test_confidence_blending(self, tracker):
        # With exactly min_trades, confidence should be partial
        for _ in range(10):
            tracker.record_trade(_make_trade(pnl=2.0))
        engine = AdaptiveEngine(tracker, min_trades=10)
        adj = engine.get_adjustment("reversal")
        # multiplier should be between 1.0 and full boost
        assert 1.0 <= adj.multiplier <= 1.25


# ──────────────────── SelfCorrector ────────────────────


class TestSelfCorrector:

    def test_no_corrections_with_good_performance(self, loaded_tracker):
        corrector = SelfCorrector(loaded_tracker, min_trades=10)
        corrections = corrector.evaluate()
        # 60% WR should not trigger anything
        assert len(corrections) == 0

    def test_disable_bad_signal_type(self, tracker):
        for _ in range(20):
            tracker.record_trade(
                _make_trade(signal_type="buildup", pnl=-1.0, exit_reason="stop_loss")
            )
        for _ in range(3):
            tracker.record_trade(
                _make_trade(signal_type="buildup", pnl=1.0)
            )
        corrector = SelfCorrector(tracker, min_trades=15)
        corrections = corrector.evaluate(signal_types=["buildup"])
        actions = [c.action for c in corrections]
        assert ActionType.DISABLE_SIGNAL in actions

    def test_warn_marginal_signal_type(self, tracker):
        # 35% win rate -> warning
        for _ in range(13):
            tracker.record_trade(
                _make_trade(signal_type="pullback", pnl=-1.0, exit_reason="stop_loss")
            )
        for _ in range(7):
            tracker.record_trade(
                _make_trade(signal_type="pullback", pnl=1.0)
            )
        corrector = SelfCorrector(tracker, min_trades=15)
        corrections = corrector.evaluate(signal_types=["pullback"])
        actions = [c.action for c in corrections]
        assert ActionType.RAISE_QUALITY_MIN in actions

    def test_remove_bad_pair(self, tracker):
        # 20% win rate on a pair
        for _ in range(20):
            tracker.record_trade(
                _make_trade(pair="USD_CAD", pnl=-1.0, exit_reason="stop_loss")
            )
        for _ in range(4):
            tracker.record_trade(
                _make_trade(pair="USD_CAD", pnl=1.0)
            )
        corrector = SelfCorrector(tracker, min_trades=15)
        corrections = corrector.evaluate(pairs=["USD_CAD"], signal_types=[])
        actions = [c.action for c in corrections]
        assert ActionType.REMOVE_PAIR in actions

    def test_apply_disable(self, tracker):
        corrector = SelfCorrector(tracker)
        from src.learning.self_corrector import Correction
        c = Correction(
            action=ActionType.DISABLE_SIGNAL,
            target="bos",
            detail="test",
            severity="critical",
        )
        corrector.apply_correction(c)
        assert not corrector.is_signal_enabled("bos")

    def test_re_enable(self, tracker):
        corrector = SelfCorrector(tracker, disabled_signals={"bos"})
        assert not corrector.is_signal_enabled("bos")
        from src.learning.self_corrector import Correction
        c = Correction(
            action=ActionType.RE_ENABLE_SIGNAL,
            target="bos",
            detail="recovered",
        )
        corrector.apply_correction(c)
        assert corrector.is_signal_enabled("bos")

    def test_re_enable_when_recovered(self, tracker):
        # Disabled, then performance recovers
        for _ in range(10):
            tracker.record_trade(
                _make_trade(signal_type="bos", pnl=2.0)
            )
        for _ in range(5):
            tracker.record_trade(
                _make_trade(signal_type="bos", pnl=-1.0, exit_reason="stop_loss")
            )
        corrector = SelfCorrector(tracker, min_trades=10, disabled_signals={"bos"})
        corrections = corrector.evaluate(signal_types=["bos"])
        actions = [c.action for c in corrections]
        assert ActionType.RE_ENABLE_SIGNAL in actions


# ──────────────────── PairSelector ────────────────────


class TestPairSelector:

    def test_defaults_when_no_data(self, tracker):
        selector = PairSelector(tracker, max_pairs=3)
        pairs = selector.select()
        assert len(pairs) == 3
        assert pairs == ["EUR_USD", "GBP_USD", "USD_JPY"]

    def test_selects_top_pairs(self, tracker):
        # EUR_USD good, GBP_USD bad, USD_JPY medium
        for _ in range(10):
            tracker.record_trade(_make_trade(pair="EUR_USD", pnl=3.0))
        for _ in range(10):
            tracker.record_trade(_make_trade(pair="GBP_USD", pnl=-1.0, exit_reason="stop_loss"))
        for _ in range(10):
            tracker.record_trade(_make_trade(pair="USD_JPY", pnl=1.0))
        selector = PairSelector(tracker, max_pairs=2, min_trades=5)
        pairs = selector.select()
        assert "EUR_USD" in pairs
        assert "GBP_USD" not in pairs  # bad win rate

    def test_rank_order(self, tracker):
        for _ in range(10):
            tracker.record_trade(_make_trade(pair="EUR_USD", pnl=5.0))
        for _ in range(10):
            tracker.record_trade(_make_trade(pair="AUD_USD", pnl=2.0))
        selector = PairSelector(tracker, max_pairs=5, min_trades=5)
        rankings = selector.rank()
        assert rankings[0].pair == "EUR_USD"
        assert rankings[1].pair == "AUD_USD"
        assert rankings[0].selected
        assert rankings[1].selected

    def test_min_win_rate_filter(self, tracker):
        for _ in range(7):
            tracker.record_trade(
                _make_trade(pair="EUR_USD", pnl=-1.0, exit_reason="stop_loss")
            )
        for _ in range(3):
            tracker.record_trade(_make_trade(pair="EUR_USD", pnl=1.0))
        selector = PairSelector(tracker, max_pairs=5, min_trades=5, min_win_rate=0.35)
        pairs = selector.select()
        # 30% WR < 35% min -> falls back to defaults
        assert pairs == ["EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "EUR_GBP"]
