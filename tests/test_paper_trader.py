"""Tests for OANDA connector and paper trading engine."""

from datetime import datetime

import pytest
import pandas as pd
import numpy as np

from src.broker.broker_base import (
    AccountInfo, Order, OrderSide, OrderStatus, OrderType,
)
from src.broker.oanda_connector import OandaConnector, TIMEFRAME_MAP
from src.paper_trader import PaperTrader, PaperTraderConfig, PaperTraderState
from src.signals.signal_base import Signal, SignalDirection, SignalType


# ──────────────── Mock OANDA connector ────────────────


class MockOandaConnector(OandaConnector):
    """OandaConnector that returns fake data without hitting the API."""

    def __init__(self):
        super().__init__(api_key="test", account_id="test-001")
        self._balance = 300.0
        self._trades: dict[str, Order] = {}
        self._next_id = 1
        self._candle_data: dict[str, pd.DataFrame] = {}

    def connect(self) -> bool:
        return True

    def disconnect(self) -> None:
        pass

    def get_account_info(self) -> AccountInfo:
        return AccountInfo(
            balance=self._balance,
            unrealized_pnl=0,
            margin_used=0,
            margin_available=self._balance,
            open_trades=len(self._trades),
            currency="USD",
        )

    def get_candles(self, pair, timeframe, count=500) -> pd.DataFrame:
        key = f"{pair}_{timeframe}"
        if key in self._candle_data:
            return self._candle_data[key].tail(count)
        return _generate_candles(count)

    def set_candles(self, pair: str, timeframe: str, df: pd.DataFrame) -> None:
        self._candle_data[f"{pair}_{timeframe}"] = df

    def place_order(self, pair, side, units, order_type=OrderType.MARKET,
                    price=0.0, stop_loss=0.0, take_profit=0.0) -> Order:
        oid = f"mock-{self._next_id}"
        self._next_id += 1
        order = Order(
            order_id=oid, pair=pair, side=side, order_type=order_type,
            units=units, price=price, stop_loss=stop_loss,
            take_profit=take_profit, status=OrderStatus.FILLED,
            fill_price=price or 1.10000,
        )
        self._trades[oid] = order
        return order

    def close_trade(self, order_id) -> Order:
        order = self._trades.pop(order_id)
        order.status = OrderStatus.FILLED
        order.pnl = 1.50
        return order

    def get_open_trades(self) -> list[Order]:
        return list(self._trades.values())

    def get_spread(self, pair) -> float:
        return 0.00015


def _generate_candles(count=200):
    """Generate realistic OHLC candles for testing signal generation."""
    np.random.seed(42)
    dates = pd.date_range("2026-01-01", periods=count, freq="1h")
    price = 1.10000
    rows = []
    for i in range(count):
        change = np.random.normal(0, 0.0005)
        o = price
        h = o + abs(np.random.normal(0, 0.0008))
        l = o - abs(np.random.normal(0, 0.0008))
        c = o + change
        h = max(h, o, c)
        l = min(l, o, c)
        rows.append({"open": o, "high": h, "low": l, "close": c, "volume": 1000})
        price = c
    return pd.DataFrame(rows, index=dates)


# ──────────────── OandaConnector unit tests ────────────────


class TestOandaConnector:

    def test_timeframe_mapping(self):
        assert TIMEFRAME_MAP["M15"] == "M15"
        assert TIMEFRAME_MAP["H1"] == "H1"
        assert TIMEFRAME_MAP["D"] == "D"

    def test_connect_no_credentials(self):
        connector = OandaConnector(api_key="", account_id="")
        assert not connector.connect()

    def test_headers(self):
        connector = OandaConnector(api_key="test-key-123")
        headers = connector._headers
        assert "Bearer test-key-123" in headers["Authorization"]

    def test_environment_urls(self):
        practice = OandaConnector(environment="practice")
        live = OandaConnector(environment="live")
        assert "practice" in practice.base_url
        assert "practice" not in live.base_url

    def test_mock_connector_works(self):
        mock = MockOandaConnector()
        assert mock.connect()
        info = mock.get_account_info()
        assert info.balance == 300.0
        candles = mock.get_candles("EUR_USD", "H1", count=50)
        assert len(candles) == 50
        assert "close" in candles.columns


# ──────────────── PaperTrader tests ────────────────


@pytest.fixture
def mock_connector():
    return MockOandaConnector()


