"""Tests for backtesting engine."""

import pytest
import pandas as pd
import numpy as np

from src.backtest.backtester import run_backtest, BacktestConfig, _check_exit, _close_trade, Trade
from src.backtest.metrics import calculate_metrics, BacktestMetrics
from src.backtest.optimizer import optimize
from src.backtest.reporter import format_report, trade_log
from src.signals.signal_base import Signal, SignalDirection, SignalType


# --- Fixtures ---

@pytest.fixture
def backtest_ohlc():
    """500-bar OHLC data with trends and ranges for meaningful backtest."""
    np.random.seed(42)
    n = 500
    dates = pd.date_range("2024-01-01", periods=n, freq="h")

    # Create data with regime changes: trend up, range, trend down, range
    trend = np.zeros(n)
    trend[:125] = np.linspace(0, 0.03, 125)
    trend[125:250] = 0.03 + np.sin(np.linspace(0, 4 * np.pi, 125)) * 0.003
    trend[250:375] = np.linspace(0.03, -0.01, 125)
    trend[375:] = -0.01 + np.sin(np.linspace(0, 4 * np.pi, 125)) * 0.003

    noise = np.random.randn(n) * 0.0008
    close = 1.1000 + trend + noise

    spread = np.abs(np.random.randn(n) * 0.0005)
    high = close + spread
    low = close - spread
    open_ = close + np.random.randn(n) * 0.0003
    high = np.maximum(high, np.maximum(open_, close))
    low = np.minimum(low, np.minimum(open_, close))

    return pd.DataFrame({
        "open": open_, "high": high, "low": low, "close": close,
        "volume": np.random.randint(100, 10000, n),
    }, index=dates)


@pytest.fixture
def sample_trades():
    """Sample trade dicts for metrics testing."""
    return [
        {"pnl": 10.0, "entry_bar": 0, "exit_bar": 5, "risk_amount": 3.0},
        {"pnl": -3.0, "entry_bar": 10, "exit_bar": 12, "risk_amount": 3.0},
        {"pnl": 8.0, "entry_bar": 20, "exit_bar": 28, "risk_amount": 3.0},
        {"pnl": -3.0, "entry_bar": 35, "exit_bar": 37, "risk_amount": 3.0},
        {"pnl": -3.0, "entry_bar": 40, "exit_bar": 42, "risk_amount": 3.0},
        {"pnl": 15.0, "entry_bar": 50, "exit_bar": 60, "risk_amount": 3.0},
    ]


@pytest.fixture
def sample_signal():
    return Signal(
        signal_type=SignalType.REVERSAL,
        direction=SignalDirection.BUY,
        pair="EUR_USD",
        timeframe="H1",
        timestamp=pd.Timestamp("2024-01-01"),
        entry_price=1.1000,
        stop_loss=1.0950,
        take_profit=1.1100,
        quality_score=70,
        confluence_level=2,
        confidence=65,
    )


# --- Metrics Tests ---

class TestMetrics:
    def test_calculate_metrics_basic(self, sample_trades):
        m = calculate_metrics(sample_trades, initial_balance=300)
        assert m.total_trades == 6
        assert m.winning_trades == 3
        assert m.losing_trades == 3
        assert m.win_rate == 0.5
        assert m.total_pnl == 24.0
        assert m.profit_factor > 1.0

    def test_calculate_metrics_empty(self):
        m = calculate_metrics([], initial_balance=300)
        assert m.total_trades == 0
        assert m.win_rate == 0
        assert m.total_pnl == 0

    def test_metrics_drawdown(self, sample_trades):
        m = calculate_metrics(sample_trades, initial_balance=300)
        assert m.max_drawdown_pct >= 0
        assert m.max_drawdown_amount >= 0

    def test_metrics_sharpe(self, sample_trades):
        m = calculate_metrics(sample_trades, initial_balance=300)
        assert isinstance(m.sharpe_ratio, float)

    def test_metrics_all_winners(self):
        trades = [{"pnl": 5.0, "entry_bar": i, "exit_bar": i + 3, "risk_amount": 2.0} for i in range(5)]
        m = calculate_metrics(trades, initial_balance=300)
        assert m.win_rate == 1.0
        assert m.losing_trades == 0
        assert m.profit_factor == float("inf")

    def test_metrics_all_losers(self):
        trades = [{"pnl": -3.0, "entry_bar": i, "exit_bar": i + 2, "risk_amount": 3.0} for i in range(5)]
        m = calculate_metrics(trades, initial_balance=300)
        assert m.win_rate == 0.0
        assert m.profit_factor == 0
        assert m.total_pnl == -15.0


# --- Trade Exit Tests ---

