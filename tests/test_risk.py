"""Tests for risk management."""

import pytest
import pandas as pd
import numpy as np

from src.risk.position_sizer import calculate_position_size
from src.risk.stop_validator import validate_stop
from src.risk.daily_limits import DailyLimitTracker
from src.risk.drawdown_manager import DrawdownManager


class TestPositionSizer:
    def test_basic_sizing(self):
        result = calculate_position_size(
            account_balance=300, entry_price=1.1000,
            stop_loss=1.0950, risk_pct=0.01,
        )
        assert result["risk_amount"] == 3.0
        assert result["position_size"] > 0
        assert result["stop_pips"] == 50.0

    def test_zero_stop_distance(self):
        result = calculate_position_size(
            account_balance=300, entry_price=1.1000,
            stop_loss=1.1000, risk_pct=0.01,
        )
        assert result["position_size"] == 0

    def test_larger_account(self):
        small = calculate_position_size(300, 1.1, 1.095, 0.01)
        large = calculate_position_size(3000, 1.1, 1.095, 0.01)
        assert large["position_size"] > small["position_size"]

    def test_tighter_stop_larger_position(self):
        wide = calculate_position_size(300, 1.1, 1.09, 0.01)
        tight = calculate_position_size(300, 1.1, 1.095, 0.01)
        assert tight["position_size"] > wide["position_size"]


class TestStopValidator:
    def test_valid_buy_stop(self):
        result = validate_stop(1.1000, 1.0950, "buy")
        assert result["valid"] is True

    def test_invalid_buy_stop_above_entry(self):
        result = validate_stop(1.1000, 1.1050, "buy")
        assert result["valid"] is False

    def test_invalid_sell_stop_below_entry(self):
        result = validate_stop(1.1000, 1.0950, "sell")
        assert result["valid"] is False

    def test_stop_too_tight(self):
        result = validate_stop(1.1000, 1.09998, "buy", min_stop_pips=5)
        assert result["valid"] is False

    def test_stop_too_wide(self):
        result = validate_stop(1.1000, 1.0000, "buy", max_stop_pips=100)
        assert result["valid"] is False


class TestDailyLimits:
    def test_initial_state(self):
        tracker = DailyLimitTracker(account_balance=300)
        assert tracker.can_trade() is True
        assert tracker.remaining_risk > 0

    def test_locks_after_max_loss(self):
        tracker = DailyLimitTracker(account_balance=300, max_daily_loss_pct=0.10)
        tracker.record_trade(-30.0)  # 10% loss
        assert tracker.can_trade() is False
        assert tracker.is_locked is True

    def test_reset(self):
        tracker = DailyLimitTracker(account_balance=300)
        tracker.record_trade(-30.0)
        assert tracker.is_locked is True
        tracker.reset(new_balance=270)
        assert tracker.can_trade() is True
        assert tracker.daily_pnl == 0

    def test_partial_losses_ok(self):
        tracker = DailyLimitTracker(account_balance=300, max_daily_loss_pct=0.10)
        tracker.record_trade(-10.0)
        assert tracker.can_trade() is True
        tracker.record_trade(-10.0)
        assert tracker.can_trade() is True


class TestDrawdownManager:
    def test_no_drawdown(self):
        mgr = DrawdownManager(peak_balance=300, current_balance=300)
        assert mgr.drawdown_pct == 0.0
        assert mgr.risk_multiplier() == 1.0

    def test_moderate_drawdown(self):
        mgr = DrawdownManager(peak_balance=300, current_balance=275)
        assert mgr.drawdown_pct == pytest.approx(25 / 300)
        assert mgr.risk_multiplier() == 0.75

    def test_severe_drawdown(self):
        mgr = DrawdownManager(peak_balance=300, current_balance=230)
        assert mgr.risk_multiplier() == 0.25

    def test_consecutive_losses(self):
        mgr = DrawdownManager(peak_balance=300, current_balance=300)
        for _ in range(4):
            mgr.record_trade(-3.0)
        assert mgr.consecutive_losses == 4
        assert mgr.risk_multiplier() == 0.25

    def test_win_resets_consecutive(self):
        mgr = DrawdownManager(peak_balance=300, current_balance=290)
        mgr.record_trade(-3.0)
        mgr.record_trade(-3.0)
        assert mgr.consecutive_losses == 2
        mgr.record_trade(5.0)
        assert mgr.consecutive_losses == 0

    def test_new_peak(self):
        mgr = DrawdownManager(peak_balance=300, current_balance=300)
        mgr.record_trade(10.0)
        assert mgr.peak_balance == 310
        assert mgr.drawdown_pct == 0.0
