"""Simulate trades on historical data."""

import logging
from dataclasses import dataclass, field

import pandas as pd

from src.signals.signal_base import Signal, SignalDirection
from src.signals.reversal_signal import detect_reversal_signals
from src.signals.pullback_signal import detect_pullback_signals
from src.signals.buildup_signal import detect_buildup_signals
from src.signals.bos_signal import detect_bos_signals
from src.signals.quality_scorer import score_signal
from src.analysis.confluence import calculate_confluence
from src.analysis.trend_strength import calculate_trend_strength
from src.analysis.market_structure import classify_structure
from src.risk.position_sizer import calculate_position_size
from src.risk.stop_validator import validate_stop
from src.risk.daily_limits import DailyLimitTracker
from src.risk.drawdown_manager import DrawdownManager
from src.utils.helpers import get_pip_value
from src.backtest.metrics import calculate_metrics, BacktestMetrics
from src.config import RISK_PER_TRADE, QUALITY_SCORE_MIN, CONFLUENCE_MIN

logger = logging.getLogger("pa_bot")


@dataclass
class Trade:
    """A completed backtest trade."""

    signal: Signal
    entry_bar: int
    entry_price: float
    exit_bar: int = 0
    exit_price: float = 0.0
    pnl: float = 0.0
    risk_amount: float = 0.0
    position_size: int = 0
    exit_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "signal_type": self.signal.signal_type.value,
            "direction": self.signal.direction.value,
            "pair": self.signal.pair,
            "timeframe": self.signal.timeframe,
            "entry_bar": self.entry_bar,
            "entry_price": self.entry_price,
            "exit_bar": self.exit_bar,
            "exit_price": self.exit_price,
            "pnl": self.pnl,
            "risk_amount": self.risk_amount,
            "position_size": self.position_size,
            "exit_reason": self.exit_reason,
            "quality_score": self.signal.quality_score,
            "confluence_level": self.signal.confluence_level,
        }


@dataclass
class BacktestConfig:
    """Configuration for a backtest run."""

    initial_balance: float = 300.0
    risk_per_trade: float = RISK_PER_TRADE
    min_quality_score: float = QUALITY_SCORE_MIN
    min_rr: float = 2.0
    max_open_trades: int = 3
    signal_types: list[str] = field(default_factory=lambda: ["reversal", "pullback", "buildup", "bos"])
    warmup_bars: int = 50
    use_drawdown_scaling: bool = True
    use_daily_limits: bool = True
    spread_pips: float = 1.5


SIGNAL_DETECTORS = {
    "reversal": detect_reversal_signals,
    "pullback": detect_pullback_signals,
    "buildup": detect_buildup_signals,
    "bos": detect_bos_signals,
}


