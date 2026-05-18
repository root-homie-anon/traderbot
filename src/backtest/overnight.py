"""Overnight backtest pipeline.

Three stages — designed to be triggered before bed and produce a vault-ready
report by morning:

  Stage 0: fetch (or reuse) 5000-bar H1 OHLC for the active USD-quoted pair set
  Stage 1: per-pair sanity backtest at current production config
  Stage 2: walk-forward parameter grid optimization

Outputs land in:
  ~/dev-vault/projects/traderbot/backtest-results/YYYY-MM-DD/
    - summary.md       <- human-readable digest
    - sanity.json      <- raw stage 1 numbers
    - walkforward.json <- raw stage 2 numbers per fold
    - run.log          <- full execution log

Run with:
  ./deploy/run-overnight-backtest.sh

Or directly:
  set -a && source .env && set +a
  .venv/bin/python -m src.backtest.overnight
"""

from __future__ import annotations

import json
import logging
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from src.backtest.backtester import BacktestConfig, run_backtest
from src.backtest.optimizer import walk_forward_optimize
from src.data.data_loader import load_pair
from src.data.historical_fetcher import HistoricalFetcher
from src.broker.oanda_connector import OandaConnector

logger = logging.getLogger("overnight_backtest")

# Validation-window pair set (matches deploy/launchd/start-paper.sh)
PAIRS = ["EUR_USD", "GBP_USD", "AUD_USD", "NZD_USD"]
TIMEFRAME = "H1"
CANDLE_COUNT = 5000  # OANDA hard cap; ~7 months of H1

# Where backtest output goes (mirrors the trade-log location pattern)
OUTPUT_ROOT = Path.home() / "dev-vault" / "projects" / "traderbot" / "backtest-results"

# Walk-forward param grid (focused on the knobs we actually want to tune)
WF_PARAM_GRID = {
    "min_quality_score": [55, 65, 75],
    "min_rr": [1.5, 2.0, 2.5],
    "risk_per_trade": [0.005],  # locked at validation-window value
}
WF_FOLDS = 3
WF_IS_PCT = 0.7


@dataclass
class SanityResult:
    pair: str
    n_trades: int
    win_rate: float
    expectancy_r: float
    profit_factor: float
    sharpe: float
    total_return_pct: float
    max_drawdown_pct: float
    first_bar: str
    last_bar: str


def _ensure_data(output_dir: Path) -> list[str]:
    """Fetch missing CSVs from OANDA. Returns list of pairs successfully loaded."""
    output_dir.mkdir(parents=True, exist_ok=True)
    missing = [p for p in PAIRS if not (output_dir / f"{p}_{TIMEFRAME}.csv").exists()]
    if not missing:
        logger.info("Stage 0: all %d pair CSVs present, skipping fetch", len(PAIRS))
        return list(PAIRS)

    logger.info("Stage 0: fetching %d missing pair(s) from OANDA: %s",
                len(missing), missing)
    connector = OandaConnector()
    if not connector.connect():
        raise RuntimeError("OANDA connect failed — check .env credentials")
    try:
        fetcher = HistoricalFetcher(connector)
        results = fetcher.fetch_all_pairs(
            pairs=missing, timeframes=[TIMEFRAME],
            count=CANDLE_COUNT, output_dir=str(output_dir),
        )
    finally:
        connector.disconnect()

    failed = [k for k, v in results.items() if isinstance(v, Exception)]
    if failed:
        logger.warning("Stage 0: fetch failures: %s", failed)

    return [p for p in PAIRS if (output_dir / f"{p}_{TIMEFRAME}.csv").exists()]


def _sanity_backtest(pairs: list[str], min_quality_score: float = 55.0) -> list[SanityResult]:
    """Stage 1: run current-config backtest per pair."""
    results = []
    for pair in pairs:
        logger.info("Stage 1: sanity backtest %s", pair)
        try:
            df = load_pair(pair, TIMEFRAME)
        except FileNotFoundError:
            logger.warning("Stage 1: no data for %s, skipping", pair)
            continue
        config = BacktestConfig(
            initial_balance=71_000.0,            # post-bleed balance
            risk_per_trade=0.005,                # 0.5% validation-window risk
            min_quality_score=min_quality_score,
            min_rr=2.0,
            signal_types=["reversal", "pullback", "buildup", "bos"],
            spread_pips=1.5,
        )
        out = run_backtest(df, pair=pair, timeframe=TIMEFRAME, config=config)
        m = out["metrics"]
        results.append(SanityResult(
            pair=pair,
            n_trades=int(getattr(m, "total_trades", 0)),
            win_rate=float(getattr(m, "win_rate", 0.0)),
            expectancy_r=float(getattr(m, "expectancy", 0.0)),
            profit_factor=float(getattr(m, "profit_factor", 0.0) or 0.0),
            sharpe=float(getattr(m, "sharpe_ratio", 0.0) or 0.0),
            total_return_pct=float(getattr(m, "total_return_pct", 0.0)),
            max_drawdown_pct=float(getattr(m, "max_drawdown_pct", 0.0)),
            first_bar=str(df.index[0]),
            last_bar=str(df.index[-1]),
        ))
    return results


