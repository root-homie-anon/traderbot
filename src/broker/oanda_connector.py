"""OANDA v20 REST API implementation.

Uses the v20 REST API directly via requests — no third-party SDK needed.
Supports both practice and live environments.

Requires environment variables:
    OANDA_API_KEY    - your OANDA API token
    OANDA_ACCOUNT_ID - your account ID (e.g. "101-001-12345678-001")
    OANDA_ENVIRONMENT - "practice" (default) or "live"
"""

import logging
import os
from datetime import datetime

import pandas as pd
import requests

from src.broker.broker_base import (
    AccountInfo, BrokerBase, Order, OrderSide, OrderStatus, OrderType,
)

logger = logging.getLogger("pa_bot")

PRACTICE_URL = "https://api-fxpractice.oanda.com"
LIVE_URL = "https://api-fxtrade.oanda.com"

# OANDA granularity mapping
TIMEFRAME_MAP = {
    "M1": "M1", "M5": "M5", "M15": "M15", "M30": "M30",
    "H1": "H1", "H4": "H4", "D": "D", "W": "W", "MN": "M",
}

# OANDA price precision per instrument (decimal places)
# JPY pairs use 3 decimals, most others use 5
JPY_PAIRS = {"USD_JPY", "EUR_JPY", "GBP_JPY", "AUD_JPY", "CAD_JPY", "CHF_JPY", "NZD_JPY"}


def _price_precision(pair: str) -> int:
    """Return the number of decimal places allowed for the instrument."""
    return 3 if pair in JPY_PAIRS else 5


def _fmt_price(price: float, pair: str) -> str:
    """Format a price to the instrument's required precision."""
    prec = _price_precision(pair)
    return f"{price:.{prec}f}"


