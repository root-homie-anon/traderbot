"""CFTC Commitment of Traders (COT) data — institutional positioning.

Fetches weekly COT reports from the CFTC and provides institutional
net positioning as a directional bias signal. Updated every Friday.

Institutional (non-commercial) traders are the "smart money" — when
they're heavily long or short, it provides a directional bias.
"""

import csv
import io
import json
import logging
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from src.config import DATA_DIR

logger = logging.getLogger("pa_bot")

CACHE_FILE = DATA_DIR / "cot_cache.json"
CACHE_MAX_AGE_HOURS = 24 * 4  # COT updates weekly, cache for 4 days

# CFTC market names for forex futures (as they appear in the CSV)
CURRENCY_MARKET_NAMES = {
    "EUR": "EURO FX",
    "GBP": "BRITISH POUND",
    "JPY": "JAPANESE YEN",
    "AUD": "AUSTRALIAN DOLLAR",
    "CAD": "CANADIAN DOLLAR",
    "NZD": "NZ DOLLAR",
    "CHF": "SWISS FRANC",
}

# Map OANDA pairs to the currency whose COT data matters most
# For pairs like EUR_USD, we check EUR positioning (non-commercial)
PAIR_COT_CURRENCY = {
    "EUR_USD": "EUR",
    "GBP_USD": "GBP",
    "USD_JPY": "JPY",
    "AUD_USD": "AUD",
    "USD_CAD": "CAD",
    "NZD_USD": "NZD",
    "EUR_GBP": "EUR",  # Primary currency
    "EUR_JPY": "EUR",
    "GBP_JPY": "GBP",
    "AUD_JPY": "AUD",
}


@dataclass
class COTPosition:
    """Institutional positioning for a currency."""

    currency: str
    report_date: str
    non_commercial_long: int
    non_commercial_short: int
    net_position: int           # long - short
    net_change: int             # change from previous week
    pct_long: float             # % of non-commercial that is long
    bias: str                   # "bullish", "bearish", or "neutral"
    strength: float             # 0-100, how extreme the positioning is


