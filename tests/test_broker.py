"""Tests for broker infrastructure (broker_base, order_manager, trade_logger)."""

import pytest
import pandas as pd

from src.broker.broker_base import (
    BrokerBase, Order, OrderSide, OrderType, OrderStatus, AccountInfo,
)
from src.broker.order_manager import OrderManager, OrderResult
from src.broker.trade_logger import TradeLogger
from src.signals.signal_base import Signal, SignalDirection, SignalType


# ──────────────────── Fake broker for testing ────────────────────


class FakeBroker(BrokerBase):
    """In-memory broker for testing OrderManager."""

    def __init__(self, balance=300.0, spread=0.00015):
        self._balance = balance
        self._spread = spread
        self._trades: dict[str, Order] = {}
        self._next_id = 1
        self._connected = False
        self.should_reject = False

    def connect(self) -> bool:
        self._connected = True
        return True

    def disconnect(self) -> None:
        self._connected = False

    def get_account_info(self) -> AccountInfo:
        return AccountInfo(
            balance=self._balance,
            unrealized_pnl=0,
            margin_used=0,
            margin_available=self._balance,
            open_trades=len(self._trades),
        )

    def get_candles(self, pair, timeframe, count=500) -> pd.DataFrame:
        return pd.DataFrame()

    def place_order(self, pair, side, units, order_type=OrderType.MARKET,
                    price=0.0, stop_loss=0.0, take_profit=0.0) -> Order:
        if self.should_reject:
            return Order(
                order_id="", pair=pair, side=side, order_type=order_type,
                units=units, status=OrderStatus.REJECTED,
            )
        oid = f"order-{self._next_id}"
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
        order.pnl = 2.50
        return order

    def get_open_trades(self) -> list[Order]:
        return list(self._trades.values())

    def get_spread(self, pair) -> float:
        return self._spread


def _make_signal(pair="EUR_USD", direction=SignalDirection.BUY):
    if direction == SignalDirection.BUY:
        stop_loss = 1.09800
        take_profit = 1.10400
    else:
        stop_loss = 1.10200
        take_profit = 1.09600
    return Signal(
        signal_type=SignalType.REVERSAL,
        direction=direction,
        pair=pair,
        timeframe="H1",
        timestamp=pd.Timestamp("2026-01-01"),
        entry_price=1.10000,
        stop_loss=stop_loss,
        take_profit=take_profit,
        quality_score=70,
        confluence_level=3,
        confidence=65,
    )


# ──────────────────── BrokerBase ────────────────────


class TestBrokerBase:

    def test_fake_broker_implements_interface(self):
        broker = FakeBroker()
        assert broker.connect()
        assert broker.get_account_info().balance == 300.0
        assert broker.get_spread("EUR_USD") == 0.00015
        broker.disconnect()

    def test_account_info_equity(self):
        info = AccountInfo(
            balance=300, unrealized_pnl=15, margin_used=50,
            margin_available=250, open_trades=1,
        )
        assert info.equity == 315

    def test_order_dataclass(self):
        order = Order(
            order_id="1", pair="EUR_USD", side=OrderSide.BUY,
            order_type=OrderType.MARKET, units=1000,
        )
        assert order.status == OrderStatus.PENDING
        assert order.pnl == 0.0


# ──────────────────── OrderManager ────────────────────


