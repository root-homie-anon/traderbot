"""Place, monitor, and manage orders.

Orchestrates order flow between signal generation and broker execution.
Works with any BrokerBase implementation.
"""

import logging
from dataclasses import dataclass, field

from src.broker.broker_base import (
    BrokerBase, Order, OrderSide, OrderType, OrderStatus,
)
from src.risk.position_sizer import calculate_position_size
from src.risk.daily_limits import DailyLimitTracker
from src.risk.drawdown_manager import DrawdownManager
from src.risk.stop_validator import validate_stop
from src.risk.correlation_guard import CorrelationGuard
from src.signals.signal_base import Signal, SignalDirection
from src.utils.helpers import get_pip_value
from src.utils.validators import validate_signal

logger = logging.getLogger("pa_bot")


@dataclass
class OrderResult:
    """Result of an order attempt."""

    success: bool
    order: Order | None = None
    reason: str = ""


class OrderManager:
    """Manage order lifecycle: validate, size, place, and track.

    Usage:
        mgr = OrderManager(broker, account_balance=300)
        result = mgr.submit_signal(signal)
        if result.success:
            print(f"Placed order {result.order.order_id}")
    """

    def __init__(
        self,
        broker: BrokerBase,
        account_balance: float = 300.0,
        risk_per_trade: float = 0.01,
        max_open_trades: int = 3,
        use_drawdown_scaling: bool = True,
        use_daily_limits: bool = True,
    ):
        self.broker = broker
        self.balance = account_balance
        self.risk_per_trade = risk_per_trade
        self.max_open_trades = max_open_trades

        self.drawdown_mgr = DrawdownManager(
            peak_balance=account_balance,
            current_balance=account_balance,
        )
        self.daily_limits = DailyLimitTracker(account_balance=account_balance)
        self.use_drawdown_scaling = use_drawdown_scaling
        self.use_daily_limits = use_daily_limits
        self.correlation_guard = CorrelationGuard(max_correlated=2)

        self.open_orders: dict[str, Order] = {}

    def submit_signal(self, signal: Signal) -> OrderResult:
        """Validate and place an order from a trading signal."""
        # Validate signal fields and logical consistency
        signal_errors = validate_signal(signal)
        if signal_errors:
            reason = "signal validation failed: " + "; ".join(signal_errors)
            logger.warning("Rejecting signal: %s", reason)
            return OrderResult(success=False, reason=reason)

        # Check daily limits
        if self.use_daily_limits and not self.daily_limits.can_trade():
            return OrderResult(success=False, reason="daily loss limit reached")

        # Check max open trades
        if len(self.open_orders) >= self.max_open_trades:
            return OrderResult(success=False, reason="max open trades reached")

        # Check for existing or conflicting trades on the same pair
        for order in self.open_orders.values():
            if order.pair == signal.pair:
                return OrderResult(
                    success=False,
                    reason=f"already have open trade on {signal.pair}",
                )

        # Check correlation limits — prevent over-concentration on the same
        # macro bet (e.g. multiple USD-weak longs at the same time)
        allowed, corr_reason = self.correlation_guard.can_open_trade(
            signal.pair,
            signal.direction.value,
            self._get_open_trade_info(),
        )
        if not allowed:
            logger.warning(
                "Rejecting order for %s — %s", signal.pair, corr_reason
            )
            return OrderResult(success=False, reason=corr_reason)

        # Validate stop distance before sizing
        pip_value = get_pip_value(signal.pair)
        stop_check = validate_stop(
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            direction=signal.direction.value,
            pip_value=pip_value,
        )
        if not stop_check["valid"]:
            reason = f"stop rejected: {stop_check['reason']}"
            logger.warning("Rejecting order for %s — %s", signal.pair, reason)
            return OrderResult(success=False, reason=reason)

        # Position sizing
        risk_mult = (
            self.drawdown_mgr.risk_multiplier()
            if self.use_drawdown_scaling
            else 1.0
        )
        sizing = calculate_position_size(
            account_balance=self.balance,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            risk_pct=self.risk_per_trade * risk_mult,
            pip_value=pip_value,
        )

        if sizing["position_size"] <= 0:
            return OrderResult(success=False, reason="position size is zero")

        # Place order
        side = OrderSide.BUY if signal.direction == SignalDirection.BUY else OrderSide.SELL
        try:
            order = self.broker.place_order(
                pair=signal.pair,
                side=side,
                units=sizing["position_size"],
                order_type=OrderType.MARKET,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
            )
        except Exception as e:
            logger.error("Order placement failed: %s", e)
            return OrderResult(success=False, reason=str(e))

        if order.status == OrderStatus.FILLED:
            self.open_orders[order.order_id] = order
            logger.info(
                "Order filled: %s %s %d units @ %.5f",
                side.value, signal.pair, sizing["position_size"], order.fill_price,
            )
            return OrderResult(success=True, order=order)

        return OrderResult(
            success=False,
            order=order,
            reason=f"order status: {order.status.value}",
        )

    def close_order(self, order_id: str) -> OrderResult:
        """Close an open order by ID."""
        if order_id not in self.open_orders:
            return OrderResult(success=False, reason="order not found")

        try:
            closed = self.broker.close_trade(order_id)
        except Exception as e:
            logger.error("Close failed for %s: %s", order_id, e)
            return OrderResult(success=False, reason=str(e))

        self._process_closed_order(closed)
        return OrderResult(success=True, order=closed)

    def sync_open_trades(self) -> None:
        """Sync open orders with the broker's current state."""
        try:
            broker_trades = self.broker.get_open_trades()
        except Exception as e:
            logger.error("Failed to sync trades: %s", e)
            return

        broker_ids = {t.order_id for t in broker_trades}

        # Detect closed trades
        closed_ids = [
            oid for oid in self.open_orders if oid not in broker_ids
        ]
        for oid in closed_ids:
            order = self.open_orders.pop(oid)
            logger.info("Trade %s closed externally", oid)
            self._process_closed_order(order)

        # Update open orders
        for trade in broker_trades:
            self.open_orders[trade.order_id] = trade

    def _process_closed_order(self, order: Order) -> None:
        """Update internal state after a trade closes."""
        self.open_orders.pop(order.order_id, None)
        self.balance += order.pnl
        self.drawdown_mgr.record_trade(order.pnl)
        self.daily_limits.record_trade(order.pnl)

    def _get_open_trade_info(self) -> dict[str, dict[str, str]]:
        """Return a lightweight snapshot of open trades for correlation checks.

        Returns:
            Mapping of order_id -> {"pair": str, "direction": str} where
            *direction* is the lowercase ``OrderSide`` value (``"buy"`` /
            ``"sell"``).
        """
        return {
            order_id: {
                "pair": order.pair,
                "direction": order.side.value,
            }
            for order_id, order in self.open_orders.items()
        }

    def reset_daily(self) -> None:
        """Reset daily limits for a new trading day."""
        self.daily_limits.reset(new_balance=self.balance)
