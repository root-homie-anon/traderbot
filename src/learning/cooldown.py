"""Re-entry cooldown guard.

Prevents the same (pair, signal_type, direction) setup from re-firing
immediately after a stop-out. Closes the failure mode where one losing
idea triggers 4-6 times in minutes because the local conditions still
satisfy the detector right after the stop hits.

Cooldown duration = max(60 min, 4 × signal timeframe in minutes).
Persisted to state/cooldowns.json so it survives restarts.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

TIMEFRAME_MINUTES: dict[str, int] = {
    "M1": 1, "M5": 5, "M15": 15, "M30": 30,
    "H1": 60, "H4": 240,
    "D": 1440, "W": 10080,
}

MIN_COOLDOWN_MINUTES = 60
BARS_MULTIPLIER = 4


def cooldown_minutes(timeframe: str) -> int:
    """Compute cooldown duration for a given signal timeframe."""
    tf_min = TIMEFRAME_MINUTES.get(timeframe, 60)
    return max(MIN_COOLDOWN_MINUTES, BARS_MULTIPLIER * tf_min)


def _key(pair: str, signal_type: str, direction: str) -> str:
    return f"{pair}|{signal_type}|{direction}"


@dataclass
class CooldownEntry:
    pair: str
    signal_type: str
    direction: str
    locked_at: str  # ISO timestamp of triggering stop-out
    unlock_at: str  # ISO timestamp when re-entry is allowed
    timeframe: str
    triggering_order_id: str | None = None


@dataclass
class CooldownGuard:
    """In-memory cooldown registry with JSON persistence.

    Use:
        guard = CooldownGuard(state_path=Path("state/cooldowns.json"))
        guard.load()
        if guard.is_locked("EUR_USD", "bos", "sell")[0]:
            skip_signal()
        # later, on stop-out:
        guard.register_stopout("EUR_USD", "bos", "sell", "H1", order_id="abc123")
    """

    state_path: Path
    _entries: dict[str, CooldownEntry] = field(default_factory=dict)

    def load(self) -> None:
        if not self.state_path.exists():
            return
        try:
            raw = json.loads(self.state_path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("cooldown state unreadable, starting fresh: %s", e)
            return
        for k, v in raw.items():
            self._entries[k] = CooldownEntry(**v)
        logger.info("cooldown guard loaded %d entries", len(self._entries))

    def save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {k: v.__dict__ for k, v in self._entries.items()}
        tmp = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
        tmp.replace(self.state_path)

    def is_locked(
        self, pair: str, signal_type: str, direction: str, *, now: datetime | None = None,
    ) -> tuple[bool, datetime | None]:
        """Return (locked, unlock_at). If unlocked, also prune the expired entry."""
        now = now or datetime.now()
        key = _key(pair, signal_type, direction)
        entry = self._entries.get(key)
        if entry is None:
            return False, None
        unlock = datetime.fromisoformat(entry.unlock_at)
        if now >= unlock:
            del self._entries[key]
            self.save()
            return False, None
        return True, unlock

    def register_stopout(
        self,
        pair: str,
        signal_type: str,
        direction: str,
        timeframe: str,
        *,
        order_id: str | None = None,
        now: datetime | None = None,
    ) -> CooldownEntry:
        """Register a stop-out; lock the tuple for the timeframe-derived window."""
        now = now or datetime.now()
        mins = cooldown_minutes(timeframe)
        unlock = now + timedelta(minutes=mins)
        entry = CooldownEntry(
            pair=pair,
            signal_type=signal_type,
            direction=direction,
            locked_at=now.isoformat(),
            unlock_at=unlock.isoformat(),
            timeframe=timeframe,
            triggering_order_id=order_id,
        )
        self._entries[_key(pair, signal_type, direction)] = entry
        self.save()
        logger.info(
            "cooldown registered: %s/%s/%s on %s, unlock at %s (%d min)",
            pair, signal_type, direction, timeframe, entry.unlock_at, mins,
        )
        return entry

    def active(self, *, now: datetime | None = None) -> list[CooldownEntry]:
        """Return all currently-active entries, pruning expired ones."""
        now = now or datetime.now()
        live = []
        expired = []
        for k, e in self._entries.items():
            if now < datetime.fromisoformat(e.unlock_at):
                live.append(e)
            else:
                expired.append(k)
        for k in expired:
            del self._entries[k]
        if expired:
            self.save()
        return live
