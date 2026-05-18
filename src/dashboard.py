"""Truth dashboard: read trade_results, emit Sharpe / DD / PSR / WR / expectancy.

Usage:
    python -m src.dashboard                  # all paper trades
    python -m src.dashboard --source paper   # explicit
    python -m src.dashboard --since 2026-04-01
    python -m src.dashboard --json           # machine-readable
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

CLUSTER_WINDOW_MINUTES = 120
DEFAULT_JOURNAL = Path.home() / "dev-vault" / "projects" / "traderbot" / "trade-log.md"

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "performance.db"


@dataclass
class Metrics:
    n_trades: int
    n_wins: int
    n_losses: int
    win_rate: float
    gross_profit: float
    gross_loss: float
    net_pnl: float
    profit_factor: float
    avg_trade: float
    median_trade: float
    std_trade: float
    best_trade: float
    worst_trade: float
    avg_win: float
    avg_loss: float
    expectancy_dollars: float
    expectancy_r: float
    sharpe_per_trade: float
    psr_vs_zero: float
    max_drawdown_pct: float
    max_drawdown_dollars: float
    consecutive_losses: int
    first_trade: str
    last_trade: str
    days_span: int


def fetch_trades(db: Path, source: str | None, since: str | None) -> list[dict]:
    if not db.exists():
        raise SystemExit(f"db not found: {db}")
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    where, args = [], []
    if source:
        where.append("source = ?")
        args.append(source)
    if since:
        where.append("timestamp >= ?")
        args.append(since)
    sql = "SELECT * FROM trade_results"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY timestamp ASC"
    rows = [dict(r) for r in con.execute(sql, args).fetchall()]
    con.close()
    return rows


def psr(sharpe: float, n: int, skew: float, kurt_excess: float) -> float:
    """Probabilistic Sharpe Ratio vs SR* = 0 (López de Prado 2012).

    Probability the true Sharpe exceeds zero given sample SR, N, skew, excess kurtosis.
    """
    if n < 3:
        return float("nan")
    denom = 1.0 - skew * sharpe + ((kurt_excess) / 4.0) * sharpe * sharpe
    if denom <= 0:
        return float("nan")
    z = sharpe * math.sqrt(n - 1) / math.sqrt(denom)
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def excess_kurtosis(xs: list[float]) -> float:
    n = len(xs)
    if n < 4:
        return 0.0
    m = statistics.fmean(xs)
    var = sum((x - m) ** 2 for x in xs) / n
    if var == 0:
        return 0.0
    m4 = sum((x - m) ** 4 for x in xs) / n
    return m4 / (var * var) - 3.0


def skewness(xs: list[float]) -> float:
    n = len(xs)
    if n < 3:
        return 0.0
    m = statistics.fmean(xs)
    var = sum((x - m) ** 2 for x in xs) / n
    if var == 0:
        return 0.0
    m3 = sum((x - m) ** 3 for x in xs) / n
    return m3 / (var ** 1.5)


def max_consecutive_losses(pnls: list[float]) -> int:
    best, run = 0, 0
    for p in pnls:
        if p < 0:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


def compute(rows: list[dict]) -> Metrics:
    if not rows:
        raise SystemExit("no trades match filter")
    pnls = [float(r["pnl"]) for r in rows]
    risks = [float(r["risk_amount"]) for r in rows if r["risk_amount"]]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    n = len(pnls)

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    pf = gross_profit / gross_loss if gross_loss else float("inf")

    avg_win = statistics.fmean(wins) if wins else 0.0
    avg_loss = statistics.fmean(losses) if losses else 0.0
    win_rate = len(wins) / n

    r_multiples = [p / r for p, r in zip(pnls, risks) if r > 0]
    expectancy_r = statistics.fmean(r_multiples) if r_multiples else 0.0
    expectancy_dollars = statistics.fmean(pnls)

    std = statistics.pstdev(pnls) if n > 1 else 0.0
    sharpe = (expectancy_dollars / std) if std > 0 else 0.0
    sk = skewness(pnls)
    kx = excess_kurtosis(pnls)
    p_psr = psr(sharpe, n, sk, kx)

    equity = 0.0
    peak = 0.0
    max_dd_dollars = 0.0
    for p in pnls:
        equity += p
        if equity > peak:
            peak = equity
        dd = peak - equity
        if dd > max_dd_dollars:
            max_dd_dollars = dd
    starting_equity = statistics.fmean(risks) / 0.02 if risks else 1.0
    max_dd_pct = (max_dd_dollars / starting_equity) * 100.0 if starting_equity > 0 else 0.0

    first_ts = rows[0]["timestamp"][:10]
    last_ts = rows[-1]["timestamp"][:10]
    from datetime import date
    d1 = date.fromisoformat(first_ts)
    d2 = date.fromisoformat(last_ts)
    days_span = (d2 - d1).days

    return Metrics(
        n_trades=n,
        n_wins=len(wins),
        n_losses=len(losses),
        win_rate=win_rate,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        net_pnl=sum(pnls),
        profit_factor=pf,
        avg_trade=expectancy_dollars,
        median_trade=statistics.median(pnls),
        std_trade=std,
        best_trade=max(pnls),
        worst_trade=min(pnls),
        avg_win=avg_win,
        avg_loss=avg_loss,
        expectancy_dollars=expectancy_dollars,
        expectancy_r=expectancy_r,
        sharpe_per_trade=sharpe,
        psr_vs_zero=p_psr,
        max_drawdown_pct=max_dd_pct,
        max_drawdown_dollars=max_dd_dollars,
        consecutive_losses=max_consecutive_losses(pnls),
        first_trade=first_ts,
        last_trade=last_ts,
        days_span=days_span,
    )


def graduation_check(m: Metrics) -> list[tuple[str, bool, str]]:
    """The 4 gates from research dossier — explicit pass/fail with current value."""
    n_gate = (m.n_trades >= 200, f"{m.n_trades}/200")
    sharpe_gate = (m.sharpe_per_trade >= 0.5, f"{m.sharpe_per_trade:.2f}/0.50")
    dd_gate = (m.max_drawdown_pct <= 20.0, f"{m.max_drawdown_pct:.1f}%/20%")
    psr_gate = (m.psr_vs_zero >= 0.95, f"{m.psr_vs_zero:.2%}/95%")
    return [
        ("sample size ≥200 trades", *n_gate),
        ("Sharpe ≥0.50", *sharpe_gate),
        ("max DD ≤20%", *dd_gate),
        ("PSR vs 0 ≥95%", *psr_gate),
    ]


def breakdown(rows: list[dict], by: str) -> list[tuple[str, int, int, float, float]]:
    buckets: dict[str, list[float]] = {}
    for r in rows:
        buckets.setdefault(r[by], []).append(float(r["pnl"]))
    out = []
    for k, pnls in buckets.items():
        wins = sum(1 for p in pnls if p > 0)
        n = len(pnls)
        wr = wins / n if n else 0.0
        out.append((k, n, wins, wr, sum(pnls)))
    return sorted(out, key=lambda r: r[4])


def annotate_clusters(rows: list[dict], window_min: int = CLUSTER_WINDOW_MINUTES) -> list[dict]:
    """Tag each trade with cluster_idx (0=standalone, 1+=Nth in a cluster).

    A cluster = consecutive trades on the same (pair, signal_type, direction)
    where each fires within window_min of the prior one. Catches the
    "same setup re-fires 6× in 50 min after stop-out" failure mode.
    """
    last_seen: dict[tuple, tuple[int, datetime, int]] = {}  # key -> (cluster_id, last_ts, position)
    next_cluster_id = 1
    out = []
    for r in rows:
        key = (r["pair"], r["signal_type"], r["direction"])
        ts = datetime.fromisoformat(r["timestamp"])
        cluster_id = 0
        position = 0
        if key in last_seen:
            cid, prev_ts, prev_pos = last_seen[key]
            delta_min = (ts - prev_ts).total_seconds() / 60
            if delta_min <= window_min:
                cluster_id = cid if cid else next_cluster_id
                if not cid:
                    next_cluster_id += 1
                position = prev_pos + 1
        last_seen[key] = (cluster_id, ts, position)
        out.append({**r, "_cluster_id": cluster_id, "_cluster_pos": position})

    # Backfill: the first trade of a cluster wasn't tagged when seen. Mark it.
    cluster_seeds: dict[int, int] = {}
    for i, r in enumerate(out):
        if r["_cluster_id"]:
            cluster_seeds.setdefault(r["_cluster_id"], i)
    for cid, seed_i in cluster_seeds.items():
        # Walk back from seed-1 to find original anchor with matching key
        seed = out[seed_i]
        key = (seed["pair"], seed["signal_type"], seed["direction"])
        for j in range(seed_i - 1, -1, -1):
            if (out[j]["pair"], out[j]["signal_type"], out[j]["direction"]) == key:
                if out[j]["_cluster_id"] == 0:
                    out[j]["_cluster_id"] = cid
                    out[j]["_cluster_pos"] = 0
                break
    return out


def fmt_trade_table(rows: list[dict]) -> str:
    """Per-trade narrative with cluster flags."""
    tagged = annotate_clusters(rows)
    lines = []
    add = lines.append
    add("=" * 110)
    add(f"{'#':<3} {'date':<10} {'pair':<8} {'sig':<9} {'dir':<4} {'Q':>4} {'R':>7} {'pnl $':>10} {'exit':<11} flags")
    add("-" * 110)
    for i, r in enumerate(tagged, 1):
        pnl = float(r["pnl"])
        risk = float(r["risk_amount"]) if r["risk_amount"] else 0.0
        r_mult = pnl / risk if risk > 0 else 0.0
        q = float(r.get("quality_score") or 0)
        date = r["timestamp"][:10]
        flags = []
        if r["_cluster_id"]:
            flags.append(f"⚠ cluster#{r['_cluster_id']}.{r['_cluster_pos']}")
        if r["signal_type"] == "unknown":
            flags.append("⚠ unknown-type")
        if r["exit_reason"] == "take_profit" and abs(r_mult) < 0.05:
            flags.append("⚠ micro-tp")
        flag_str = "  ".join(flags)
        add(f"{i:<3} {date:<10} {r['pair']:<8} {r['signal_type']:<9} {r['direction']:<4} "
            f"{q:>4.0f} {r_mult:>+7.3f} {pnl:>+10.2f} {r['exit_reason']:<11} {flag_str}")
    return "\n".join(lines)


def fmt_journal_md(rows: list[dict], metrics: Metrics) -> str:
    """Markdown export for obsidian vault. Regenerable; do not hand-edit."""
    tagged = annotate_clusters(rows)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Detect cluster groups for callout summary
    clusters: dict[int, list[dict]] = {}
    for r in tagged:
        if r["_cluster_id"]:
            clusters.setdefault(r["_cluster_id"], []).append(r)

    lines = [
        "# Trade Log",
        "",
        f"> Auto-generated from `data/performance.db` at {now}. Do not hand-edit — re-run `python3 -m src.dashboard --journal` after each session.",
        "",
        "## Summary",
        "",
        f"- Trades: **{metrics.n_trades}** ({metrics.n_wins}W / {metrics.n_losses}L, WR {metrics.win_rate:.1%})",
        f"- Net PnL: **${metrics.net_pnl:+,.2f}**",
        f"- Profit factor: **{metrics.profit_factor:.2f}**",
        f"- Sharpe (per-trade): **{metrics.sharpe_per_trade:+.3f}**",
        f"- PSR vs 0: **{metrics.psr_vs_zero:.1%}**",
        f"- Max DD: **${metrics.max_drawdown_dollars:,.2f}** ({metrics.max_drawdown_pct:.1f}% est. equity)",
        f"- Window: {metrics.first_trade} → {metrics.last_trade} ({metrics.days_span}d)",
        "",
    ]
    if clusters:
        lines.append("## Cluster alerts")
        lines.append("")
        lines.append("Same (pair, signal, direction) re-firing within 2h of a prior trade. These are bot architecture bugs, not strategy signal:")
        lines.append("")
        for cid, members in sorted(clusters.items()):
            anchor = members[0]
            total = sum(float(r["pnl"]) for r in members)
            lines.append(f"- **Cluster #{cid}** — `{anchor['pair']} {anchor['signal_type']} {anchor['direction']}` × {len(members)} trades, **${total:+,.2f}**, starts {anchor['timestamp'][:16]}")
        lines.append("")

    lines.append("## Trades")
    lines.append("")
    lines.append("| # | timestamp | pair | sig | dir | Q | R | pnl | exit | flags |")
    lines.append("|---|-----------|------|-----|-----|----|----|-----|------|-------|")
    for i, r in enumerate(tagged, 1):
        pnl = float(r["pnl"])
        risk = float(r["risk_amount"]) if r["risk_amount"] else 0.0
        r_mult = pnl / risk if risk > 0 else 0.0
        q = float(r.get("quality_score") or 0)
        flags = []
        if r["_cluster_id"]:
            flags.append(f"cluster#{r['_cluster_id']}.{r['_cluster_pos']}")
        if r["signal_type"] == "unknown":
            flags.append("unknown-type")
        if r["exit_reason"] == "take_profit" and abs(r_mult) < 0.05:
            flags.append("micro-tp")
        lines.append(
            f"| {i} | {r['timestamp'][:16]} | {r['pair']} | {r['signal_type']} | {r['direction']} | "
            f"{q:.0f} | {r_mult:+.3f} | {pnl:+,.2f} | {r['exit_reason']} | {' '.join(flags)} |"
        )
    lines.append("")
    lines.append("## How to validate a trade")
    lines.append("")
    lines.append("Look at any row and ask:")
    lines.append("- Was this a **clean signal** (not part of a cluster)? Clusters are bot bugs, not strategy outcomes.")
    lines.append("- Did the **R-multiple** match the intended ~2R minimum on wins? Micro-TPs flag a position-sizing or TP-placement bug.")
    lines.append("- Did `exit_reason` match what the chart actually did at that timestamp? Mismatches indicate broker/sync issues.")
    lines.append("")
    return "\n".join(lines)


def fmt_table(m: Metrics) -> str:
    lines = []
    add = lines.append
    add("=" * 64)
    add(f"TRADERBOT DASHBOARD — {m.first_trade} → {m.last_trade} ({m.days_span}d)")
    add("=" * 64)
    add(f"  Trades       {m.n_trades}  ({m.n_wins}W / {m.n_losses}L, WR {m.win_rate:.1%})")
    add(f"  Net PnL      ${m.net_pnl:>+12,.2f}")
    add(f"  Gross prof   ${m.gross_profit:>+12,.2f}")
    add(f"  Gross loss   ${-m.gross_loss:>+12,.2f}")
    pf = f"{m.profit_factor:.2f}" if math.isfinite(m.profit_factor) else "inf"
    add(f"  Profit fact  {pf}")
    add(f"  Avg trade    ${m.avg_trade:>+12,.2f}")
    add(f"  Avg win      ${m.avg_win:>+12,.2f}")
    add(f"  Avg loss     ${m.avg_loss:>+12,.2f}")
    add(f"  Expectancy   {m.expectancy_r:+.3f}R  (${m.expectancy_dollars:+,.2f}/trade)")
    add(f"  Best / Worst ${m.best_trade:+,.2f}  /  ${m.worst_trade:+,.2f}")
    add(f"  Max DD       ${m.max_drawdown_dollars:,.2f}  ({m.max_drawdown_pct:.1f}% of est. equity)")
    add(f"  Max losing   {m.consecutive_losses} consecutive")
    add(f"  Sharpe       {m.sharpe_per_trade:+.3f}  (per-trade, unannualized)")
    add(f"  PSR vs 0     {m.psr_vs_zero:.1%}  (prob true Sharpe > 0)")
    add("")
    add("GRADUATION GATES (live trading threshold)")
    add("-" * 64)
    for name, passed, value in graduation_check(m):
        mark = "PASS" if passed else "FAIL"
        add(f"  [{mark}]  {name:30s}  {value}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Read-only metrics over paper/backtest trades.")
    p.add_argument("--source", default="paper", help="paper | backtest | all (default: paper)")
    p.add_argument("--since", default=None, help="ISO date filter (timestamp >= since)")
    p.add_argument("--json", action="store_true", help="emit JSON instead of table")
    p.add_argument("--by", default=None, choices=["signal_type", "pair", "timeframe"],
                   help="show breakdown grouped by column")
    p.add_argument("--trades", action="store_true",
                   help="show per-trade chronological narrative with cluster flags")
    p.add_argument("--journal", nargs="?", const=str(DEFAULT_JOURNAL), default=None,
                   help=f"write markdown journal to PATH (default: {DEFAULT_JOURNAL})")
    args = p.parse_args(argv)

    source = None if args.source == "all" else args.source
    rows = fetch_trades(DB_PATH, source, args.since)
    m = compute(rows)

    if args.json:
        out = asdict(m)
        out["graduation"] = [{"gate": g, "pass": passed, "value": v}
                             for g, passed, v in graduation_check(m)]
        print(json.dumps(out, indent=2))
        return 0

    print(fmt_table(m))
    if args.by:
        print()
        print(f"BREAKDOWN BY {args.by.upper()}")
        print("-" * 64)
        print(f"  {'key':<14} {'N':>3} {'W':>3} {'WR':>6} {'net':>14}")
        for key, n, w, wr, net in breakdown(rows, args.by):
            print(f"  {key:<14} {n:>3} {w:>3} {wr:>6.1%} {net:>+14,.2f}")
    if args.trades:
        print()
        print(fmt_trade_table(rows))
    if args.journal is not None:
        path = Path(args.journal)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(fmt_journal_md(rows, m))
        print(f"\njournal written: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
