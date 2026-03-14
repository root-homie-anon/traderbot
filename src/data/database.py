"""SQLite interface for storing trades and market data."""

import sqlite3
from pathlib import Path

import pandas as pd

from src.config import DATA_DIR


class Database:
    """Simple SQLite wrapper for trade and signal storage."""

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = str(db_path or DATA_DIR / "trades.db")
        self._ensure_tables()

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _ensure_tables(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    pair TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    stop_loss REAL,
                    take_profit REAL,
                    exit_price REAL,
                    exit_timestamp TEXT,
                    pnl REAL,
                    pips REAL,
                    signal_type TEXT,
                    quality_score REAL,
                    timeframe TEXT,
                    mode TEXT DEFAULT 'backtest',
                    notes TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    pair TEXT NOT NULL,
                    signal_type TEXT NOT NULL,
                    direction TEXT NOT NULL,
                    quality_score REAL,
                    confluence_level INTEGER,
                    timeframe TEXT,
                    acted_on INTEGER DEFAULT 0,
                    notes TEXT
                )
            """)

    def log_trade(self, trade: dict):
        cols = ", ".join(trade.keys())
        placeholders = ", ".join("?" for _ in trade)
        with self._connect() as conn:
            conn.execute(
                f"INSERT INTO trades ({cols}) VALUES ({placeholders})",
                list(trade.values()),
            )

    def log_signal(self, signal: dict):
        cols = ", ".join(signal.keys())
        placeholders = ", ".join("?" for _ in signal)
        with self._connect() as conn:
            conn.execute(
                f"INSERT INTO signals ({cols}) VALUES ({placeholders})",
                list(signal.values()),
            )

    def get_trades(self, pair: str | None = None, mode: str | None = None) -> pd.DataFrame:
        query = "SELECT * FROM trades WHERE 1=1"
        params = []
        if pair:
            query += " AND pair = ?"
            params.append(pair)
        if mode:
            query += " AND mode = ?"
            params.append(mode)
        with self._connect() as conn:
            return pd.read_sql_query(query, conn, params=params)

    def get_signals(self, pair: str | None = None) -> pd.DataFrame:
        query = "SELECT * FROM signals WHERE 1=1"
        params = []
        if pair:
            query += " AND pair = ?"
            params.append(pair)
        with self._connect() as conn:
            return pd.read_sql_query(query, conn, params=params)