def run_backtest(
    df: pd.DataFrame,
    pair: str = "EUR_USD",
    timeframe: str = "H1",
    config: BacktestConfig | None = None,
) -> dict:
    """Run a walk-forward backtest on OHLC data.

    Walks bar-by-bar through the data, generating signals on the visible
    history and simulating fills on the next bar's open.

    Args:
        df: OHLC DataFrame with datetime index
        pair: trading pair name
        timeframe: timeframe label
        config: backtest configuration

    Returns:
        dict with 'trades', 'metrics', 'equity_curve', 'config'
    """
    if config is None:
        config = BacktestConfig()

    balance = config.initial_balance
    equity_curve = [balance]
    completed_trades: list[Trade] = []
    open_trades: list[Trade] = []

    drawdown_mgr = DrawdownManager(
        peak_balance=balance, current_balance=balance
    )
    daily_limits = DailyLimitTracker(account_balance=balance)
    current_day = None

    for bar_idx in range(config.warmup_bars, len(df)):
        bar = df.iloc[bar_idx]
        bar_date = df.index[bar_idx]

        # Reset daily limits on new day
        if hasattr(bar_date, "date"):
            day = bar_date.date()
        else:
            day = bar_date
        if day != current_day:
            daily_limits.reset(new_balance=balance)
            current_day = day

        # --- Check open trades for exit ---
        still_open = []
        for trade in open_trades:
            exit_price, exit_reason = _check_exit(trade, bar)
            if exit_price is not None:
                _close_trade(trade, bar_idx, exit_price, exit_reason)
                balance += trade.pnl
                completed_trades.append(trade)
                drawdown_mgr.record_trade(trade.pnl)
                daily_limits.record_trade(trade.pnl)
            else:
                still_open.append(trade)
        open_trades = still_open

        # --- Generate signals on visible history ---
        if len(open_trades) >= config.max_open_trades:
            equity_curve.append(balance)
            continue

        if config.use_daily_limits and not daily_limits.can_trade():
            equity_curve.append(balance)
            continue

        visible = df.iloc[: bar_idx + 1]
        signals = _generate_signals(visible, pair, timeframe, config)

        # Filter and take the best signal
        signals = [s for s in signals if s.quality_score >= config.min_quality_score]
        signals.sort(key=lambda s: s.quality_score, reverse=True)

        for signal in signals:
            if len(open_trades) >= config.max_open_trades:
                break

            # Don't open opposing trades on same pair
            if any(t.signal.pair == signal.pair and t.signal.direction != signal.direction for t in open_trades):
                continue

            # Validate stop before sizing (same gate as live path)
            pip_value = get_pip_value(signal.pair)
            stop_check = validate_stop(
                entry_price=signal.entry_price,
                stop_loss=signal.stop_loss,
                direction=signal.direction.value,
                pip_value=pip_value,
            )
            if not stop_check["valid"]:
                continue

            # Position sizing with drawdown scaling
            risk_mult = drawdown_mgr.risk_multiplier() if config.use_drawdown_scaling else 1.0
            sizing = calculate_position_size(
                account_balance=balance,
                entry_price=signal.entry_price,
                stop_loss=signal.stop_loss,
                risk_pct=config.risk_per_trade * risk_mult,
                pip_value=pip_value,
            )

            if sizing["position_size"] <= 0:
                continue

            # Apply spread
            spread = config.spread_pips * 0.0001
            if signal.direction == SignalDirection.BUY:
                entry = signal.entry_price + spread / 2
            else:
                entry = signal.entry_price - spread / 2

            trade = Trade(
                signal=signal,
                entry_bar=bar_idx,
                entry_price=entry,
                risk_amount=sizing["risk_amount"],
                position_size=sizing["position_size"],
            )
            open_trades.append(trade)

        equity_curve.append(balance)

    # Force-close any remaining open trades at last bar
    last_bar = df.iloc[-1]
    for trade in open_trades:
        _close_trade(trade, len(df) - 1, last_bar["close"], "end_of_data")
        balance += trade.pnl
        completed_trades.append(trade)

    equity_curve.append(balance)

    trade_dicts = [t.to_dict() for t in completed_trades]
    metrics = calculate_metrics(trade_dicts, config.initial_balance)

    return {
        "trades": trade_dicts,
        "metrics": metrics,
        "equity_curve": equity_curve,
        "config": {
            "initial_balance": config.initial_balance,
            "risk_per_trade": config.risk_per_trade,
            "min_quality_score": config.min_quality_score,
            "signal_types": config.signal_types,
            "pair": pair,
            "timeframe": timeframe,
            "total_bars": len(df),
        },
    }


def _generate_signals(
    df: pd.DataFrame,
    pair: str,
    timeframe: str,
    config: BacktestConfig,
) -> list[Signal]:
    """Run all enabled signal detectors and score with 6-factor quality scorer."""
    raw_signals = []
    for sig_type in config.signal_types:
        detector = SIGNAL_DETECTORS.get(sig_type)
        if detector:
            try:
                found = detector(df, pair=pair, timeframe=timeframe, min_rr=config.min_rr)
                raw_signals.extend(found)
            except Exception:
                pass

    if not raw_signals:
        return []

    # Score with full quality scorer
    trend = calculate_trend_strength(df)
    structure = classify_structure(df)
    scored = []

    for signal in raw_signals:
        if signal.confluence_level < CONFLUENCE_MIN:
            continue

        direction = "bullish" if signal.direction == SignalDirection.BUY else "bearish"
        confluence = calculate_confluence(df, direction=direction)
        breakdown = score_signal(
            signal,
            confluence=confluence,
            trend=trend,
            structure=structure,
        )
        signal.quality_score = breakdown.total_score
        scored.append(signal)

    return scored


def _check_exit(trade: Trade, bar: pd.Series) -> tuple[float | None, str]:
    """Check if a trade should exit on this bar.

    Returns (exit_price, reason) or (None, "") if no exit.
    """
    signal = trade.signal

    if signal.direction == SignalDirection.BUY:
        # Stop loss hit
        if bar["low"] <= signal.stop_loss:
            return signal.stop_loss, "stop_loss"
        # Take profit hit
        if bar["high"] >= signal.take_profit:
            return signal.take_profit, "take_profit"
    else:
        # Stop loss hit (for sells, stop is above)
        if bar["high"] >= signal.stop_loss:
            return signal.stop_loss, "stop_loss"
        # Take profit hit (for sells, TP is below)
        if bar["low"] <= signal.take_profit:
            return signal.take_profit, "take_profit"

    return None, ""


def _close_trade(trade: Trade, bar_idx: int, exit_price: float, reason: str) -> None:
    """Close a trade and calculate P&L."""
    trade.exit_bar = bar_idx
    trade.exit_price = exit_price
    trade.exit_reason = reason

    if trade.signal.direction == SignalDirection.BUY:
        price_diff = exit_price - trade.entry_price
    else:
        price_diff = trade.entry_price - exit_price

    trade.pnl = price_diff * trade.position_size
