"""Support/Resistance level finder with touch counting.

Uses pivot point detection and clustering to identify key S/R levels.
Levels are scored by the number of times price touches/reacts to them.
"""

import pandas as pd
import numpy as np
from dataclasses import dataclass


@dataclass
class Level:
    price: float
    touches: int
    level_type: str  # "support", "resistance", or "both"
    first_seen: pd.Timestamp
    last_touched: pd.Timestamp
    strength: float  # 0-100 based on touches and recency


def find_pivots(
    df: pd.DataFrame, left: int = 5, right: int = 5
) -> tuple[list[float], list[float]]:
    """Find swing highs and swing lows using pivot point detection.

    A swing high is a bar whose high is higher than `left` bars before
    and `right` bars after. Vice versa for swing lows.
    """
    swing_highs = []
    swing_lows = []

    for i in range(left, len(df) - right):
        # Swing high
        high = df["high"].iloc[i]
        if (high >= df["high"].iloc[i - left : i].max()
                and high >= df["high"].iloc[i + 1 : i + right + 1].max()):
            swing_highs.append((i, high, df.index[i]))

        # Swing low
        low = df["low"].iloc[i]
        if (low <= df["low"].iloc[i - left : i].min()
                and low <= df["low"].iloc[i + 1 : i + right + 1].min()):
            swing_lows.append((i, low, df.index[i]))

    return swing_highs, swing_lows


def cluster_levels(
    pivots: list[tuple], tolerance_pct: float = 0.002
) -> list[dict]:
    """Cluster nearby pivot prices into S/R levels.

    Pivots within tolerance_pct of each other are grouped into one level.
    """
    if not pivots:
        return []

    # Sort by price
    sorted_pivots = sorted(pivots, key=lambda x: x[1])
    clusters = []
    current_cluster = [sorted_pivots[0]]

    for pivot in sorted_pivots[1:]:
        avg_price = np.mean([p[1] for p in current_cluster])
        if abs(pivot[1] - avg_price) / avg_price <= tolerance_pct:
            current_cluster.append(pivot)
        else:
            clusters.append(current_cluster)
            current_cluster = [pivot]
    clusters.append(current_cluster)

    levels = []
    for cluster in clusters:
        prices = [p[1] for p in cluster]
        timestamps = [p[2] for p in cluster]
        levels.append({
            "price": np.mean(prices),
            "touches": len(cluster),
            "first_seen": min(timestamps),
            "last_touched": max(timestamps),
        })

    return levels


def count_touches(
    df: pd.DataFrame, level_price: float, tolerance_pct: float = 0.002
) -> int:
    """Count how many times price touched a level (within tolerance)."""
    upper = level_price * (1 + tolerance_pct)
    lower = level_price * (1 - tolerance_pct)

    touches = ((df["low"] <= upper) & (df["high"] >= lower)).sum()
    return int(touches)


def find_support_resistance(
    df: pd.DataFrame,
    pivot_left: int = 5,
    pivot_right: int = 5,
    cluster_tolerance: float = 0.002,
    min_touches: int = 2,
) -> list[Level]:
    """Main function: find all S/R levels with quality scoring.

    Returns levels sorted by strength (strongest first).
    """
    swing_highs, swing_lows = find_pivots(df, pivot_left, pivot_right)

    # Cluster resistance (from swing highs)
    resistance_levels = cluster_levels(swing_highs, cluster_tolerance)
    # Cluster support (from swing lows)
    support_levels = cluster_levels(swing_lows, cluster_tolerance)

    levels = []
    last_ts = df.index[-1]

    # Process resistance levels
    for lvl in resistance_levels:
        touches = count_touches(df, lvl["price"], cluster_tolerance)
        if touches < min_touches:
            continue

        # Recency factor: more recent = stronger
        days_since = (last_ts - lvl["last_touched"]).total_seconds() / 86400
        recency_score = max(0, 100 - days_since * 0.5)

        strength = min(100, touches * 15 + recency_score * 0.3)

        levels.append(Level(
            price=lvl["price"],
            touches=touches,
            level_type="resistance",
            first_seen=lvl["first_seen"],
            last_touched=lvl["last_touched"],
            strength=strength,
        ))

    # Process support levels
    for lvl in support_levels:
        touches = count_touches(df, lvl["price"], cluster_tolerance)
        if touches < min_touches:
            continue

        days_since = (last_ts - lvl["last_touched"]).total_seconds() / 86400
        recency_score = max(0, 100 - days_since * 0.5)

        strength = min(100, touches * 15 + recency_score * 0.3)

        levels.append(Level(
            price=lvl["price"],
            touches=touches,
            level_type="support",
            first_seen=lvl["first_seen"],
            last_touched=lvl["last_touched"],
            strength=strength,
        ))

    # Merge nearby support/resistance into "both"
    merged = _merge_nearby_levels(levels, cluster_tolerance)
    merged.sort(key=lambda x: x.strength, reverse=True)
    return merged


def _merge_nearby_levels(levels: list[Level], tolerance: float) -> list[Level]:
    """Merge support and resistance levels that are at similar prices."""
    if not levels:
        return []

    sorted_levels = sorted(levels, key=lambda x: x.price)
    merged = [sorted_levels[0]]

    for lvl in sorted_levels[1:]:
        prev = merged[-1]
        if abs(lvl.price - prev.price) / prev.price <= tolerance:
            # Merge: combine touches, keep strongest
            merged[-1] = Level(
                price=(prev.price + lvl.price) / 2,
                touches=prev.touches + lvl.touches,
                level_type="both" if prev.level_type != lvl.level_type else prev.level_type,
                first_seen=min(prev.first_seen, lvl.first_seen),
                last_touched=max(prev.last_touched, lvl.last_touched),
                strength=max(prev.strength, lvl.strength),
            )
        else:
            merged.append(lvl)

    return merged


def nearest_support(levels: list[Level], price: float) -> Level | None:
    """Find the nearest support level below the given price."""
    supports = [l for l in levels if l.price < price and l.level_type in ("support", "both")]
    if not supports:
        return None
    return max(supports, key=lambda l: l.price)


def nearest_resistance(levels: list[Level], price: float) -> Level | None:
    """Find the nearest resistance level above the given price."""
    resistances = [l for l in levels if l.price > price and l.level_type in ("resistance", "both")]
    if not resistances:
        return None
    return min(resistances, key=lambda l: l.price)