def _walkforward(pairs: list[str]) -> dict[str, dict]:
    """Stage 2: walk-forward optimization per pair."""
    out = {}
    for pair in pairs:
        logger.info("Stage 2: walk-forward optimization %s", pair)
        try:
            df = load_pair(pair, TIMEFRAME)
        except FileNotFoundError:
            continue
        try:
            result = walk_forward_optimize(
                df,
                pair=pair,
                timeframe=TIMEFRAME,
                param_grid=WF_PARAM_GRID,
                in_sample_pct=WF_IS_PCT,
                n_folds=WF_FOLDS,
                scoring="expectancy",
            )
        except Exception as e:
            logger.exception("Stage 2: walkforward failed for %s", pair)
            out[pair] = {"error": str(e)}
            continue

        # Make JSON-serializable (BacktestMetrics → dict)
        folds_serial = []
        for f in result.get("fold_results", []):
            folds_serial.append({
                "fold": f["fold"],
                "best_params": f["best_params"],
                "is_score": f["is_score"],
                "oos_score": f["oos_score"],
                "is_metrics": _metrics_to_dict(f["is_metrics"]),
                "oos_metrics": _metrics_to_dict(f["oos_metrics"]),
            })
        out[pair] = {
            "fold_results": folds_serial,
            "best_params": result.get("best_params"),
            "oos_metrics": _metrics_to_dict(result.get("oos_metrics")),
        }
    return out


def _metrics_to_dict(m) -> dict:
    if m is None:
        return {}
    if hasattr(m, "__dict__"):
        return {k: (v if isinstance(v, (int, float, str, bool, type(None))) else str(v))
                for k, v in m.__dict__.items()}
    return {"value": str(m)}


