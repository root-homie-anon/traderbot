"""Economic calendar filter — block trades around high-impact news events.

Fetches event data from ForexFactory-compatible sources and caches it daily.
Provides a simple check: should we avoid trading this currency right now?
"""

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from src.config import DATA_DIR

logger = logging.getLogger("pa_bot")

CACHE_FILE = DATA_DIR / "calendar_cache.json"
CACHE_MAX_AGE_HOURS = 12

# Currency mapping: OANDA pair -> affected currencies
PAIR_CURRENCIES = {
    "EUR_USD": ["EUR", "USD"],
    "GBP_USD": ["GBP", "USD"],
    "USD_JPY": ["USD", "JPY"],
    "AUD_USD": ["AUD", "USD"],
    "EUR_GBP": ["EUR", "GBP"],
    "USD_CAD": ["USD", "CAD"],
    "NZD_USD": ["NZD", "USD"],
    "EUR_JPY": ["EUR", "JPY"],
    "GBP_JPY": ["GBP", "JPY"],
    "AUD_JPY": ["AUD", "JPY"],
}

# Minutes to avoid before and after a high-impact event
BLACKOUT_BEFORE_MIN = 30
BLACKOUT_AFTER_MIN = 30


@dataclass
class CalendarEvent:
    timestamp: datetime
    currency: str
    impact: str  # "high", "medium", "low"
    title: str


class EconomicCalendar:
    """Fetches and caches economic calendar events, provides trade filtering."""

    def __init__(
        self,
        blackout_before: int = BLACKOUT_BEFORE_MIN,
        blackout_after: int = BLACKOUT_AFTER_MIN,
    ):
        self.blackout_before = timedelta(minutes=blackout_before)
        self.blackout_after = timedelta(minutes=blackout_after)
        self._events: list[CalendarEvent] = []
        self._last_fetch: datetime | None = None

    def refresh(self) -> None:
        """Load events from cache or fetch fresh data."""
        if self._cache_is_fresh():
            self._load_cache()
            return

        events = self._fetch_events()
        if events:
            self._events = events
            self._last_fetch = datetime.now(timezone.utc)
            self._save_cache()
        elif not self._events:
            # Fetch failed and no cached data — load stale cache if exists
            self._load_cache()

    def is_blackout(self, pair: str, utc_now: datetime | None = None) -> tuple[bool, str]:
        """Check if a pair is in a news blackout window.

        Returns (is_blocked, reason_string).
        """
        if utc_now is None:
            utc_now = datetime.now(timezone.utc)

        currencies = PAIR_CURRENCIES.get(pair, [])
        if not currencies:
            return False, ""

        for event in self._events:
            if event.impact != "high":
                continue
            if event.currency not in currencies:
                continue

            window_start = event.timestamp - self.blackout_before
            window_end = event.timestamp + self.blackout_after

            if window_start <= utc_now <= window_end:
                mins_to_event = (event.timestamp - utc_now).total_seconds() / 60
                if mins_to_event > 0:
                    reason = f"News blackout: {event.title} ({event.currency}) in {mins_to_event:.0f}min"
                else:
                    reason = f"News blackout: {event.title} ({event.currency}) {abs(mins_to_event):.0f}min ago"
                return True, reason

        return False, ""

    def get_upcoming_events(
        self, hours_ahead: int = 24, impact: str = "high",
    ) -> list[CalendarEvent]:
        """Get upcoming events within the next N hours."""
        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(hours=hours_ahead)
        return [
            e for e in self._events
            if e.impact == impact and now <= e.timestamp <= cutoff
        ]

    def _fetch_events(self) -> list[CalendarEvent]:
        """Fetch events from nomi.com free forex calendar API."""
        events = []
        today = datetime.now(timezone.utc).date()

        # Fetch today and tomorrow to cover overnight events
        for day_offset in range(2):
            target_date = today + timedelta(days=day_offset)
            url = f"https://nfs.faireconomy.media/ff_calendar_thisweek.json"

            try:
                resp = requests.get(url, timeout=10)
                resp.raise_for_status()
                data = resp.json()

                for item in data:
                    impact = item.get("impact", "").lower()
                    if impact not in ("high", "medium"):
                        continue

                    # Parse date and time
                    date_str = item.get("date", "")
                    if not date_str:
                        continue

                    try:
                        # Format: "2026-03-31T12:30:00-04:00" or similar
                        ts = datetime.fromisoformat(date_str)
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=timezone.utc)
                        else:
                            ts = ts.astimezone(timezone.utc)
                    except (ValueError, TypeError):
                        continue

                    events.append(CalendarEvent(
                        timestamp=ts,
                        currency=item.get("country", "").upper(),
                        impact=impact,
                        title=item.get("title", "Unknown Event"),
                    ))

                # Only need one successful fetch (it returns the full week)
                if events:
                    break

            except Exception as e:
                logger.warning("Failed to fetch economic calendar: %s", e)
                continue

        logger.info("Economic calendar: loaded %d high/medium impact events", len(events))
        return events

    def _cache_is_fresh(self) -> bool:
        """Check if the cache file exists and is recent enough."""
        if not CACHE_FILE.exists():
            return False
        try:
            mtime = datetime.fromtimestamp(CACHE_FILE.stat().st_mtime, tz=timezone.utc)
            return (datetime.now(timezone.utc) - mtime).total_seconds() < CACHE_MAX_AGE_HOURS * 3600
        except Exception:
            return False

    def _load_cache(self) -> None:
        """Load events from the cache file."""
        try:
            with open(CACHE_FILE) as f:
                data = json.load(f)
            self._events = [
                CalendarEvent(
                    timestamp=datetime.fromisoformat(e["timestamp"]),
                    currency=e["currency"],
                    impact=e["impact"],
                    title=e["title"],
                )
                for e in data
            ]
            logger.debug("Loaded %d events from calendar cache", len(self._events))
        except Exception as e:
            logger.warning("Failed to load calendar cache: %s", e)

    def _save_cache(self) -> None:
        """Save current events to cache file."""
        try:
            data = [
                {
                    "timestamp": e.timestamp.isoformat(),
                    "currency": e.currency,
                    "impact": e.impact,
                    "title": e.title,
                }
                for e in self._events
            ]
            with open(CACHE_FILE, "w") as f:
                json.dump(data, f)
        except Exception as e:
            logger.warning("Failed to save calendar cache: %s", e)
