"""Unit tests for CooldownGuard + retro replay over the bleed history."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.learning.cooldown import (
    CooldownGuard,
    cooldown_minutes,
    MIN_COOLDOWN_MINUTES,
    BARS_MULTIPLIER,
)


def test_cooldown_minutes_h1():
    assert cooldown_minutes("H1") == max(MIN_COOLDOWN_MINUTES, BARS_MULTIPLIER * 60)


def test_cooldown_minutes_m15_floors_to_min():
    assert cooldown_minutes("M15") == MIN_COOLDOWN_MINUTES


def test_cooldown_minutes_unknown_defaults_to_h1():
    assert cooldown_minutes("X9") == cooldown_minutes("H1")


def test_register_locks_tuple(tmp_path: Path):
    guard = CooldownGuard(state_path=tmp_path / "c.json")
    now = datetime(2026, 5, 11, 13, 38)
    guard.register_stopout("USD_CAD", "pullback", "sell", "H1", now=now)
    locked, unlock = guard.is_locked("USD_CAD", "pullback", "sell", now=now + timedelta(minutes=10))
    assert locked is True
    assert unlock == now + timedelta(minutes=cooldown_minutes("H1"))


def test_unrelated_tuple_not_locked(tmp_path: Path):
    guard = CooldownGuard(state_path=tmp_path / "c.json")
    now = datetime(2026, 5, 11, 13, 38)
    guard.register_stopout("USD_CAD", "pullback", "sell", "H1", now=now)
    locked, _ = guard.is_locked("EUR_USD", "pullback", "sell", now=now + timedelta(minutes=5))
    assert locked is False


def test_opposite_direction_not_locked(tmp_path: Path):
    """A short stop-out should not block the reverse-direction long."""
    guard = CooldownGuard(state_path=tmp_path / "c.json")
    now = datetime(2026, 5, 11, 13, 38)
    guard.register_stopout("USD_CAD", "pullback", "sell", "H1", now=now)
    locked, _ = guard.is_locked("USD_CAD", "pullback", "buy", now=now + timedelta(minutes=5))
    assert locked is False


def test_expiry_unlocks_and_prunes(tmp_path: Path):
    state_path = tmp_path / "c.json"
    guard = CooldownGuard(state_path=state_path)
    now = datetime(2026, 5, 11, 13, 38)
    guard.register_stopout("USD_CAD", "pullback", "sell", "H1", now=now)

    later = now + timedelta(minutes=cooldown_minutes("H1") + 1)
    locked, _ = guard.is_locked("USD_CAD", "pullback", "sell", now=later)
    assert locked is False
    # Pruned from on-disk state too
    persisted = json.loads(state_path.read_text())
    assert "USD_CAD|pullback|sell" not in persisted


def test_persistence_roundtrip(tmp_path: Path):
    state_path = tmp_path / "c.json"
    g1 = CooldownGuard(state_path=state_path)
    g1.register_stopout("EUR_USD", "bos", "sell", "H1")
    g2 = CooldownGuard(state_path=state_path)
    g2.load()
    locked, _ = g2.is_locked("EUR_USD", "bos", "sell")
    assert locked is True


def test_replay_collapses_known_clusters(tmp_path: Path):
    """Acceptance test: apply cooldown logic to the real bleed history
    in data/performance.db. Cluster #1 (4 EUR_USD BOS sells on 04-10) and
    cluster #2 (6 USD_CAD pullback sells on 05-11) must collapse to 1 trade each.
    """
    db = Path(__file__).resolve().parent.parent / "data" / "performance.db"
    if not db.exists():
        pytest.skip("performance.db missing — replay test needs real history")

    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute(
        "SELECT timestamp, pair, signal_type, direction, timeframe, exit_reason, pnl "
        "FROM trade_results WHERE source='paper' ORDER BY timestamp ASC"
    ).fetchall()]
    con.close()

    guard = CooldownGuard(state_path=tmp_path / "c.json")
    allowed = []
    skipped = []
    for r in rows:
        ts = datetime.fromisoformat(r["timestamp"])
        locked, _ = guard.is_locked(r["pair"], r["signal_type"], r["direction"], now=ts)
        if locked:
            skipped.append(r)
            continue
        allowed.append(r)
        if r["exit_reason"] == "stop_loss":
            guard.register_stopout(
                r["pair"], r["signal_type"], r["direction"],
                r["timeframe"], now=ts,
            )

    # Acceptance criteria: at least the two known clusters get collapsed.
    # Cluster #1: rows 8,9,10 on EUR_USD bos sell after row 7 stopped out → 3 skips
    # Cluster #2: rows 19-23 on USD_CAD pullback sell after row 18 stopped out → 5 skips
    eur_bos_skips = [
        s for s in skipped
        if s["pair"] == "EUR_USD" and s["signal_type"] == "bos" and s["direction"] == "sell"
    ]
    usdcad_pb_skips = [
        s for s in skipped
        if s["pair"] == "USD_CAD" and s["signal_type"] == "pullback" and s["direction"] == "sell"
    ]
    assert len(eur_bos_skips) >= 3, f"expected ≥3 EUR_USD BOS skips, got {len(eur_bos_skips)}"
    assert len(usdcad_pb_skips) >= 5, f"expected ≥5 USD_CAD pullback skips, got {len(usdcad_pb_skips)}"

    prevented_loss = sum(float(s["pnl"]) for s in skipped)
    assert prevented_loss < 0, f"sanity: prevented losses should be net negative, got {prevented_loss}"
