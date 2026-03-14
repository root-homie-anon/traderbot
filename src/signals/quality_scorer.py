"""6-factor quality scoring for trade signals.

Factors:
1. Backtest performance (historical win rate for this setup type)
2. Live performance (recent win rate)
3. Confluence score (multi-TF alignment)
4. Trend strength
5. Market regime suitability
6. Risk/Reward ratio quality
"""

from dataclasses import dataclass

from src.analysis.confluence import ConfluenceResult
from src.analysis.trend_strength import TrendStrengthResult
from src.analysis.market_structure import StructureResult, MarketPhase
from src.signals.signal_base import Signal


@dataclass
class QualityBreakdown:
    total_score: float              # 0-100
    backtest_score: float           # 0-100
    live_score: float               # 0-100
    confluence_score: float         # 0-100
    trend_score: float              # 0-100
    regime_score: float             # 0-100
    rr_score: float                 # 0-100
    grade: str                      # A, B, C, D, F


# Weights for each factor (must sum to 1.0)
FACTOR_WEIGHTS = {
    "backtest": 0.20,
    "live": 0.15,
    "confluence": 0.25,
    "trend": 0.15,
    "regime": 0.10,
    "rr": 0.15,
}


def score_signal(
    signal: Signal,
    confluence: ConfluenceResult | None = None,
    trend: TrendStrengthResult | None = None,
    structure: StructureResult | None = None,
    backtest_win_rate: float | None = None,
    live_win_rate: float | None = None,
) -> QualityBreakdown:
    """Calculate the 6-factor quality score for a signal.

    Args:
        signal: the trade signal to score
        confluence: confluence analysis result
        trend: trend strength result
        structure: market structure result
        backtest_win_rate: historical win rate (0-1) for this setup type
        live_win_rate: recent live win rate (0-1) for this setup type
    """
    # 1. Backtest performance
    if backtest_win_rate is not None:
        backtest_score = min(100, backtest_win_rate * 100 * 1.5)  # 66%+ = 100
    else:
        backtest_score = 50  # Neutral if no data

    # 2. Live performance
    if live_win_rate is not None:
        live_score = min(100, live_win_rate * 100 * 1.5)
    else:
        live_score = 50

    # 3. Confluence
    if confluence:
        confluence_score = (confluence.score / confluence.max_score) * 100
    else:
        confluence_score = signal.confluence_level / 6 * 100

    # 4. Trend strength
    if trend:
        trend_aligned = (
            (signal.direction.value == "buy" and trend.direction == "bullish")
            or (signal.direction.value == "sell" and trend.direction == "bearish")
        )
        trend_score = trend.score if trend_aligned else max(0, trend.score - 30)
    else:
        trend_score = 50

    # 5. Market regime suitability
    if structure:
        regime_score = _regime_suitability(signal, structure)
    else:
        regime_score = 50

    # 6. Risk/Reward ratio quality
    rr = signal.risk_reward_ratio
    if rr >= 3.0:
        rr_score = 100
    elif rr >= 2.0:
        rr_score = 80
    elif rr >= 1.5:
        rr_score = 60
    elif rr >= 1.0:
        rr_score = 40
    else:
        rr_score = 20

    # Weighted total
    total = (
        backtest_score * FACTOR_WEIGHTS["backtest"]
        + live_score * FACTOR_WEIGHTS["live"]
        + confluence_score * FACTOR_WEIGHTS["confluence"]
        + trend_score * FACTOR_WEIGHTS["trend"]
        + regime_score * FACTOR_WEIGHTS["regime"]
        + rr_score * FACTOR_WEIGHTS["rr"]
    )

    # Grade
    if total >= 80:
        grade = "A"
    elif total >= 65:
        grade = "B"
    elif total >= 50:
        grade = "C"
    elif total >= 35:
        grade = "D"
    else:
        grade = "F"

    return QualityBreakdown(
        total_score=total,
        backtest_score=backtest_score,
        live_score=live_score,
        confluence_score=confluence_score,
        trend_score=trend_score,
        regime_score=regime_score,
        rr_score=rr_score,
        grade=grade,
    )


def _regime_suitability(signal: Signal, structure: StructureResult) -> float:
    """Score how suitable the signal is for the current market regime."""
    phase = structure.phase

    # Reversal signals work best in accumulation/distribution
    if signal.signal_type.value == "reversal":
        if phase in (MarketPhase.ACCUMULATION, MarketPhase.DISTRIBUTION):
            return 90
        elif phase in (MarketPhase.ADVANCING, MarketPhase.DECLINING):
            return 40  # Counter-trend reversal is riskier
        return 50

    # Pullback signals work best in trending markets
    if signal.signal_type.value == "pullback":
        if phase == MarketPhase.ADVANCING and signal.direction.value == "buy":
            return 95
        elif phase == MarketPhase.DECLINING and signal.direction.value == "sell":
            return 95
        return 30

    # BOS signals are best in trending or transitioning markets
    if signal.signal_type.value == "bos":
        if phase in (MarketPhase.ADVANCING, MarketPhase.DECLINING):
            return 85
        elif phase in (MarketPhase.ACCUMULATION, MarketPhase.DISTRIBUTION):
            return 70  # Could be breakout from range
        return 50

    # Buildup signals work in most regimes
    if signal.signal_type.value == "buildup":
        return 70

    return 50


def filter_signals(
    signals: list[Signal],
    min_quality: float = 50,
    **kwargs,
) -> list[tuple[Signal, QualityBreakdown]]:
    """Score and filter signals, returning only those above min_quality."""
    scored = []
    for signal in signals:
        breakdown = score_signal(signal, **kwargs)
        if breakdown.total_score >= min_quality:
            signal.quality_score = breakdown.total_score
            scored.append((signal, breakdown))

    scored.sort(key=lambda x: x[1].total_score, reverse=True)
    return scored
