"""Abstract base class for broker connectors."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

import pandas as pd


class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"


class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(Enum):
    PENDING = "pending"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass
class Order:
    """Represents a broker order."""

    order_id: str
    pair: str
    side: OrderSide
    order_type: OrderType
    units: int
    price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    status: OrderStatus = OrderStatus.PENDING
    fill_price: float = 0.0
    fill_time: str = ""
    pnl: float = 0.0


@dataclass
class AccountInfo:
    """Broker account summary."""

    balance: float
    unrealized_pnl: float
    margin_used: float
    margin_available: float
    open_trades: int
    currency: str = "USD"

    @property
    def equity(self) -> float:
        return self.balance + self.unrealized_pnl


class BrokerBase(ABC):
    """Abstract interface for broker connectors.

    Subclasses (OandaConnector, BinanceConnector) implement the actual
    API calls. This base defines the contract that OrderManager depends on.
    """

    @abstractmethod
    def connect(self) -> bool:
        """Establish connection to the broker. Returns True on success."""

    @abstractmethod
    def disconnect(self) -> None:
        """Close the broker connection."""

    @abstractmethod
    def get_account_info(self) -> AccountInfo:
        """Fetch current account balance, margin, etc."""

    @abstractmethod
    def get_candles(
        self,
        pair: str,
        timeframe: str,
        count: int = 500,
    ) -> pd.DataFrame:
        """Fetch OHLCV candles. Returns DataFrame with datetime index."""

    @abstractmethod
    def place_order(
        self,
        pair: str,
        side: OrderSide,
        units: int,
        order_type: OrderType = OrderType.MARKET,
        price: float = 0.0,
        stop_loss: float = 0.0,
        take_profit: float = 0.0,
    ) -> Order:
        """Place an order. Returns the Order with status updated."""

    @abstractmethod
    def close_trade(self, order_id: str) -> Order:
        """Close an open trade by order ID."""

    @abstractmethod
    def get_open_trades(self) -> list[Order]:
        """Get all currently open trades."""

    @abstractmethod
    def get_spread(self, pair: str) -> float:
        """Get the current spread in price units for a pair."""