class COTAnalyzer:
    """Fetch and analyze CFTC Commitment of Traders data."""

    def __init__(self):
        self._positions: dict[str, COTPosition] = {}
        self._last_fetch: datetime | None = None

    def refresh(self) -> None:
        """Load COT data from cache or fetch fresh."""
        if self._cache_is_fresh():
            self._load_cache()
            return

        positions = self._fetch_cot()
        if positions:
            self._positions = positions
            self._last_fetch = datetime.now(timezone.utc)
            self._save_cache()
        elif not self._positions:
            self._load_cache()

    def get_bias(self, pair: str) -> COTPosition | None:
        """Get institutional positioning bias for a pair."""
        currency = PAIR_COT_CURRENCY.get(pair)
        if not currency:
            return None
        return self._positions.get(currency)

    def is_aligned(self, pair: str, direction: str) -> tuple[bool, float]:
        """Check if trade direction aligns with institutional positioning.

        For pairs where the COT currency is the base (EUR_USD, GBP_USD, AUD_USD, NZD_USD):
          - Institutions long EUR → bullish EUR_USD → aligns with "buy"
        For pairs where the COT currency is the quote (USD_JPY, USD_CAD):
          - Institutions long JPY → bearish USD_JPY → aligns with "sell"
        """
        pos = self.get_bias(pair)
        if not pos or pos.bias == "neutral":
            return False, 0.0

        currency = PAIR_COT_CURRENCY.get(pair, "")

        # Determine if the COT currency is base or quote
        base = pair.split("_")[0] if "_" in pair else ""
        is_base_currency = (currency == base)

        if is_base_currency:
            # EUR long → buy EUR_USD
            aligned = (
                (pos.bias == "bullish" and direction == "buy")
                or (pos.bias == "bearish" and direction == "sell")
            )
        else:
            # JPY long → sell USD_JPY (JPY strengthens)
            aligned = (
                (pos.bias == "bullish" and direction == "sell")
                or (pos.bias == "bearish" and direction == "buy")
            )

        return aligned, pos.strength

    def _fetch_cot(self) -> dict[str, COTPosition]:
        """Fetch latest COT data from CFTC legacy futures-only report."""
        positions = {}

        year = datetime.now(timezone.utc).year
        url = f"https://www.cftc.gov/files/dea/history/deacot{year}.zip"

        try:
            resp = requests.get(url, timeout=30)
            resp.raise_for_status()

            with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
                with z.open(z.namelist()[0]) as f:
                    reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8"))
                    rows = list(reader)

            for currency, market_name in CURRENCY_MARKET_NAMES.items():
                matching = [
                    r for r in rows
                    if market_name in r.get("Market and Exchange Names", "").upper()
                ]

                if not matching:
                    continue

                matching.sort(
                    key=lambda r: r.get("As of Date in Form YYYY-MM-DD", ""),
                    reverse=True,
                )

                latest = matching[0]
                prev = matching[1] if len(matching) > 1 else None

                try:
                    nc_long = int(latest.get("Noncommercial Positions-Long (All)", "0").strip())
                    nc_short = int(latest.get("Noncommercial Positions-Short (All)", "0").strip())
                except (ValueError, TypeError):
                    continue

                net = nc_long - nc_short
                total = nc_long + nc_short
                pct_long = (nc_long / total * 100) if total > 0 else 50.0

                net_change = 0
                if prev:
                    try:
                        prev_long = int(prev.get("Noncommercial Positions-Long (All)", "0").strip())
                        prev_short = int(prev.get("Noncommercial Positions-Short (All)", "0").strip())
                        net_change = net - (prev_long - prev_short)
                    except (ValueError, TypeError):
                        pass

                if pct_long >= 60:
                    bias = "bullish"
                    strength = min(100, (pct_long - 50) * 2)
                elif pct_long <= 40:
                    bias = "bearish"
                    strength = min(100, (50 - pct_long) * 2)
                else:
                    bias = "neutral"
                    strength = 0.0

                positions[currency] = COTPosition(
                    currency=currency,
                    report_date=latest.get("As of Date in Form YYYY-MM-DD", ""),
                    non_commercial_long=nc_long,
                    non_commercial_short=nc_short,
                    net_position=net,
                    net_change=net_change,
                    pct_long=round(pct_long, 1),
                    bias=bias,
                    strength=round(strength, 1),
                )

            logger.info(
                "COT data loaded: %d currencies | %s",
                len(positions),
                ", ".join(f"{c}={p.bias}" for c, p in positions.items()),
            )

        except Exception as e:
            logger.warning("Failed to fetch COT data: %s", e)

        return positions

    def _cache_is_fresh(self) -> bool:
        if not CACHE_FILE.exists():
            return False
        try:
            mtime = datetime.fromtimestamp(CACHE_FILE.stat().st_mtime, tz=timezone.utc)
            return (datetime.now(timezone.utc) - mtime).total_seconds() < CACHE_MAX_AGE_HOURS * 3600
        except Exception:
            return False

    def _load_cache(self) -> None:
        try:
            with open(CACHE_FILE) as f:
                data = json.load(f)
            self._positions = {
                k: COTPosition(**v) for k, v in data.items()
            }
            logger.debug("Loaded COT data from cache: %d currencies", len(self._positions))
        except Exception as e:
            logger.warning("Failed to load COT cache: %s", e)

    def _save_cache(self) -> None:
        try:
            data = {}
            for k, v in self._positions.items():
                data[k] = {
                    "currency": v.currency,
                    "report_date": v.report_date,
                    "non_commercial_long": v.non_commercial_long,
                    "non_commercial_short": v.non_commercial_short,
                    "net_position": v.net_position,
                    "net_change": v.net_change,
                    "pct_long": v.pct_long,
                    "bias": v.bias,
                    "strength": v.strength,
                }
            with open(CACHE_FILE, "w") as f:
                json.dump(data, f)
        except Exception as e:
            logger.warning("Failed to save COT cache: %s", e)