def _summarize(sanity: list[SanityResult], wf: dict[str, dict], elapsed: float) -> str:
    """Generate the human-readable markdown digest."""
    lines = [
        f"# Overnight Backtest — {date.today().isoformat()}",
        "",
        f"> Generated by `src.backtest.overnight`. Runtime: {elapsed:.1f}s.",
        f"> Config: H1, USD-quoted pairs ({', '.join(PAIRS)}), {CANDLE_COUNT}-bar OHLC per pair.",
        f"> Spread: 1.5 pips. Risk: 0.5%. min_rr: 2.0 baseline.",
        "",
        "## Stage 1 — Sanity backtest (current production config)",
        "",
        "| pair | trades | WR | exp. (R) | PF | Sharpe | return | max DD | window |",
        "|------|-------:|-----:|---------:|-----:|-------:|-------:|-------:|--------|",
    ]
    if sanity:
        agg_trades = sum(r.n_trades for r in sanity)
        agg_return = sum(r.total_return_pct for r in sanity)
        for r in sanity:
            lines.append(
                f"| {r.pair} | {r.n_trades} | {r.win_rate:.1%} | "
                f"{r.expectancy_r:+.3f} | {r.profit_factor:.2f} | "
                f"{r.sharpe:+.2f} | {r.total_return_pct:+.1f}% | "
                f"{r.max_drawdown_pct:.1f}% | {r.first_bar[:10]} → {r.last_bar[:10]} |"
            )
        lines.append("")
        lines.append(f"**Aggregate**: {agg_trades} trades, "
                     f"sum-of-pair returns {agg_return:+.1f}%.")
    else:
        lines.append("(no results — data missing for all pairs)")
    lines.append("")

    lines.append("## Stage 2 — Walk-forward optimization")
    lines.append("")
    lines.append(
        f"Param grid: `min_quality_score` ∈ {WF_PARAM_GRID['min_quality_score']}, "
        f"`min_rr` ∈ {WF_PARAM_GRID['min_rr']}, "
        f"`risk_per_trade` ∈ {WF_PARAM_GRID['risk_per_trade']}. "
        f"{WF_FOLDS} folds, {int(WF_IS_PCT*100)}% in-sample / {int((1-WF_IS_PCT)*100)}% OOS."
    )
    lines.append("")

    for pair in PAIRS:
        if pair not in wf:
            continue
        data = wf[pair]
        lines.append(f"### {pair}")
        lines.append("")
        if "error" in data:
            lines.append(f"FAILED — {data['error']}")
            lines.append("")
            continue
        bp = data.get("best_params") or {}
        lines.append("| fold | best params | IS score | OOS score | OOS-vs-IS |")
        lines.append("|-----:|-------------|---------:|----------:|----------:|")
        for f in data.get("fold_results", []):
            params_str = ", ".join(f"{k}={v}" for k, v in f["best_params"].items())
            delta = f["oos_score"] - f["is_score"]
            lines.append(
                f"| {f['fold']} | {params_str} | "
                f"{f['is_score']:+.3f} | {f['oos_score']:+.3f} | {delta:+.3f} |"
            )
        if bp:
            lines.append("")
            lines.append(f"**Most robust (best avg OOS)**: `{bp}`")
        lines.append("")

    lines.append("## How to read this")
    lines.append("")
    lines.append(
        "- **OOS score collapsing vs IS** (delta strongly negative) = overfit. "
        "Don't deploy that param set.\n"
        "- **OOS comparable to IS across folds** = robust. Candidate for deployment.\n"
        "- **Sanity expectancy > 0R AND walk-forward OOS > 0** = real edge candidate. "
        "Stage gate: PSR vs 0 ≥ 50% on a 50-trade live window before scaling risk.\n"
        "- **All sanity expectancies < 0** = strategy doesn't have edge on H1 majors at "
        "current spread. Pivot to a different timeframe, signal mix, or asset class."
    )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true",
                   help="Verify data availability and config, but skip the backtests")
    p.add_argument("--smoke", action="store_true",
                   help="Fast end-to-end smoke test: stage 1 only on EUR_USD")
    p.add_argument("--data-dir", default="data/historical",
                   help="OHLC CSV cache directory (default: data/historical)")
    args = p.parse_args(argv)

    today = date.today().isoformat()
    out_dir = OUTPUT_ROOT / today
    out_dir.mkdir(parents=True, exist_ok=True)

    file_handler = logging.FileHandler(out_dir / "run.log", mode="w")
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s"
    ))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(logging.StreamHandler(sys.stdout))

    logger.info("overnight backtest starting; output → %s", out_dir)
    logger.info("dry_run=%s", args.dry_run)

    start = time.time()

    try:
        data_dir = Path(args.data_dir)
        pairs = _ensure_data(data_dir)
        logger.info("data ready for: %s", pairs)

        if args.dry_run:
            logger.info("dry-run: skipping backtest stages")
            print(f"\nDry run OK. Data ready in {data_dir}. Output dir: {out_dir}")
            return 0

        if args.smoke:
            logger.info("smoke test: stage 1 only on EUR_USD")
            smoke_pairs = [p for p in pairs if p == "EUR_USD"] or pairs[:1]
            sanity = _sanity_backtest(smoke_pairs)
            (out_dir / "sanity.json").write_text(
                json.dumps([asdict(r) for r in sanity], indent=2)
            )
            elapsed = time.time() - start
            summary = _summarize(sanity, {}, elapsed)
            (out_dir / "summary.md").write_text(summary)
            print(f"\nSmoke OK in {elapsed:.1f}s. Check {out_dir}/summary.md")
            return 0

        sanity = _sanity_backtest(pairs)
        (out_dir / "sanity.json").write_text(
            json.dumps([asdict(r) for r in sanity], indent=2)
        )
        logger.info("Stage 1 complete: %d sanity results", len(sanity))

        wf = _walkforward(pairs)
        (out_dir / "walkforward.json").write_text(json.dumps(wf, indent=2, default=str))
        logger.info("Stage 2 complete: %d walk-forward results", len(wf))

        elapsed = time.time() - start
        summary = _summarize(sanity, wf, elapsed)
        (out_dir / "summary.md").write_text(summary)
        logger.info("digest written: %s", out_dir / "summary.md")
        print(f"\nDone in {elapsed:.1f}s. Read: {out_dir}/summary.md")
        return 0
    except Exception:
        logger.exception("overnight backtest failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
