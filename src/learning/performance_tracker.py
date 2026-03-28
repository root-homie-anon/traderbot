"""Track per-pair, per-setup, per-timeframe performance metrics."""

import math
import sqlite3
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from src.config import DATA_DIR
from src.trading_sessions import get_session_name

logger = logging.getLogger("pa_bot")

DB_PATH = DATA_DIR / "performance.db"

# Kept here so self_corrector.py can import it without a circular dep
CONSECUTIVE_LOSS_LIMIT_DEFAULT = 5


@dataclass
class SetupStats:
    """Aggregated stats for a specific setup combination."""

    pair: str
    signal_type: str
    timeframe: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    total_risk: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0

    @property
    def win_rate(self) -> float:
        return self.wins / self.total_trades if self.total_trades else 0.0

    @property
    def expectancy(self) -> float:
        return self.total_pnl / self.total_trades if self.total_trades else 0.0

    @property
    def profit_factor(self) -> float:
        if self.gross_loss == 0:
            return float("inf") if self.gross_profit > 0 else 0.0
        return self.gross_profit / self.gross_loss

    @property
    def avg_r(self) -> float:
        """Average R multiple (pnl / risk)."""
        if self.total_risk == 0:
            return 0.0
        return self.total_pnl / self.total_risk


WeightType = Literal["uniform", "exponential", "recent_only"]

# Default half-life for exponential decay (hours).
# A trade this many hours old receives weight 0.5 relative to a trade
# recorded right now.
DEFAULT_HALF_LIFE_HOURS: float = 3.0

# Default window for recent_only filtering (hours)
DEFAULT_RECENT_ONLY_HOURS: float = 6.0


@dataclass
class WeightedSetupStats:
    """Aggregated stats computed with exponential or recency-windowed weights.

    Stores pre-computed weighted sums so that the standard property interface
    (win_rate, expectancy, profit_factor) is preserved for all downstream
    consumers without modification.

    win_rate        = sum(w * is_win) / sum(w)
    expectancy      = sum(w * pnl) / sum(w)
    profit_factor   = sum(w * pnl for wins) / abs(sum(w * pnl for losses))
    """

    pair: str
    signal_type: str
    timeframe: str
    total_trades: int = 0

    # Weighted accumulators — private, populated by PerformanceTracker
    _sum_weights: float = field(default=0.0, repr=False)
    _sum_weighted_wins: float = field(default=0.0, repr=False)
    _sum_weighted_pnl: float = field(default=0.0, repr=False)
    _sum_weighted_gross_profit: float = field(default=0.0, repr=False)
    _sum_weighted_gross_loss: float = field(default=0.0, repr=False)

    @property
    def win_rate(self) -> float:
        if self._sum_weights == 0.0:
            return 0.0
        return self._sum_weighted_wins / self._sum_weights

    @property
    def expectancy(self) -> float:
        if self._sum_weights == 0.0:
            return 0.0
        return self._sum_weighted_pnl / self._sum_weights

    @property
    def profit_factor(self) -> float:
        if self._sum_weighted_gross_loss == 0.0:
            return float("inf") if self._sum_weighted_gross_profit > 0.0 else 0.0
        return self._sum_weighted_gross_profit / self._sum_weighted_gross_loss

    @property
    def avg_r(self) -> float:
        return 0.0


def _parse_timestamp(ts: str) -> datetime:
    """Parse an ISO 8601 timestamp string into a timezone-aware datetime."""
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        # Treat naive timestamps as UTC — matches how they are stored
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _hours_since(ts: str, now: datetime) -> float:
    """Return the number of hours elapsed between ts and now."""
    trade_dt = _parse_timestamp(ts)
    delta = now - trade_dt
    return delta.total_seconds() / 3600.0


