"""Log all trades to the database.

Provides a persistent record of every order placed, filled, and closed,
independent of the performance tracker (which stores aggregated results).
"""

import sqlite3
import logging
from pathlib import Path

from src.broker.broker_base import Order, OrderStatus
from src.config import DATA_DIR

logger = logging.getLogger("pa_bot")

DB_PATH = DATA_DIR / "trades.db"


class TradeLogger:
    """Append-only trade log backed by SQLite.

    Records order events (placed, filled, closed) for auditing and replay.
    """

    def __init__(self, db_path: Path | str | None = None):
        self.db_path = str(db_path or DB_PATH)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trade_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
                    order_id TEXT NOT NULL,
                    pair TEXT NOT NULL,
                    side TEXT NOT NULL,
                    order_type TEXT NOT NULL,
                    units INTEGER NOT NULL,
                    requested_price REAL DEFAULT 0,
                    fill_price REAL DEFAULT 0,
                    stop_loss REAL DEFAULT 0,
                    take_profit REAL DEFAULT 0,
                    status TEXT NOT NULL,
                    pnl REAL DEFAULT 0,
                    event TEXT NOT NULL DEFAULT 'placed'
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_trade_log_order
                ON trade_log(order_id)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS signal_meta (
                    order_id TEXT PRIMARY KEY,
                    pair TEXT NOT NULL,
                    signal_type TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    quality_score REAL NOT NULL DEFAULT 0,
                    confluence_level REAL NOT NULL DEFAULT 0,
                    entry_price REAL NOT NULL DEFAULT 0,
                    stop_loss REAL NOT NULL DEFAULT 0,
                    take_profit REAL NOT NULL DEFAULT 0
                )
            """)

    def log_order(self, order: Order, event: str = "placed") -> None:
        """Log an order event."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO trade_log
                (order_id, pair, side, order_type, units,
                 requested_price, fill_price, stop_loss, take_profit,
                 status, pnl, event)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                order.order_id,
                order.pair,
                order.side.value,
                order.order_type.value,
                order.units,
                order.price,
                order.fill_price,
                order.stop_loss,
                order.take_profit,
                order.status.value,
                order.pnl,
                event,
            ))

    def get_trade_history(
        self,
        pair: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Retrieve trade log entries."""
        conditions = []
        params: list = []

        if pair:
            conditions.append("pair = ?")
            params.append(pair)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        query = f"""
            SELECT timestamp, order_id, pair, side, order_type, units,
                   requested_price, fill_price, stop_loss, take_profit,
                   status, pnl, event
            FROM trade_log
            {where}
            ORDER BY id DESC
            LIMIT ?
        """
        params.append(limit)

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()

        return [dict(row) for row in rows]

    def get_order_events(self, order_id: str) -> list[dict]:
        """Get all events for a specific order."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM trade_log WHERE order_id = ? ORDER BY id",
                (order_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def save_signal_meta(self, order_id: str, meta: dict) -> None:
        """Upsert signal metadata for a pending trade."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO signal_meta
                    (order_id, pair, signal_type, timeframe, direction,
                     quality_score, confluence_level, entry_price, stop_loss, take_profit)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(order_id) DO UPDATE SET
                    pair = excluded.pair,
                    signal_type = excluded.signal_type,
                    timeframe = excluded.timeframe,
                    direction = excluded.direction,
                    quality_score = excluded.quality_score,
                    confluence_level = excluded.confluence_level,
                    entry_price = excluded.entry_price,
                    stop_loss = excluded.stop_loss,
                    take_profit = excluded.take_profit
            """, (
                order_id,
                meta.get("pair", ""),
                meta.get("signal_type", "unknown"),
                meta.get("timeframe", ""),
                meta.get("direction", ""),
                meta.get("quality_score", 0.0),
                meta.get("confluence_level", 0.0),
                meta.get("entry_price", 0.0),
                meta.get("stop_loss", 0.0),
                meta.get("take_profit", 0.0),
            ))

    def load_pending_signal_meta(self) -> dict[str, dict]:
        """Return all persisted signal metadata keyed by order_id."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM signal_meta").fetchall()
        return {row["order_id"]: dict(row) for row in rows}

    def delete_signal_meta(self, order_id: str) -> None:
        """Remove signal metadata once a trade outcome has been recorded."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM signal_meta WHERE order_id = ?", (order_id,))

    def clear(self) -> None:
        """Clear the trade log."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM trade_log")