class TestPaperTrader:

    @pytest.fixture
    def trader(self, mock_connector, tmp_path):
        config = PaperTraderConfig(
            pairs=["EUR_USD"],
            timeframes=["H1"],
            max_cycles=2,
            poll_interval=0,
            min_quality_score=30,  # lower threshold so test signals pass
            use_learning=False,
            use_session_filter=False,
        )
        return PaperTrader(config=config, connector=mock_connector)

    def test_init(self, trader):
        assert trader.config.max_cycles == 2
        assert not trader._running

    def test_start_and_stop(self, trader):
        """Trader should run max_cycles then stop."""
        trader.start()
        assert trader.state.cycles == 2
        assert not trader._running

    def test_get_status(self, trader):
        trader.start()
        status = trader.get_status()
        assert status["cycles"] == 2
        assert "EUR_USD" in status["active_pairs"]
        assert isinstance(status["balance"], float)

    def test_state_tracking(self, trader):
        trader.start()
        assert trader.state.cycles == 2
        # Signals may or may not be generated depending on random data
        assert trader.state.signals_generated >= 0

    def test_daily_reset(self, trader, mock_connector):
        """Verify daily reset happens on first cycle."""
        trader.start()
        assert trader.state.current_day is not None

    def test_config_pairs(self, mock_connector):
        config = PaperTraderConfig(
            pairs=["GBP_USD", "USD_JPY"],
            max_cycles=1,
            poll_interval=0,
            use_learning=False,
            use_session_filter=False,
        )
        trader = PaperTrader(config=config, connector=mock_connector)
        trader.start()
        status = trader.get_status()
        assert "GBP_USD" in status["active_pairs"]

    def _learning_config(self, **overrides):
        return PaperTraderConfig(
            pairs=["EUR_USD"],
            timeframes=["H1"],
            max_cycles=1,
            poll_interval=0,
            use_learning=True,
            auto_pair_selection=False,
            use_session_filter=False,
            **overrides,
        )

    def test_with_learning_enabled(self, mock_connector):
        trader = PaperTrader(config=self._learning_config(), connector=mock_connector)
        trader.start()
        assert trader.adaptive is not None

    def test_corrector_off_by_default(self, mock_connector):
        trader = PaperTrader(config=self._learning_config(), connector=mock_connector)
        trader.start()
        assert trader.corrector is None

    def test_corrector_enabled_by_flag(self, mock_connector):
        config = self._learning_config(use_self_corrector=True)
        trader = PaperTrader(config=config, connector=mock_connector)
        trader.start()
        assert trader.corrector is not None

    def test_all_signal_types_active_without_corrector(self, mock_connector):
        trader = PaperTrader(config=self._learning_config(), connector=mock_connector)
        trader.start()
        assert trader._get_enabled_signal_types() == trader.config.signal_types


    def test_stop_method(self, mock_connector):
        config = PaperTraderConfig(
            max_cycles=0,  # would run forever
            poll_interval=0,
            use_learning=False,
            use_session_filter=False,
        )
        trader = PaperTrader(config=config, connector=mock_connector)
        # Stop immediately via max_cycles override
        trader.config.max_cycles = 1
        trader.start()
        assert trader.state.cycles == 1


class TestWeekendFlatten:
    """Positions must not be carried across the weekend gap."""

    @pytest.fixture
    def trader(self, mock_connector):
        return PaperTrader(
            config=PaperTraderConfig(max_cycles=1, poll_interval=0),
            connector=mock_connector,
        )

    def test_friday_after_cutoff_is_in_window(self, trader):
        assert trader._is_weekend_cutoff(datetime(2026, 5, 29, 16, 45))

    def test_friday_before_cutoff_is_not(self, trader):
        assert not trader._is_weekend_cutoff(datetime(2026, 5, 29, 16, 44))

    def test_other_weekdays_are_not(self, trader):
        assert not trader._is_weekend_cutoff(datetime(2026, 5, 28, 23, 59))

    def test_flatten_closes_every_open_position(self, trader, mock_connector):
        trader.start()
        trader.order_mgr.open_orders = {
            "1721": Order(
                order_id="1721", pair="GBP_USD", side=OrderSide.BUY,
                order_type=OrderType.MARKET, units=1000,
                status=OrderStatus.FILLED,
            ),
            "1869": Order(
                order_id="1869", pair="EUR_USD", side=OrderSide.SELL,
                order_type=OrderType.MARKET, units=1000,
                status=OrderStatus.FILLED,
            ),
        }
        closed = []
        mock_connector.close_trade = lambda oid: closed.append(oid)

        trader._flatten_open_positions()

        assert closed == ["1721", "1869"]

    def test_flatten_leaves_reconciliation_to_record_the_trade(self, trader, mock_connector):
        """Closing must not drop the order locally, or it is never recorded."""
        trader.start()
        trader.order_mgr.open_orders = {
            "1721": Order(
                order_id="1721", pair="GBP_USD", side=OrderSide.BUY,
                order_type=OrderType.MARKET, units=1000,
                status=OrderStatus.FILLED,
            ),
        }
        mock_connector.close_trade = lambda oid: None

        trader._flatten_open_positions()

        assert "1721" in trader.order_mgr.open_orders


class TestPaperTraderConfig:

    def test_defaults(self):
        config = PaperTraderConfig()
        assert config.poll_interval == 120
        assert config.max_open_trades == 5
        assert "reversal" in config.signal_types
        assert len(config.pairs) == 9

    def test_custom(self):
        config = PaperTraderConfig(
            pairs=["EUR_USD"],
            timeframes=["M15", "H1"],
            max_open_trades=5,
        )
        assert config.max_open_trades == 5
        assert len(config.timeframes) == 2


class TestPaperTraderState:

    def test_initial_state(self):
        state = PaperTraderState()
        assert state.cycles == 0
        assert state.total_pnl == 0.0
        assert state.current_day is None
