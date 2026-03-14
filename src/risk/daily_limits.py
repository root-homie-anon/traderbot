"""Daily loss limit enforcement."""

from dataclasses import dataclass, field

from src.config import MAX_DAILY_LOSS


@dataclass
class DailyLimitTracker:
    """Track daily P&L and enforce loss limits."""

    account_balance: float
    max_daily_loss_pct: float = MAX_DAILY_LOSS
    daily_pnl: float = 0.0
    trades_today: int = 0
    _locked: bool = False

    @property
    def max_loss_amount(self) -> float:
        return self.account_balance * self.max_daily_loss_pct

    @property
    def remaining_risk(self) -> float:
        """How much more can be lost today."""
        if self._locked:
            return 0.0
        return max(0, self.max_loss_amount + self.daily_pnl)  # daily_pnl is negative when losing

    @property
    def is_locked(self) -> bool:
        return self._locked

    def record_trade(self, pnl: float) -> None:
        """Record a completed trade's P&L."""
        self.daily_pnl += pnl
        self.trades_today += 1

        if self.daily_pnl <= -self.max_loss_amount:
            self._locked = True

    def can_trade(self) -> bool:
        """Check if trading is still allowed today."""
        return not self._locked

    def reset(self, new_balance: float | None = None) -> None:
        """Reset for a new trading day."""
        if new_balance is not None:
            self.account_balance = new_balance
        self.daily_pnl = 0.0
        self.trades_today = 0
        self._locked = False
