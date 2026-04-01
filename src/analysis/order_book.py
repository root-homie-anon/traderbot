"""OANDA order book and position book analysis.

Uses OANDA's free client positioning data to derive a contrarian
sentiment signal. When retail is heavily one-sided, fade the crowd.
"""

import logging
from dataclasses import dataclass

from src.broker.oanda_connector import OandaConnector

logger = logging.getLogger("pa_bot")


@dataclass
class PositioningResult:
    """Retail positioning analysis for a pair."""

    pair: str
    long_pct: float        # % of retail traders long (0-100)
    short_pct: float       # % of retail traders short (0-100)
    bias: str              # "contrarian_buy", "contrarian_sell", "neutral"
    strength: float        # 0-100, how extreme the positioning is
    raw_ratio: float       # long/short ratio

    @property
    def confluence_boost(self) -> float:
        """Return a multiplier for quality score based on positioning.

        Contrarian signal aligned with trade direction gets a boost.
        Neutral positioning returns 1.0 (no effect).
        """
        if self.strength < 20:
            return 1.0  # Not extreme enough to matter
        # Scale from 1.0 to 1.15 based on strength
        return 1.0 + (self.strength / 100) * 0.15


class OrderBookAnalyzer:
    """Analyze OANDA order/position books for sentiment signals."""

    def __init__(self, connector: OandaConnector):
        self.connector = connector
        self._cache: dict[str, PositioningResult] = {}
        self._cache_cycle: int = -1

    def get_positioning(
        self, pair: str, cycle: int = 0,
    ) -> PositioningResult | None:
        """Get retail positioning for a pair.

        Caches results per cycle to avoid redundant API calls.
        """
        # Return cached result if same cycle
        if cycle == self._cache_cycle and pair in self._cache:
            return self._cache[pair]

        # Reset cache on new cycle
        if cycle != self._cache_cycle:
            self._cache.clear()
            self._cache_cycle = cycle

        result = self._fetch_positioning(pair)
        if result:
            self._cache[pair] = result
        return result

    def _fetch_positioning(self, pair: str) -> PositioningResult | None:
        """Fetch position book from OANDA and calculate sentiment."""
        try:
            resp = self.connector._request(
                "GET",
                f"/v3/instruments/{pair}/positionBook",
            )
        except Exception as e:
            logger.debug("Failed to fetch position book for %s: %s", pair, e)
            return None

        position_book = resp.get("positionBook", {})
        buckets = position_book.get("buckets", [])

        if not buckets:
            return None

        # Sum up long vs short percentages across all price buckets
        total_long = sum(float(b.get("longCountPercent", 0)) for b in buckets)
        total_short = sum(float(b.get("shortCountPercent", 0)) for b in buckets)

        # Normalize to percentages
        total = total_long + total_short
        if total == 0:
            return None

        long_pct = (total_long / total) * 100
        short_pct = (total_short / total) * 100
        ratio = total_long / total_short if total_short > 0 else float("inf")

        # Determine contrarian bias
        # >60% one side = moderate signal, >70% = strong signal
        if long_pct >= 60:
            bias = "contrarian_sell"
            strength = min(100, (long_pct - 50) * 2)  # 60% → 20, 75% → 50, 100% → 100
        elif short_pct >= 60:
            bias = "contrarian_buy"
            strength = min(100, (short_pct - 50) * 2)
        else:
            bias = "neutral"
            strength = 0.0

        return PositioningResult(
            pair=pair,
            long_pct=round(long_pct, 1),
            short_pct=round(short_pct, 1),
            bias=bias,
            strength=round(strength, 1),
            raw_ratio=round(ratio, 3),
        )

    def is_aligned(self, pair: str, direction: str, cycle: int = 0) -> tuple[bool, float]:
        """Check if trade direction aligns with contrarian positioning.

        Args:
            pair: currency pair
            direction: "buy" or "sell"
            cycle: current cycle number for caching

        Returns:
            (is_aligned, strength) — True if contrarian signal matches direction
        """
        pos = self.get_positioning(pair, cycle)
        if not pos:
            return False, 0.0

        if direction == "buy" and pos.bias == "contrarian_buy":
            return True, pos.strength
        if direction == "sell" and pos.bias == "contrarian_sell":
            return True, pos.strength

        return False, pos.strength