class TestOrderManager:

    def test_submit_signal_success(self):
        broker = FakeBroker()
        mgr = OrderManager(broker, account_balance=300)
        result = mgr.submit_signal(_make_signal())
        assert result.success
        assert result.order is not None
        assert len(mgr.open_orders) == 1

    def test_max_open_trades(self):
        broker = FakeBroker()
        mgr = OrderManager(broker, account_balance=300, max_open_trades=2)
        mgr.submit_signal(_make_signal(pair="EUR_USD"))
        mgr.submit_signal(_make_signal(pair="GBP_USD"))
        result = mgr.submit_signal(_make_signal(pair="USD_JPY"))
        assert not result.success
        assert "max open trades" in result.reason

    def test_duplicate_pair_blocked(self):
        broker = FakeBroker()
        mgr = OrderManager(broker, account_balance=300, max_open_trades=5)
        mgr.submit_signal(_make_signal(pair="EUR_USD", direction=SignalDirection.BUY))
        result = mgr.submit_signal(_make_signal(pair="EUR_USD", direction=SignalDirection.SELL))
        assert not result.success
        assert "already have open trade" in result.reason

    def test_daily_limit_blocks(self):
        broker = FakeBroker()
        mgr = OrderManager(broker, account_balance=300, max_open_trades=5)
        # Simulate hitting daily limit
        mgr.daily_limits._locked = True
        result = mgr.submit_signal(_make_signal())
        assert not result.success
        assert "daily loss" in result.reason

    def test_close_order(self):
        broker = FakeBroker()
        mgr = OrderManager(broker, account_balance=300)
        placed = mgr.submit_signal(_make_signal())
        oid = placed.order.order_id
        result = mgr.close_order(oid)
        assert result.success
        assert len(mgr.open_orders) == 0
        assert mgr.balance == pytest.approx(302.50)

    def test_close_unknown_order(self):
        broker = FakeBroker()
        mgr = OrderManager(broker, account_balance=300)
        result = mgr.close_order("nonexistent")
        assert not result.success

    def test_rejected_order(self):
        broker = FakeBroker()
        broker.should_reject = True
        mgr = OrderManager(broker, account_balance=300)
        result = mgr.submit_signal(_make_signal())
        assert not result.success

    def test_reset_daily(self):
        broker = FakeBroker()
        mgr = OrderManager(broker, account_balance=300)
        mgr.daily_limits._locked = True
        mgr.reset_daily()
        assert mgr.daily_limits.can_trade()


# ──────────────────── TradeLogger ────────────────────


class TestTradeLogger:

    @pytest.fixture
    def logger(self, tmp_path):
        return TradeLogger(db_path=tmp_path / "test_trades.db")

    def test_log_and_retrieve(self, logger):
        order = Order(
            order_id="t1", pair="EUR_USD", side=OrderSide.BUY,
            order_type=OrderType.MARKET, units=1000,
            status=OrderStatus.FILLED, fill_price=1.10000,
            stop_loss=1.09800, take_profit=1.10400,
        )
        logger.log_order(order, event="placed")
        logger.log_order(order, event="filled")
        history = logger.get_trade_history()
        assert len(history) == 2

    def test_filter_by_pair(self, logger):
        for pair in ["EUR_USD", "GBP_USD"]:
            order = Order(
                order_id=f"t-{pair}", pair=pair, side=OrderSide.BUY,
                order_type=OrderType.MARKET, units=1000,
                status=OrderStatus.FILLED,
            )
            logger.log_order(order)
        eur = logger.get_trade_history(pair="EUR_USD")
        assert len(eur) == 1
        assert eur[0]["pair"] == "EUR_USD"

    def test_order_events(self, logger):
        order = Order(
            order_id="t99", pair="EUR_USD", side=OrderSide.BUY,
            order_type=OrderType.MARKET, units=1000,
            status=OrderStatus.FILLED,
        )
        logger.log_order(order, event="placed")
        order.pnl = 5.0
        logger.log_order(order, event="closed")
        events = logger.get_order_events("t99")
        assert len(events) == 2
        assert events[0]["event"] == "placed"
        assert events[1]["event"] == "closed"

    def test_clear(self, logger):
        order = Order(
            order_id="t1", pair="EUR_USD", side=OrderSide.BUY,
            order_type=OrderType.MARKET, units=1000,
            status=OrderStatus.FILLED,
        )
        logger.log_order(order)
        logger.clear()
        assert len(logger.get_trade_history()) == 0

    def test_limit(self, logger):
        for i in range(20):
            order = Order(
                order_id=f"t{i}", pair="EUR_USD", side=OrderSide.BUY,
                order_type=OrderType.MARKET, units=1000,
                status=OrderStatus.FILLED,
            )
            logger.log_order(order)
        history = logger.get_trade_history(limit=5)
        assert len(history) == 5