class OandaConnector(BrokerBase):
    """OANDA v20 REST API connector.

    Usage:
        connector = OandaConnector()   # reads from env vars
        connector.connect()
        candles = connector.get_candles("EUR_USD", "H1", count=100)
        connector.place_order("EUR_USD", OrderSide.BUY, 1000, stop_loss=1.098, take_profit=1.104)
    """

    def __init__(
        self,
        api_key: str | None = None,
        account_id: str | None = None,
        environment: str | None = None,
    ):
        self.api_key = api_key or os.environ.get("OANDA_API_KEY", "")
        self.account_id = account_id or os.environ.get("OANDA_ACCOUNT_ID", "")
        env = environment or os.environ.get("OANDA_ENVIRONMENT", "practice")
        self.base_url = LIVE_URL if env == "live" else PRACTICE_URL
        self._session: requests.Session | None = None

    @property
    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept-Datetime-Format": "RFC3339",
        }

    def connect(self) -> bool:
        """Test the connection by fetching account summary."""
        if not self.api_key or not self.account_id:
            logger.error("OANDA_API_KEY and OANDA_ACCOUNT_ID must be set")
            return False

        self._session = requests.Session()
        self._session.headers.update(self._headers)

        try:
            resp = self._request("GET", f"/v3/accounts/{self.account_id}/summary")
            account = resp.get("account", {})
            logger.info(
                "Connected to OANDA — balance: %s %s",
                account.get("balance"), account.get("currency"),
            )
            return True
        except Exception as e:
            logger.error("OANDA connection failed: %s", e)
            self._session = None
            return False

    def disconnect(self) -> None:
        if self._session:
            self._session.close()
            self._session = None

    def get_account_info(self) -> AccountInfo:
        resp = self._request("GET", f"/v3/accounts/{self.account_id}/summary")
        acct = resp["account"]
        return AccountInfo(
            balance=float(acct["balance"]),
            unrealized_pnl=float(acct["unrealizedPL"]),
            margin_used=float(acct["marginUsed"]),
            margin_available=float(acct["marginAvailable"]),
            open_trades=int(acct["openTradeCount"]),
            currency=acct["currency"],
        )

    def get_candles(
        self,
        pair: str,
        timeframe: str,
        count: int = 500,
    ) -> pd.DataFrame:
        """Fetch OHLCV candles from OANDA.

        Returns DataFrame with DatetimeIndex and columns:
        open, high, low, close, volume.
        """
        granularity = TIMEFRAME_MAP.get(timeframe, timeframe)
        params = {
            "granularity": granularity,
            "count": min(count, 5000),  # OANDA max
            "price": "M",  # mid prices
        }

        resp = self._request(
            "GET",
            f"/v3/instruments/{pair}/candles",
            params=params,
        )

        candles = resp.get("candles", [])
        if not candles:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        rows = []
        for c in candles:
            if not c.get("complete", False):
                continue  # skip incomplete candle
            mid = c["mid"]
            rows.append({
                "timestamp": pd.Timestamp(c["time"]),
                "open": float(mid["o"]),
                "high": float(mid["h"]),
                "low": float(mid["l"]),
                "close": float(mid["c"]),
                "volume": int(c["volume"]),
            })

        df = pd.DataFrame(rows)
        if len(df) > 0:
            df.set_index("timestamp", inplace=True)
            df.index = df.index.tz_localize(None)

        return df

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
        """Place an order via OANDA API."""
        # OANDA uses negative units for sell
        signed_units = units if side == OrderSide.BUY else -units

        order_body: dict = {
            "type": "MARKET" if order_type == OrderType.MARKET else "LIMIT",
            "instrument": pair,
            "units": str(signed_units),
            "timeInForce": "FOK" if order_type == OrderType.MARKET else "GTC",
        }

        if order_type == OrderType.LIMIT and price > 0:
            order_body["price"] = _fmt_price(price, pair)

        if stop_loss > 0:
            order_body["stopLossOnFill"] = {"price": _fmt_price(stop_loss, pair)}
        if take_profit > 0:
            order_body["takeProfitOnFill"] = {"price": _fmt_price(take_profit, pair)}

        try:
            resp = self._request(
                "POST",
                f"/v3/accounts/{self.account_id}/orders",
                json={"order": order_body},
            )
        except Exception as e:
            return Order(
                order_id="",
                pair=pair,
                side=side,
                order_type=order_type,
                units=units,
                price=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                status=OrderStatus.REJECTED,
            )

        # Parse response
        if "orderFillTransaction" in resp:
            fill = resp["orderFillTransaction"]
            return Order(
                order_id=fill["id"],
                pair=pair,
                side=side,
                order_type=order_type,
                units=units,
                price=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                status=OrderStatus.FILLED,
                fill_price=float(fill.get("price", price)),
                fill_time=fill.get("time", ""),
            )
        elif "orderCancelTransaction" in resp:
            return Order(
                order_id="",
                pair=pair,
                side=side,
                order_type=order_type,
                units=units,
                status=OrderStatus.REJECTED,
            )
        else:
            # Pending (limit order)
            create = resp.get("orderCreateTransaction", {})
            return Order(
                order_id=create.get("id", ""),
                pair=pair,
                side=side,
                order_type=order_type,
                units=units,
                price=price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                status=OrderStatus.PENDING,
            )

    def close_trade(self, order_id: str) -> Order:
        """Close an open trade by trade ID."""
        resp = self._request(
            "PUT",
            f"/v3/accounts/{self.account_id}/trades/{order_id}/close",
        )

        close_txn = resp.get("orderFillTransaction", {})
        return Order(
            order_id=order_id,
            pair=close_txn.get("instrument", ""),
            side=OrderSide.BUY,  # will be updated from trade
            order_type=OrderType.MARKET,
            units=abs(int(float(close_txn.get("units", 0)))),
            status=OrderStatus.FILLED,
            fill_price=float(close_txn.get("price", 0)),
            pnl=float(close_txn.get("pl", 0)),
        )

    def get_open_trades(self) -> list[Order]:
        """Get all currently open trades."""
        resp = self._request(
            "GET",
            f"/v3/accounts/{self.account_id}/openTrades",
        )

        orders = []
        for t in resp.get("trades", []):
            units = int(t["currentUnits"])
            side = OrderSide.BUY if units > 0 else OrderSide.SELL
            orders.append(Order(
                order_id=t["id"],
                pair=t["instrument"],
                side=side,
                order_type=OrderType.MARKET,
                units=abs(units),
                fill_price=float(t["price"]),
                fill_time=t.get("openTime", ""),
                status=OrderStatus.FILLED,
                pnl=float(t.get("unrealizedPL", 0)),
                stop_loss=float(t.get("stopLossOrder", {}).get("price", 0)),
                take_profit=float(t.get("takeProfitOrder", {}).get("price", 0)),
            ))
        return orders

    def get_spread(self, pair: str) -> float:
        """Get current spread by fetching pricing."""
        resp = self._request(
            "GET",
            f"/v3/accounts/{self.account_id}/pricing",
            params={"instruments": pair},
        )
        prices = resp.get("prices", [])
        if not prices:
            return 0.00015  # fallback
        p = prices[0]
        ask = float(p["asks"][0]["price"])
        bid = float(p["bids"][0]["price"])
        return ask - bid

    def _request(self, method: str, path: str, **kwargs) -> dict:
        """Make an authenticated request to OANDA API."""
        session = self._session or requests.Session()
        if not self._session:
            session.headers.update(self._headers)

        url = f"{self.base_url}{path}"
        resp = session.request(method, url, timeout=30, **kwargs)

        if resp.status_code >= 400:
            logger.error("OANDA API error %d: %s", resp.status_code, resp.text)
            resp.raise_for_status()

        return resp.json()
