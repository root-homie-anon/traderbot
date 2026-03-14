"""Generate backtest reports and visualizations."""

from src.backtest.metrics import BacktestMetrics


def format_report(metrics: BacktestMetrics, config: dict | None = None) -> str:
    """Generate a text summary report from backtest metrics.

    Args:
        metrics: calculated backtest metrics
        config: optional config dict for context

    Returns:
        formatted report string
    """
    lines = []
    lines.append("=" * 60)
    lines.append("  BACKTEST REPORT")
    lines.append("=" * 60)

    if config:
        lines.append(f"  Pair: {config.get('pair', 'N/A')}  |  TF: {config.get('timeframe', 'N/A')}")
        lines.append(f"  Bars: {config.get('total_bars', 'N/A')}  |  Initial: ${config.get('initial_balance', 0):.2f}")
        lines.append(f"  Signals: {', '.join(config.get('signal_types', []))}")
        lines.append("-" * 60)

    lines.append("")
    lines.append("  PERFORMANCE")
    lines.append(f"  Total Trades:      {metrics.total_trades}")
    lines.append(f"  Winners:           {metrics.winning_trades}  ({metrics.win_rate:.1%})")
    lines.append(f"  Losers:            {metrics.losing_trades}")
    lines.append(f"  Total P&L:         ${metrics.total_pnl:+.2f}  ({metrics.total_return_pct:+.1f}%)")
    lines.append(f"  Expectancy:        ${metrics.expectancy:+.2f} per trade")
    lines.append("")

    lines.append("  RISK METRICS")
    lines.append(f"  Sharpe Ratio:      {metrics.sharpe_ratio:.2f}")
    lines.append(f"  Profit Factor:     {metrics.profit_factor:.2f}")
    lines.append(f"  Max Drawdown:      {metrics.max_drawdown_pct:.2%}  (${metrics.max_drawdown_amount:.2f})")
    lines.append(f"  Avg R:R Achieved:  {metrics.avg_rr_achieved:.2f}")
    lines.append("")

    lines.append("  TRADE STATS")
    lines.append(f"  Avg Win:           ${metrics.avg_win:+.2f}")
    lines.append(f"  Avg Loss:          ${metrics.avg_loss:+.2f}")
    lines.append(f"  Largest Win:       ${metrics.largest_win:+.2f}")
    lines.append(f"  Largest Loss:      ${metrics.largest_loss:+.2f}")
    lines.append(f"  Avg Duration:      {metrics.avg_trade_duration_bars:.1f} bars")
    lines.append("")

    # Grade
    grade = _grade_performance(metrics)
    lines.append(f"  OVERALL GRADE:     {grade}")
    lines.append("=" * 60)

    return "\n".join(lines)


def trade_log(trades: list[dict]) -> str:
    """Format trade list as a readable log."""
    if not trades:
        return "No trades."

    lines = []
    lines.append(f"{'#':>3}  {'Type':<10} {'Dir':<5} {'Entry':>10} {'Exit':>10} {'P&L':>10} {'Reason':<12}")
    lines.append("-" * 70)

    for i, t in enumerate(trades, 1):
        lines.append(
            f"{i:3d}  {t['signal_type']:<10} {t['direction']:<5} "
            f"{t['entry_price']:10.5f} {t['exit_price']:10.5f} "
            f"{t['pnl']:+10.2f} {t['exit_reason']:<12}"
        )

    return "\n".join(lines)


def _grade_performance(m: BacktestMetrics) -> str:
    """Assign a letter grade to backtest performance."""
    score = 0

    # Win rate contribution (max 25 pts)
    if m.win_rate >= 0.55:
        score += 25
    elif m.win_rate >= 0.45:
        score += 15
    elif m.win_rate >= 0.35:
        score += 5

    # Profit factor (max 25 pts)
    if m.profit_factor >= 2.0:
        score += 25
    elif m.profit_factor >= 1.5:
        score += 15
    elif m.profit_factor >= 1.0:
        score += 5

    # Sharpe (max 25 pts)
    if m.sharpe_ratio >= 2.0:
        score += 25
    elif m.sharpe_ratio >= 1.0:
        score += 15
    elif m.sharpe_ratio >= 0.5:
        score += 5

    # Drawdown (max 25 pts)
    if m.max_drawdown_pct <= 0.10:
        score += 25
    elif m.max_drawdown_pct <= 0.20:
        score += 15
    elif m.max_drawdown_pct <= 0.30:
        score += 5

    if score >= 80:
        return "A"
    if score >= 60:
        return "B"
    if score >= 40:
        return "C"
    if score >= 20:
        return "D"
    return "F"
