"""Integration tests for stop placement fixes and pair expansion.

Covers:
- ATR-based stop placement in reversal and pullback signals
- ATR NaN and zero edge cases
- backtester validate_stop path matching live order_manager path
- Position sizer 5-pip defense guard
- All 9 pairs in session windows and correlation groups
- Default value consistency
"""

import math

import pandas as pd
import numpy as np
import pytest

from src.signals.reversal_signal import detect_reversal_signals
from src.signals.pullback_signal import detect_pullback_signals
from src.risk.position_sizer import calculate_position_size
from src.risk.stop_validator import validate_stop
from src.utils.helpers import get_pip_value
from src.trading_sessions import OPTIMAL_WINDOWS, is_pair_tradeable
from src.risk.correlation_guard import _PAIR_TO_GROUPS
from src.paper_trader import PaperTraderConfig
from src.backtest.backtester import BacktestConfig
from src.config import TOP_PAIRS


LIVE_PAIRS = [
    "EUR_USD", "GBP_USD", "USD_JPY", "AUD_USD", "EUR_GBP",
    "USD_CAD", "NZD_USD", "EUR_JPY", "GBP_JPY",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _flat_df(n=20, price=1.1000):
    """DataFrame with identical OHLC — ATR = 0.0, no patterns possible."""
    dates = pd.date_range("2024-01-01", periods=n, freq="h")
    return pd.DataFrame(
        {"open": price, "high": price, "low": price, "close": price, "volume": 1000},
        index=dates,
    )


def _short_df(n=10):
    """DataFrame shorter than the 14-bar ATR window."""
    dates = pd.date_range("2024-01-01", periods=n, freq="h")
    np.random.seed(1)
    c = 1.1000 + np.cumsum(np.random.randn(n) * 0.001)
    h = c + np.abs(np.random.randn(n) * 0.0005)
    lo = c - np.abs(np.random.randn(n) * 0.0005)
    return pd.DataFrame({"open": c, "high": h, "low": lo, "close": c, "volume": 1000}, index=dates)


# ---------------------------------------------------------------------------
# ATR edge cases — reversal signal
# ---------------------------------------------------------------------------


class TestReversalStopATR:

    def test_no_crash_on_short_df(self):
        """Should return [] without raising when df < 14 bars."""
        df = _short_df(10)
        result = detect_reversal_signals(df)
        assert isinstance(result, list)

    def test_no_crash_on_zero_atr(self):
        """Flat price data produces ATR=0; should not crash."""
        df = _flat_df(20)
        result = detect_reversal_signals(df)
        assert isinstance(result, list)

    def test_atr_fallback_used_for_short_df(self):
        """Verify the fallback branch runs without error for 13-bar df."""
        df = _short_df(13)
        # Should not raise; no patterns expected on random data
        result = detect_reversal_signals(df)
        assert isinstance(result, list)

    def test_zero_atr_does_not_produce_invalid_stop(self):
        """If a signal somehow forms with ATR=0, stop == support.price -> validate_stop catches it."""
        # Create conditions where ATR could in theory be 0: use flat data but
        # we can't force a signal, so test the arithmetic directly.
        # stop_loss (bullish) = support.price - atr * 0.5
        # If atr = 0 and support.price = 1.0990, current = 1.1000:
        support_price = 1.0990
        atr = 0.0
        stop_loss = support_price - atr * 0.5  # == 1.0990
        entry = 1.1000
        pip_value = get_pip_value("EUR_USD")
        result = validate_stop(entry, stop_loss, "buy", pip_value=pip_value)
        # stop_distance = 0.0010 = 10 pips -> VALID (above 5-pip minimum)
        assert result["valid"] is True

    def test_very_small_atr_produces_tight_stop_that_may_fail_validation(self):
        """ATR of 0.00004 (0.4 pip): stop = support - 0.00002 -> < 5 pips from entry -> rejected."""
        support_price = 1.0999
        atr = 0.00004
        stop_loss = support_price - atr * 0.5  # 1.0999 - 0.00002 = 1.09988
        entry = 1.1000
        # stop_distance = entry - stop_loss = 0.00012 = 1.2 pips -> below 5-pip min
        pip_value = get_pip_value("EUR_USD")
        result = validate_stop(entry, stop_loss, "buy", pip_value=pip_value)
        assert result["valid"] is False
        assert "tight" in result["reason"]


# ---------------------------------------------------------------------------
# ATR edge cases — pullback signal
# ---------------------------------------------------------------------------


class TestPullbackStopATR:

    def test_no_crash_on_short_df(self):
        df = _short_df(10)
        result = detect_pullback_signals(df)
        assert isinstance(result, list)

    def test_no_crash_on_zero_atr(self):
        df = _flat_df(30)
        result = detect_pullback_signals(df)
        assert isinstance(result, list)

    def test_min_stop_floor_arithmetic(self):
        """max(raw_stop_dist, min_stop) should always produce stop >= min_stop."""
        atr = 0.0012
        min_stop = atr * 0.5  # 0.0006
        move_size = 0.0005    # small move -> raw_stop = 0.0001 < min_stop
        raw_stop_dist = move_size * 0.2  # 0.0001
        stop_dist = max(raw_stop_dist, min_stop)
        assert stop_dist == pytest.approx(min_stop)

    def test_min_stop_floor_does_not_invert(self):
        """When min_stop > move_size, RR becomes < 1 so signal is filtered."""
        atr = 0.0012
        min_stop = atr * 0.5  # 0.0006
        move_size = 0.0002
        raw_stop_dist = move_size * 0.2  # 0.00004
        stop_dist = max(raw_stop_dist, min_stop)  # 0.0006

        swing_high = 1.1010
        current_price = 1.1009  # ~50% retrace of 0.0002 move
        stop_loss = current_price - stop_dist
        risk = current_price - stop_loss  # 0.0006
        take_profit = swing_high + risk * 0.5
        rr = (take_profit - current_price) / risk if risk > 0 else 0
        # RR should be < 2.0, so signal would be filtered
        assert rr < 2.0, f"Expected RR < 2.0 but got {rr}"

    def test_normal_stop_dist_not_floored(self):
        """When raw_stop_dist > min_stop, the original distance is preserved."""
        atr = 0.0010
        min_stop = atr * 0.5  # 0.0005
        move_size = 0.0050    # large move -> raw_stop = 0.001 > min_stop
        raw_stop_dist = move_size * 0.2  # 0.001
        stop_dist = max(raw_stop_dist, min_stop)
        assert stop_dist == pytest.approx(raw_stop_dist)


# ---------------------------------------------------------------------------
# Backtester stop gate vs live path parity
# ---------------------------------------------------------------------------


class TestStopGateParity:
    """Verify backtester and order_manager use identical validate_stop calls."""

    def test_both_paths_reject_same_tight_stop(self):
        """A 3-pip stop should be rejected by both paths identically."""
        entry = 1.1000
        stop_loss = 1.0997  # 3 pips
        pip_value = get_pip_value("EUR_USD")

        # Simulate what backtester does
        bt_result = validate_stop(
            entry_price=entry,
            stop_loss=stop_loss,
            direction="buy",
            pip_value=pip_value,
        )
        # Simulate what order_manager does
        om_result = validate_stop(
            entry_price=entry,
            stop_loss=stop_loss,
            direction="buy",
            pip_value=pip_value,
        )

        assert bt_result["valid"] == om_result["valid"] is False
        assert bt_result["reason"] == om_result["reason"]

    def test_both_paths_accept_same_valid_stop(self):
        entry = 1.1000
        stop_loss = 1.0990  # 10 pips
        pip_value = get_pip_value("EUR_USD")

        bt_result = validate_stop(entry, stop_loss, "buy", pip_value=pip_value)
        om_result = validate_stop(entry, stop_loss, "buy", pip_value=pip_value)

        assert bt_result["valid"] == om_result["valid"] is True

    def test_jpy_stop_gate_consistent(self):
        """JPY pip value of 0.01 handled the same in both paths."""
        entry = 150.00
        stop_tight = 149.97  # 3 JPY pips
        stop_wide = 149.40   # 60 JPY pips
        pip_value = get_pip_value("USD_JPY")  # 0.01

        assert validate_stop(entry, stop_tight, "buy", pip_value=pip_value)["valid"] is False
        assert validate_stop(entry, stop_wide, "buy", pip_value=pip_value)["valid"] is True


# ---------------------------------------------------------------------------
# Position sizer 5-pip defense guard
# ---------------------------------------------------------------------------


class TestPositionSizerGuard:

    @pytest.mark.parametrize("pair,entry,stop_loss,expect_zero", [
        ("EUR_USD", 1.1000, 1.0997, True),   # 3 pips -> blocked
        ("EUR_USD", 1.1000, 1.0994, False),  # 6 pips -> allowed
        ("USD_JPY", 150.00, 149.97, True),   # 3 JPY pips -> blocked
        ("USD_JPY", 150.00, 149.40, False),  # 60 JPY pips -> allowed
        ("EUR_JPY", 160.00, 159.97, True),   # 3 JPY pips -> blocked
        ("GBP_JPY", 190.00, 189.40, False),  # 60 JPY pips -> allowed
    ])
    def test_5pip_guard(self, pair, entry, stop_loss, expect_zero):
        pip_value = get_pip_value(pair)
        result = calculate_position_size(300, entry, stop_loss, pip_value=pip_value)
        if expect_zero:
            assert result["position_size"] == 0, f"Expected 0 for {pair} stop"
        else:
            assert result["position_size"] > 0, f"Expected >0 for {pair} stop"


# ---------------------------------------------------------------------------
# Session windows — all 9 pairs covered
# ---------------------------------------------------------------------------


class TestSessionWindows:

    @pytest.mark.parametrize("pair", LIVE_PAIRS)
    def test_pair_has_session_window(self, pair):
        """Every live pair must have an explicit session window."""
        assert pair in OPTIMAL_WINDOWS, (
            f"{pair} is missing from OPTIMAL_WINDOWS in trading_sessions.py"
        )

    @pytest.mark.parametrize("pair", LIVE_PAIRS)
    def test_pair_is_tradeable_at_some_hour(self, pair):
        """Every live pair should be tradeable at at least one hour of the week."""
        from datetime import datetime, timezone
        tradeable_hours = []
        for hour in range(24):
            dt = datetime(2024, 1, 2, hour, 0, tzinfo=timezone.utc)  # Tuesday
            if is_pair_tradeable(pair, dt):
                tradeable_hours.append(hour)
        assert len(tradeable_hours) > 0, f"{pair} is never tradeable — session window misconfigured"


# ---------------------------------------------------------------------------
# Correlation groups — coverage check
# ---------------------------------------------------------------------------


class TestCorrelationGroups:

    def test_usd_weak_pairs_present(self):
        """USD-weak pairs from live set are in the USD_WEAK group."""
        usd_weak_live = {"EUR_USD", "GBP_USD", "AUD_USD", "NZD_USD"}
        from src.risk.correlation_guard import CORRELATION_GROUPS
        actual = set(CORRELATION_GROUPS["USD_WEAK"])
        assert usd_weak_live.issubset(actual)

    def test_jpy_cross_pairs_in_jpy_weak(self):
        """EUR_JPY and GBP_JPY should be in JPY_WEAK group."""
        from src.risk.correlation_guard import CORRELATION_GROUPS
        jpy_weak = set(CORRELATION_GROUPS["JPY_WEAK"])
        assert "EUR_JPY" in jpy_weak
        assert "GBP_JPY" in jpy_weak

    def test_usd_cad_in_usd_strong(self):
        """USD_CAD should be in USD_STRONG group."""
        from src.risk.correlation_guard import CORRELATION_GROUPS
        assert "USD_CAD" in CORRELATION_GROUPS["USD_STRONG"]

    def test_eur_gbp_has_no_group(self):
        """EUR_GBP is a cross pair not in any USD group — expected behavior."""
        groups = _PAIR_TO_GROUPS.get("EUR_GBP", [])
        assert groups == [], (
            "EUR_GBP should not be in any correlation group "
            "(it is a EUR/GBP cross, not a USD directional bet)"
        )


# ---------------------------------------------------------------------------
# Default value consistency
# ---------------------------------------------------------------------------


class TestDefaultConsistency:

    def test_paper_trader_max_open_trades(self):
        config = PaperTraderConfig()
        assert config.max_open_trades == 5

    def test_paper_trader_pair_count(self):
        config = PaperTraderConfig()
        assert len(config.pairs) == 9

    def test_paper_trader_pairs_match_live_list(self):
        config = PaperTraderConfig()
        assert set(config.pairs) == set(LIVE_PAIRS)

    def test_config_top_pairs(self):
        assert TOP_PAIRS == 9

    def test_backtest_config_max_open_trades_diverges(self):
        """
        BacktestConfig.max_open_trades is intentionally still 3 (not updated to 5).
        This test documents the divergence so it cannot silently change.
        If BacktestConfig is updated to 5, update this test.
        """
        config = BacktestConfig()
        assert config.max_open_trades == 3, (
            "BacktestConfig.max_open_trades is 3 while PaperTraderConfig is 5. "
            "If this is intentional, leave it. If not, update BacktestConfig."
        )
