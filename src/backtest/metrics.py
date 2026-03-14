"""Calculate win rate, Sharpe ratio, profit factor, max drawdown."""

from dataclasses import dataclass
import numpy as np


@dataclass
class BacktestMetrics:
    """Complete performance metrics from a backtest run."""

    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float                 # 0-1
    profit_factor: float            # gross_profit / gross_loss
    total_pnl: float
    total_return_pct: float
    avg_win: float
    avg_loss: float
    largest_win: float
    largest_loss: float
    max_drawdown_pct: float
    max_drawdown_amount: float
    sharpe_ratio: float
    avg_rr_achieved: float          # average R:R of winning trades
    avg_trade_duration_bars: float
    expectancy: float               # avg $ per trade


def calculate_metrics(
    trades: list[dict],
    initial_balance: float,
) -> BacktestMetrics:
    """Calculate performance metrics from a list of completed trades.

    Each trade dict must have:
        pnl: float (profit/loss in account currency)
        entry_bar: int (bar index of entry)
        exit_bar: int (bar index of exit)
        risk_amount: float (amount risked on this trade)
    """
    if not trades:
        return BacktestMetrics(
            total_trades=0, winning_trades=0, losing_trades=0,
            win_rate=0, profit_factor=0, total_pnl=0, total_return_pct=0,
            avg_win=0, avg_loss=0, largest_win=0, largest_loss=0,
            max_drawdown_pct=0, max_drawdown_amount=0, sharpe_ratio=0,
            avg_rr_achieved=0, avg_trade_duration_bars=0, expectancy=0,
        )

    pnls = [t["pnl"] for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    total_trades = len(trades)
    winning_trades = len(wins)
    losing_trades = len(losses)
    win_rate = winning_trades / total_trades if total_trades else 0

    gross_profit = sum(wins) if wins else 0
    gross_loss = abs(sum(losses)) if losses else 0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf") if gross_profit > 0 else 0

    total_pnl = sum(pnls)
    total_return_pct = total_pnl / initial_balance * 100 if initial_balance else 0

    avg_win = np.mean(wins) if wins else 0
    avg_loss = np.mean(losses) if losses else 0
    largest_win = max(wins) if wins else 0
    largest_loss = min(losses) if losses else 0

    # Max drawdown
    equity_curve = [initial_balance]
    for pnl in pnls:
        equity_curve.append(equity_curve[-1] + pnl)

    peak = equity_curve[0]
    max_dd_amount = 0
    max_dd_pct = 0
    for equity in equity_curve:
        if equity > peak:
            peak = equity
        dd = peak - equity
        dd_pct = dd / peak if peak > 0 else 0
        if dd > max_dd_amount:
            max_dd_amount = dd
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct

    # Sharpe ratio (annualized, assuming daily returns)
    if len(pnls) >= 2:
        returns = np.array(pnls) / initial_balance
        sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252) if np.std(returns) > 0 else 0
    else:
        sharpe = 0

    # Average R:R achieved on winners
    rr_achieved = []
    for t in trades:
        if t["pnl"] > 0 and t.get("risk_amount", 0) > 0:
            rr_achieved.append(t["pnl"] / t["risk_amount"])
    avg_rr = np.mean(rr_achieved) if rr_achieved else 0

    # Trade duration
    durations = [t["exit_bar"] - t["entry_bar"] for t in trades if "exit_bar" in t and "entry_bar" in t]
    avg_duration = np.mean(durations) if durations else 0

    expectancy = total_pnl / total_trades if total_trades else 0

    return BacktestMetrics(
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate=win_rate,
        profit_factor=profit_factor,
        total_pnl=round(total_pnl, 2),
        total_return_pct=round(total_return_pct, 2),
        avg_win=round(float(avg_win), 2),
        avg_loss=round(float(avg_loss), 2),
        largest_win=round(largest_win, 2),
        largest_loss=round(largest_loss, 2),
        max_drawdown_pct=round(max_dd_pct, 4),
        max_drawdown_amount=round(max_dd_amount, 2),
        sharpe_ratio=round(float(sharpe), 2),
        avg_rr_achieved=round(float(avg_rr), 2),
        avg_trade_duration_bars=round(float(avg_duration), 1),
        expectancy=round(expectancy, 2),
    )