class PerformanceTracker:
    """Track and query performance metrics by pair, signal type, and timeframe.

    Stores trade results in SQLite and provides aggregated statistics
    for the adaptive engine and pair selector to consume.

    Args:
        db_path: Path to the SQLite database file.
        half_life_hours: Half-life used for exponential decay weighting.
            A trade this many hours old receives weight 0.5 relative to a
            trade recorded right now.  Default is 3 hours.
        recent_only_hours: Window used by the "recent_only" weight type.
            Only trades within this many hours of now are included.
            Default is 6 hours.
    """

    def __init__(
        self,
        db_path: Path | str | None = None,
        half_life_hours: float = DEFAULT_HALF_LIFE_HOURS,
        recent_only_hours: float = DEFAULT_RECENT_ONLY_HOURS,
    ):
        self.db_path = str(db_path or DB_PATH)
        self.half_life_hours = half_life_hours
        self.recent_only_hours = recent_only_hours
        # decay_rate = ln(2) / half_life  so that exp(-decay_rate * half_life) = 0.5
        self._decay_rate: float = math.log(2) / self.half_life_hours
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trade_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    pair TEXT NOT NULL,
                    signal_type TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    exit_price REAL NOT NULL,
                    stop_loss REAL NOT NULL,
                    take_profit REAL NOT NULL,
                    pnl REAL NOT NULL,
                    risk_amount REAL NOT NULL,
                    exit_reason TEXT NOT NULL,
                    quality_score REAL DEFAULT 0,
                    confluence_level INTEGER DEFAULT 0,
                    source TEXT DEFAULT 'backtest',
                    session TEXT DEFAULT NULL
                )
            """)
            # Migrate existing tables that were created before the session column
            existing_cols = {
                row[1]
                for row in conn.execute(
                    "PRAGMA table_info(trade_results)"
                ).fetchall()
            }
            if "session" not in existing_cols:
                try:
                    conn.execute(
                        "ALTER TABLE trade_results ADD COLUMN session TEXT DEFAULT NULL"
                    )
                except Exception as e:
                    logger.warning("Migration: could not add session column: %s", e)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_trade_pair
                ON trade_results(pair, signal_type, timeframe)
            """)

    def get_paper_trade_count(self) -> dict:
        """Return paper trade totals: count, wins, losses, total_pnl."""
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT COUNT(*), "
                "SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END), "
                "SUM(CASE WHEN pnl <= 0 THEN 1 ELSE 0 END), "
                "COALESCE(SUM(pnl), 0) "
                "FROM trade_results WHERE source='paper'"
            ).fetchone()
        return {
            "total": row[0],
            "wins": row[1] or 0,
            "losses": row[2] or 0,
            "pnl": round(row[3], 2),
        }

    def record_trade(self, trade: dict, source: str = "backtest") -> None:
        """Record a single completed trade."""
        # Derive the session from the trade's timestamp when available;
        # fall back to the current wall-clock session.
        ts_raw = trade.get("timestamp", "")
        trade_session: str | None = None
        if ts_raw:
            try:
                ts = datetime.fromisoformat(ts_raw)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                trade_session = get_session_name(ts)
            except (ValueError, TypeError):
                trade_session = get_session_name()
        else:
            trade_session = get_session_name()

        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO trade_results
                    (timestamp, pair, signal_type, timeframe, direction,
                     entry_price, exit_price, stop_loss, take_profit,
                     pnl, risk_amount, exit_reason, quality_score,
                     confluence_level, source, session)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    ts_raw,
                    trade.get("pair", ""),
                    trade.get("signal_type", ""),
                    trade.get("timeframe", ""),
                    trade.get("direction", ""),
                    trade.get("entry_price", 0),
                    trade.get("exit_price", 0),
                    trade.get("stop_loss", 0),
                    trade.get("take_profit", 0),
                    trade.get("pnl", 0),
                    trade.get("risk_amount", 0),
                    trade.get("exit_reason", ""),
                    trade.get("quality_score", 0),
                    trade.get("confluence_level", 0),
                    source,
                    trade_session,
                ))
        except Exception as e:
            logger.error(
                "Failed to record trade for %s (%s): %s",
                trade.get("pair", "unknown"), source, e,
            )

    def record_trades(self, trades: list[dict], source: str = "backtest") -> None:
        """Record multiple completed trades."""
        for trade in trades:
            self.record_trade(trade, source=source)

    def get_stats(
        self,
        pair: str | None = None,
        signal_type: str | None = None,
        timeframe: str | None = None,
        source: str | None = None,
        last_n: int | None = None,
        session: str | None = None,
        weight_type: WeightType = "uniform",
    ) -> SetupStats | WeightedSetupStats:
        """Get aggregated stats with optional filters.

        When ``session`` is provided, only trades recorded for that session
        (e.g. "London", "New York", "Tokyo") are included.

        Args:
            weight_type: Aggregation method.
                "uniform"      — equal weight per trade (original behaviour,
                                 returns SetupStats).
                "exponential"  — weight = exp(-decay_rate * hours_since_trade)
                                 using half_life_hours set on __init__.
                "recent_only"  — include only trades within recent_only_hours
                                 of the current time, equal weight.
                Weighted modes return WeightedSetupStats whose win_rate,
                expectancy, and profit_factor properties reflect the weights.
        """
        conditions = []
        params: list = []

        if pair:
            conditions.append("pair = ?")
            params.append(pair)
        if signal_type:
            conditions.append("signal_type = ?")
            params.append(signal_type)
        if timeframe:
            conditions.append("timeframe = ?")
            params.append(timeframe)
        if source:
            conditions.append("source = ?")
            params.append(source)
        if session:
            conditions.append("session = ?")
            params.append(session)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        order_limit = f"ORDER BY id DESC LIMIT {last_n}" if last_n else ""

        if weight_type == "uniform":
            query = f"""
                SELECT pnl, risk_amount FROM trade_results
                {where}
                {order_limit}
            """
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute(query, params).fetchall()

            stats = SetupStats(
                pair=pair or "*",
                signal_type=signal_type or "*",
                timeframe=timeframe or "*",
            )
            for pnl, risk_amount in rows:
                stats.total_trades += 1
                stats.total_risk += abs(risk_amount)
                if pnl > 0:
                    stats.wins += 1
                    stats.gross_profit += pnl
                else:
                    stats.losses += 1
                    stats.gross_loss += abs(pnl)
                stats.total_pnl += pnl
            return stats

        # Weighted modes — need timestamp to compute elapsed time
        query = f"""
            SELECT pnl, risk_amount, timestamp FROM trade_results
            {where}
            {order_limit}
        """
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(query, params).fetchall()

        now = datetime.now(tz=timezone.utc)
        weighted = WeightedSetupStats(
            pair=pair or "*",
            signal_type=signal_type or "*",
            timeframe=timeframe or "*",
        )

        for pnl, _risk_amount, ts in rows:
            try:
                hours_ago = _hours_since(ts, now)
            except (ValueError, TypeError):
                logger.warning(
                    "Unparseable timestamp in trade_results: %r — skipping", ts
                )
                continue

            if weight_type == "recent_only":
                if hours_ago > self.recent_only_hours:
                    continue
                w = 1.0
            else:
                # weight_type == "exponential"
                w = math.exp(-self._decay_rate * hours_ago)

            weighted.total_trades += 1
            weighted._sum_weights += w
            weighted._sum_weighted_pnl += w * pnl
            if pnl > 0:
                weighted._sum_weighted_wins += w
                weighted._sum_weighted_gross_profit += w * pnl
            else:
                weighted._sum_weighted_gross_loss += w * abs(pnl)

        return weighted

    def get_recent_outcomes(
        self,
        signal_type: str | None = None,
        pair: str | None = None,
        source: str | None = None,
        last_n: int = CONSECUTIVE_LOSS_LIMIT_DEFAULT,
    ) -> list[bool]:
        """Return the last N trade outcomes as booleans (True = win) in oldest-first order.

        Used by the self-corrector to detect consecutive loss streaks.
        """
        conditions = []
        params: list = []

        if signal_type:
            conditions.append("signal_type = ?")
            params.append(signal_type)
        if pair:
            conditions.append("pair = ?")
            params.append(pair)
        if source:
            conditions.append("source = ?")
            params.append(source)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"""
            SELECT pnl FROM trade_results
            {where}
            ORDER BY id DESC LIMIT ?
        """
        params.append(last_n)

        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(query, params).fetchall()

        # Rows arrive newest-first; reverse to get chronological order
        return [pnl > 0 for (pnl,) in reversed(rows)]

    def get_win_rate(
        self,
        pair: str | None = None,
        signal_type: str | None = None,
        timeframe: str | None = None,
        source: str | None = None,
        last_n: int | None = None,
        session: str | None = None,
    ) -> float:
        """Convenience method to get just the win rate."""
        return self.get_stats(pair, signal_type, timeframe, source, last_n, session).win_rate

    def get_all_pairs(self) -> list[str]:
        """Get all pairs that have recorded trades."""
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT DISTINCT pair FROM trade_results"
            ).fetchall()
        return [r[0] for r in rows]

    def get_pair_rankings(
        self,
        source: str | None = None,
        last_n: int | None = None,
        min_trades: int = 5,
        session: str | None = None,
    ) -> list[SetupStats]:
        """Rank all pairs by expectancy, optionally within a single session."""
        pairs = self.get_all_pairs()
        rankings = []
        for pair in pairs:
            stats = self.get_stats(
                pair=pair, source=source, last_n=last_n, session=session
            )
            if stats.total_trades >= min_trades:
                rankings.append(stats)
        rankings.sort(key=lambda s: s.expectancy, reverse=True)
        return rankings

    def clear(self, source: str | None = None) -> None:
        """Clear recorded trades, optionally filtered by source."""
        with sqlite3.connect(self.db_path) as conn:
            if source:
                conn.execute("DELETE FROM trade_results WHERE source = ?", (source,))
            else:
                conn.execute("DELETE FROM trade_results")
