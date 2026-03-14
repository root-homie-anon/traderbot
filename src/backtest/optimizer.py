"""Test configurations and find optimal parameters."""

import itertools
import logging
from dataclasses import dataclass

import pandas as pd

from src.backtest.backtester import run_backtest, BacktestConfig
from src.backtest.metrics import BacktestMetrics

logger = logging.getLogger("pa_bot")


@dataclass
class OptimizationResult:
    """Result of a single parameter combination."""

    params: dict
    metrics: BacktestMetrics
    score: float


def optimize(
    df: pd.DataFrame,
    pair: str = "EUR_USD",
    timeframe: str = "H1",
    param_grid: dict | None = None,
    scoring: str = "expectancy",
    top_n: int = 5,
) -> list[OptimizationResult]:
    """Run backtest across parameter combinations and rank results.

    Args:
        df: OHLC data
        pair: trading pair
        timeframe: timeframe label
        param_grid: dict of parameter names to lists of values, e.g.
            {"risk_per_trade": [0.005, 0.01, 0.02], "min_quality_score": [40, 50, 60]}
        scoring: metric to optimize. One of:
            "expectancy", "sharpe_ratio", "profit_factor", "total_return_pct", "win_rate"
        top_n: number of top results to return

    Returns:
        list of OptimizationResult sorted by score descending
    """
    if param_grid is None:
        param_grid = {
            "risk_per_trade": [0.005, 0.01, 0.02],
            "min_quality_score": [40, 50, 60],
            "min_rr": [1.5, 2.0, 2.5],
        }

    # Generate all combinations
    keys = list(param_grid.keys())
    values = list(param_grid.values())
    combinations = list(itertools.product(*values))

    results = []
    for combo in combinations:
        params = dict(zip(keys, combo))

        config = BacktestConfig(**params)

        try:
            result = run_backtest(df, pair=pair, timeframe=timeframe, config=config)
            metrics = result["metrics"]

            score = getattr(metrics, scoring, 0)
            if score is None or (isinstance(score, float) and score != score):  # NaN check
                score = 0

            results.append(OptimizationResult(
                params=params,
                metrics=metrics,
                score=float(score),
            ))
        except Exception as e:
            logger.warning(f"Optimization combo {params} failed: {e}")

    results.sort(key=lambda r: r.score, reverse=True)
    return results[:top_n]


def walk_forward_optimize(
    df: pd.DataFrame,
    pair: str = "EUR_USD",
    timeframe: str = "H1",
    param_grid: dict | None = None,
    in_sample_pct: float = 0.7,
    n_folds: int = 3,
    scoring: str = "expectancy",
) -> dict:
    """Walk-forward optimization with in-sample/out-of-sample splits.

    Splits data into n_folds. For each fold, optimizes on in-sample
    and validates on out-of-sample.

    Returns:
        dict with 'fold_results', 'best_params', 'oos_metrics'
    """
    total_bars = len(df)
    fold_size = total_bars // n_folds
    fold_results = []

    for fold in range(n_folds):
        start = fold * fold_size
        end = min(start + fold_size, total_bars)

        fold_data = df.iloc[start:end]
        split = int(len(fold_data) * in_sample_pct)

        in_sample = fold_data.iloc[:split]
        out_of_sample = fold_data.iloc[split:]

        if len(in_sample) < 100 or len(out_of_sample) < 30:
            continue

        # Optimize on in-sample
        best = optimize(in_sample, pair, timeframe, param_grid, scoring, top_n=1)
        if not best:
            continue

        best_params = best[0].params
        config = BacktestConfig(**best_params)

        # Validate on out-of-sample
        oos_result = run_backtest(out_of_sample, pair, timeframe, config)

        fold_results.append({
            "fold": fold,
            "best_params": best_params,
            "is_metrics": best[0].metrics,
            "oos_metrics": oos_result["metrics"],
            "is_score": best[0].score,
            "oos_score": float(getattr(oos_result["metrics"], scoring, 0)),
        })

    # Find most robust params (best average OOS score)
    if fold_results:
        best_params = max(fold_results, key=lambda f: f["oos_score"])["best_params"]
        oos_scores = [f["oos_score"] for f in fold_results]
    else:
        best_params = {}
        oos_scores = []

    return {
        "fold_results": fold_results,
        "best_params": best_params,
        "avg_oos_score": sum(oos_scores) / len(oos_scores) if oos_scores else 0,
    }
