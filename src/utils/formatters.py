"""Output formatting utilities."""

from src.learning.performance_tracker import SetupStats
from src.learning.pair_selector import PairRanking


def format_pnl(value: float) -> str:
    """Format a P&L value with sign and 2 decimal places."""
    sign = "+" if value >= 0 else ""
    return f"{sign}{value:.2f}"


def format_pct(value: float, decimals: int = 1) -> str:
    """Format a decimal as percentage (0.55 -> '55.0%')."""
    return f"{value * 100:.{decimals}f}%"


def format_stats(stats: SetupStats) -> str:
    """Format a SetupStats into a readable summary line."""
    pf = f"{stats.profit_factor:.2f}" if stats.profit_factor != float("inf") else "inf"
    return (
        f"{stats.pair:>8s} | {stats.signal_type:>10s} | {stats.timeframe:>3s} | "
        f"trades: {stats.total_trades:3d} | WR: {format_pct(stats.win_rate)} | "
        f"PF: {pf:>6s} | PnL: {format_pnl(stats.total_pnl):>10s} | "
        f"E[R]: {stats.avg_r:+.2f}"
    )


def format_rankings(rankings: list[PairRanking]) -> str:
    """Format pair rankings into a table."""
    lines = [
        f"{'Rank':>4s}  {'Pair':>8s}  {'WR':>6s}  {'PF':>6s}  "
        f"{'Expect':>8s}  {'Trades':>6s}  {'Status':>8s}",
        "-" * 58,
    ]
    for r in rankings:
        pf = f"{r.profit_factor:.2f}" if r.profit_factor < 999 else "inf"
        status = "ACTIVE" if r.selected else "-"
        lines.append(
            f"{r.rank:4d}  {r.pair:>8s}  {format_pct(r.win_rate):>6s}  "
            f"{pf:>6s}  {r.expectancy:>8.4f}  {r.total_trades:6d}  {status:>8s}"
        )
    return "\n".join(lines)


def format_trade_summary(trade: dict) -> str:
    """Format a single trade dict into a one-line summary."""
    direction = trade.get("direction", "?").upper()
    pair = trade.get("pair", "?")
    pnl = trade.get("pnl", 0)
    exit_reason = trade.get("exit_reason", "?")
    quality = trade.get("quality_score", 0)

    return (
        f"{direction:>4s} {pair:>8s} | "
        f"PnL: {format_pnl(pnl):>10s} | "
        f"Exit: {exit_reason:<12s} | "
        f"QS: {quality:5.1f}"
    )
