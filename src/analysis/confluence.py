"""Multi-timeframe confluence alignment scoring.

Confluence measures how many factors align for a trade setup.
Higher confluence = higher probability trade.

Factors checked:
1. Trend alignment across timeframes
2. S/R level proximity
3. Pattern presence
4. Trend strength
5. Market structure agreement
6. BOS alignment
"""

import pandas as pd
from dataclasses import dataclass

from src.analysis.market_structure import classify_structure, MarketPhase
from src.analysis.trend_strength import calculate_trend_strength
from src.analysis.support_resistance import find_support_resistance, nearest_support, nearest_resistance
from src.analysis.price_action import detect_all_patterns, Direction
from src.analysis.break_of_structure import latest_bos, BOSType


@dataclass
class ConfluenceResult:
    score: int              # Number of factors aligned (0-6)
    max_score: int          # Maximum possible (6)
    factors: dict[str, bool]  # Which factors are aligned
    direction: str          # "bullish", "bearish", or "neutral"
    details: dict[str, str]   # Human-readable factor details


def calculate_confluence(
    df: pd.DataFrame,
    direction: str = "bullish",
    sr_proximity_pct: float = 0.005,
) -> ConfluenceResult:
    """Calculate confluence score for a potential trade direction.

    Args:
        df: OHLC DataFrame (single timeframe)
        direction: "bullish" or "bearish"
        sr_proximity_pct: how close price must be to S/R to count
    """
    factors = {}
    details = {}
    current_price = df["close"].iloc[-1]

    # 1. Market structure alignment
    structure = classify_structure(df)
    if direction == "bullish":
        struct_aligned = structure.phase in (MarketPhase.ADVANCING, MarketPhase.ACCUMULATION)
    else:
        struct_aligned = structure.phase in (MarketPhase.DECLINING, MarketPhase.DISTRIBUTION)
    factors["market_structure"] = struct_aligned
    details["market_structure"] = f"{structure.phase.value} (conf: {structure.confidence:.0f}%)"

    # 2. Trend strength
    trend = calculate_trend_strength(df)
    trend_aligned = (
        (direction == "bullish" and trend.direction == "bullish" and trend.score >= 40)
        or (direction == "bearish" and trend.direction == "bearish" and trend.score >= 40)
    )
    factors["trend_strength"] = trend_aligned
    details["trend_strength"] = f"{trend.direction} ({trend.score:.0f}/100)"

    # 3. S/R proximity (price near a level)
    levels = find_support_resistance(df)
    if direction == "bullish":
        nearest = nearest_support(levels, current_price)
        if nearest and abs(current_price - nearest.price) / current_price <= sr_proximity_pct:
            factors["sr_proximity"] = True
            details["sr_proximity"] = f"Near support @ {nearest.price:.5f} ({nearest.touches} touches)"
        else:
            factors["sr_proximity"] = False
            details["sr_proximity"] = "Not near support"
    else:
        nearest = nearest_resistance(levels, current_price)
        if nearest and abs(nearest.price - current_price) / current_price <= sr_proximity_pct:
            factors["sr_proximity"] = True
            details["sr_proximity"] = f"Near resistance @ {nearest.price:.5f} ({nearest.touches} touches)"
        else:
            factors["sr_proximity"] = False
            details["sr_proximity"] = "Not near resistance"

    # 4. Pattern presence (recent pattern in the right direction)
    patterns = detect_all_patterns(df)
    recent_patterns = [p for p in patterns if p.index >= len(df) - 5]
    target_dir = Direction.BULLISH if direction == "bullish" else Direction.BEARISH
    pattern_aligned = any(
        p.direction == target_dir or p.direction == Direction.NEUTRAL
        for p in recent_patterns
    )
    factors["pattern"] = pattern_aligned
    if recent_patterns:
        details["pattern"] = ", ".join(f"{p.type.value}" for p in recent_patterns[-3:])
    else:
        details["pattern"] = "No recent patterns"

    # 5. Break of structure alignment
    bos = latest_bos(df)
    if bos:
        bos_aligned = (
            (direction == "bullish" and bos.bos_type == BOSType.BULLISH)
            or (direction == "bearish" and bos.bos_type == BOSType.BEARISH)
        )
        factors["bos"] = bos_aligned
        details["bos"] = f"{bos.bos_type.value} BOS @ {bos.broken_level:.5f}"
    else:
        factors["bos"] = False
        details["bos"] = "No recent BOS"

    # 6. Higher highs/lows alignment
    if direction == "bullish":
        hl_aligned = structure.higher_highs and structure.higher_lows
    else:
        hl_aligned = structure.lower_highs and structure.lower_lows
    factors["swing_structure"] = hl_aligned
    details["swing_structure"] = (
        f"HH={structure.higher_highs} HL={structure.higher_lows} "
        f"LH={structure.lower_highs} LL={structure.lower_lows}"
    )

    score = sum(1 for v in factors.values() if v)

    return ConfluenceResult(
        score=score,
        max_score=len(factors),
        factors=factors,
        direction=direction,
        details=details,
    )


def multi_timeframe_confluence(
    dataframes: dict[str, pd.DataFrame],
    direction: str = "bullish",
) -> dict[str, ConfluenceResult]:
    """Calculate confluence across multiple timeframes.

    Args:
        dataframes: dict of timeframe label -> OHLC DataFrame
                    e.g. {"H1": df_1h, "H4": df_4h, "D": df_daily}
        direction: trade direction to check

    Returns:
        dict of timeframe -> ConfluenceResult
    """
    results = {}
    for tf, df in dataframes.items():
        results[tf] = calculate_confluence(df, direction)
    return results


def overall_confluence_score(results: dict[str, ConfluenceResult]) -> float:
    """Calculate weighted overall confluence from multi-TF results.

    Higher timeframes get more weight.
    """
    weights = {"M5": 0.5, "M15": 0.7, "H1": 1.0, "H4": 1.3, "D": 1.5, "W": 1.8}

    total_score = 0
    total_weight = 0

    for tf, result in results.items():
        w = weights.get(tf, 1.0)
        total_score += (result.score / result.max_score) * w * 100
        total_weight += w

    return total_score / total_weight if total_weight > 0 else 0
