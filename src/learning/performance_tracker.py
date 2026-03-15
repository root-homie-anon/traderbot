"""Track per-pair, per-setup, per-timeframe performance metrics."""

import sqlite3
import logging
from dataclasses import dataclass
from pathlib import Path

from src.config import DATA_DIR

logger = logging.getLogger("pa_bot")

DB_PATH = DATA_DIR / "performance.db"


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


class PerformanceTracker:
    """Track and query performance metrics by pair, signal type, and timeframe.

    Stores trade results in SQLite and provides aggregated statistics
    for the adaptive engine and pair selector to consume.
    """

    def __init__(self, db_path: Path | str | None = None):
        self.db_path = str(db_path or DB_PATH)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
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
                    source TEXT DEFAULT 'backtest'
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_trade_pair
                ON trade_results(pair, signal_type, timeframe)
            """)

    def record_trade(self, trade: dict, source: str = "backtest") -> None:
        """Record a single completed trade."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO trade_results
                (timestamp, pair, signal_type, timeframe, direction,
                 entry_price, exit_price, stop_loss, take_profit,
                 pnl, risk_amount, exit_reason, quality_score,
                 confluence_level, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade.get("timestamp", ""),
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
            ))

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
    ) -> SetupStats:
        """Get aggregated stats with optional filters."""
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

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        order_limit = f"ORDER BY id DESC LIMIT {last_n}" if last_n else ""

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

    def get_win_rate(
        self,
        pair: str | None = None,
        signal_type: str | None = None,
        timeframe: str | None = None,
        source: str | None = None,
        last_n: int | None = None,
    ) -> float:
        """Convenience method to get just the win rate."""
        return self.get_stats(pair, signal_type, timeframe, source, last_n).win_rate

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
    ) -> list[SetupStats]:
        """Rank all pairs by expectancy."""
        pairs = self.get_all_pairs()
        rankings = []
        for pair in pairs:
            stats = self.get_stats(pair=pair, source=source, last_n=last_n)
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
