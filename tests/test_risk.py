"""Tests for risk management."""

import pytest
import pandas as pd
import numpy as np

from src.risk.position_sizer import calculate_position_size, quote_to_account_rate
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


class TestQuoteToAccountRate:
    def test_usd_quoted_pair_returns_one(self):
        assert quote_to_account_rate("EUR_USD", 1.10) == 1.0
        assert quote_to_account_rate("GBP_USD", 1.27) == 1.0
        assert quote_to_account_rate("AUD_USD", 0.65) == 1.0

    def test_usd_base_pair_returns_inverse_price(self):
        assert quote_to_account_rate("USD_JPY", 159.0) == pytest.approx(1 / 159.0)
        assert quote_to_account_rate("USD_CAD", 1.367) == pytest.approx(1 / 1.367)

    def test_cross_pair_returns_none(self):
        assert quote_to_account_rate("EUR_GBP", 0.86) is None
        assert quote_to_account_rate("EUR_JPY", 170.0) is None
        assert quote_to_account_rate("GBP_JPY", 200.0) is None

    def test_malformed_pair_raises(self):
        with pytest.raises(ValueError):
            quote_to_account_rate("EURUSD", 1.10)

    def test_zero_entry_price_raises_for_usd_base(self):
        with pytest.raises(ValueError):
            quote_to_account_rate("USD_JPY", 0)


class TestPositionSizingAcrossPairs:
    """Verify the size produced gives the intended dollar risk on a stop-out."""

    def _expected_loss_in_account(self, size: int, stop_distance: float, rate: float) -> float:
        return size * stop_distance * rate

    def test_eur_usd_unchanged_behavior(self):
        """USD-quoted: rate=1.0, formula reduces to old behavior."""
        result = calculate_position_size(
            account_balance=80_000, entry_price=1.10, stop_loss=1.0950,
            risk_pct=0.02, quote_to_account_rate=1.0,
        )
        loss = self._expected_loss_in_account(
            result["position_size"], 0.005, 1.0,
        )
        assert loss == pytest.approx(1600, rel=0.001)

    def test_usd_jpy_sizes_correctly(self):
        """USD/JPY at 159, 10-pip stop, 2% of $80k account → expect ~$1600 loss on stop."""
        rate = quote_to_account_rate("USD_JPY", 159.0)
        result = calculate_position_size(
            account_balance=80_000, entry_price=159.0, stop_loss=159.10,
            risk_pct=0.02, pip_value=0.01, quote_to_account_rate=rate,
        )
        loss = self._expected_loss_in_account(result["position_size"], 0.10, rate)
        assert loss == pytest.approx(1600, rel=0.001)

    def test_usd_cad_sizes_correctly(self):
        """USD/CAD at 1.367, ~9.4 pip stop → 2% of $80k → expect ~$1600 loss on stop."""
        rate = quote_to_account_rate("USD_CAD", 1.367)
        stop_distance = 0.000940
        result = calculate_position_size(
            account_balance=80_000, entry_price=1.36657,
            stop_loss=1.36657 + stop_distance,
            risk_pct=0.02, pip_value=0.0001, quote_to_account_rate=rate,
        )
        loss = self._expected_loss_in_account(
            result["position_size"], stop_distance, rate,
        )
        assert loss == pytest.approx(1600, rel=0.005)

    def test_eur_jpy_with_external_rate(self):
        """Cross pair: caller supplies USD_JPY-derived rate."""
        # USD_JPY mid = 159.0 → JPY→USD rate = 1/159
        external_rate = 1 / 159.0
        result = calculate_position_size(
            account_balance=80_000, entry_price=170.0, stop_loss=170.20,
            risk_pct=0.02, pip_value=0.01, quote_to_account_rate=external_rate,
        )
        loss = self._expected_loss_in_account(
            result["position_size"], 0.20, external_rate,
        )
        assert loss == pytest.approx(1600, rel=0.001)

    def test_jpy_pair_old_formula_undersized_by_price_factor(self):
        """Regression guard: confirm the old buggy formula was off by ~entry_price."""
        rate = quote_to_account_rate("USD_JPY", 159.0)
        new_result = calculate_position_size(
            account_balance=80_000, entry_price=159.0, stop_loss=159.10,
            risk_pct=0.02, pip_value=0.01, quote_to_account_rate=rate,
        )
        # Old formula = rate=1.0 (assumed quote = account)
        old_result = calculate_position_size(
            account_balance=80_000, entry_price=159.0, stop_loss=159.10,
            risk_pct=0.02, pip_value=0.01, quote_to_account_rate=1.0,
        )
        ratio = new_result["position_size"] / old_result["position_size"]
        assert ratio == pytest.approx(159.0, rel=0.001)


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
        # 23.3% drawdown triggers hard halt (0.0 position size)
        assert mgr.risk_multiplier() == 0.0

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