class TestTradeExit:
    def test_buy_stop_loss_hit(self, sample_signal):
        trade = Trade(signal=sample_signal, entry_bar=0, entry_price=1.1000, risk_amount=3.0, position_size=600)
        bar = pd.Series({"open": 1.0960, "high": 1.0970, "low": 1.0940, "close": 1.0955})
        exit_price, reason = _check_exit(trade, bar)
        assert exit_price == 1.0950
        assert reason == "stop_loss"

    def test_buy_take_profit_hit(self, sample_signal):
        trade = Trade(signal=sample_signal, entry_bar=0, entry_price=1.1000, risk_amount=3.0, position_size=600)
        bar = pd.Series({"open": 1.1090, "high": 1.1110, "low": 1.1085, "close": 1.1105})
        exit_price, reason = _check_exit(trade, bar)
        assert exit_price == 1.1100
        assert reason == "take_profit"

    def test_no_exit(self, sample_signal):
        trade = Trade(signal=sample_signal, entry_bar=0, entry_price=1.1000, risk_amount=3.0, position_size=600)
        bar = pd.Series({"open": 1.1010, "high": 1.1030, "low": 1.0960, "close": 1.1020})
        exit_price, reason = _check_exit(trade, bar)
        assert exit_price is None

    def test_close_trade_pnl_buy(self, sample_signal):
        trade = Trade(signal=sample_signal, entry_bar=0, entry_price=1.1000, risk_amount=3.0, position_size=1000)
        _close_trade(trade, 5, 1.1050, "take_profit")
        assert trade.pnl == pytest.approx(5.0)  # 0.0050 * 1000

    def test_close_trade_pnl_sell(self):
        signal = Signal(
            signal_type=SignalType.REVERSAL, direction=SignalDirection.SELL,
            pair="EUR_USD", timeframe="H1", timestamp=pd.Timestamp("2024-01-01"),
            entry_price=1.1000, stop_loss=1.1050, take_profit=1.0900,
            quality_score=70, confluence_level=2, confidence=65,
        )
        trade = Trade(signal=signal, entry_bar=0, entry_price=1.1000, risk_amount=3.0, position_size=1000)
        _close_trade(trade, 5, 1.0950, "take_profit")
        assert trade.pnl == pytest.approx(5.0)  # (1.1000 - 1.0950) * 1000


# --- Backtester Integration Tests ---

class TestBacktester:
    def test_run_backtest_returns_structure(self, backtest_ohlc):
        result = run_backtest(backtest_ohlc, config=BacktestConfig(min_quality_score=0))
        assert "trades" in result
        assert "metrics" in result
        assert "equity_curve" in result
        assert "config" in result
        assert isinstance(result["metrics"], BacktestMetrics)

    def test_backtest_equity_curve_length(self, backtest_ohlc):
        config = BacktestConfig(warmup_bars=50, min_quality_score=0)
        result = run_backtest(backtest_ohlc, config=config)
        # equity_curve has one entry per bar after warmup + initial + final
        assert len(result["equity_curve"]) > 0

    def test_backtest_config_defaults(self):
        config = BacktestConfig()
        assert config.initial_balance == 300.0
        assert config.risk_per_trade == 0.01
        assert config.max_open_trades == 3

    def test_backtest_no_trades_on_short_data(self):
        """Backtest on data shorter than warmup should produce no trades."""
        np.random.seed(42)
        df = pd.DataFrame({
            "open": [1.1] * 10, "high": [1.101] * 10,
            "low": [1.099] * 10, "close": [1.1] * 10,
            "volume": [100] * 10,
        }, index=pd.date_range("2024-01-01", periods=10, freq="h"))

        result = run_backtest(df, config=BacktestConfig(warmup_bars=50))
        assert result["metrics"].total_trades == 0

    def test_backtest_respects_quality_filter(self, backtest_ohlc):
        # Very high quality threshold = fewer or no trades
        config_high = BacktestConfig(min_quality_score=99)
        result_high = run_backtest(backtest_ohlc, config=config_high)

        config_low = BacktestConfig(min_quality_score=0)
        result_low = run_backtest(backtest_ohlc, config=config_low)

        assert result_high["metrics"].total_trades <= result_low["metrics"].total_trades


# --- Reporter Tests ---

class TestReporter:
    def test_format_report(self, sample_trades):
        metrics = calculate_metrics(sample_trades, 300)
        config = {"pair": "EUR_USD", "timeframe": "H1", "total_bars": 500, "initial_balance": 300, "signal_types": ["reversal"]}
        report = format_report(metrics, config)
        assert "BACKTEST REPORT" in report
        assert "EUR_USD" in report
        assert "Win" in report

    def test_trade_log(self):
        trades = [{
            "signal_type": "reversal", "direction": "buy",
            "entry_price": 1.1000, "exit_price": 1.1050,
            "pnl": 5.0, "exit_reason": "take_profit",
        }]
        log = trade_log(trades)
        assert "reversal" in log
        assert "take_profit" in log

    def test_trade_log_empty(self):
        assert trade_log([]) == "No trades."


# --- Optimizer Tests ---

class TestOptimizer:
    def test_optimize_returns_results(self, backtest_ohlc):
        param_grid = {
            "min_quality_score": [0, 50],
            "min_rr": [1.5, 2.0],
        }
        results = optimize(backtest_ohlc, param_grid=param_grid, top_n=3)
        assert isinstance(results, list)
        assert len(results) <= 3
        # Results should be sorted by score descending
        if len(results) >= 2:
            assert results[0].score >= results[1].score
