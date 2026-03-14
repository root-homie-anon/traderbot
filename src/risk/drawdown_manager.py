"""Position size reduction on consecutive losses / large drawdowns."""

from dataclasses import dataclass


@dataclass
class DrawdownManager:
    """Scale position sizes down during drawdowns."""

    peak_balance: float
    current_balance: float
    consecutive_losses: int = 0
    max_consecutive_losses: int = 0

    @property
    def drawdown_pct(self) -> float:
        """Current drawdown as a percentage."""
        if self.peak_balance == 0:
            return 0.0
        return (self.peak_balance - self.current_balance) / self.peak_balance

    def risk_multiplier(self) -> float:
        """Get position size multiplier based on drawdown state.

        Returns a value between 0.25 and 1.0:
        - 1.0: no drawdown or minor drawdown
        - 0.75: moderate drawdown (5-10%)
        - 0.50: significant drawdown (10-20%)
        - 0.25: severe drawdown (20%+) or 4+ consecutive losses
        """
        dd = self.drawdown_pct
        cl = self.consecutive_losses

        # Consecutive loss reduction
        if cl >= 4:
            return 0.25
        if cl >= 3:
            return 0.50

        # Drawdown-based reduction
        if dd >= 0.20:
            return 0.25
        if dd >= 0.10:
            return 0.50
        if dd >= 0.05:
            return 0.75

        return 1.0

    def record_trade(self, pnl: float) -> None:
        """Update state after a trade closes."""
        self.current_balance += pnl

        if pnl < 0:
            self.consecutive_losses += 1
            self.max_consecutive_losses = max(
                self.max_consecutive_losses, self.consecutive_losses
            )
        else:
            self.consecutive_losses = 0

        if self.current_balance > self.peak_balance:
            self.peak_balance = self.current_balance
