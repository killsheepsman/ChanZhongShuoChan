from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.chanlun.analyzer import ANALYSIS_ENGINE_VERSION


DB_PATH = Path(__file__).resolve().parents[3] / "data" / "signals_rules_v14.sqlite3"
_DB_LOCK = threading.Lock()


def init_signal_store() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS signal_index_state (
                symbol TEXT NOT NULL,
                name TEXT NOT NULL,
                period TEXT NOT NULL,
                adjust TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                last_kline_time TEXT,
                source TEXT NOT NULL,
                signal_count INTEGER NOT NULL,
                engine_version TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (symbol, period, adjust)
            );

            CREATE TABLE IF NOT EXISTS signal_points (
                symbol TEXT NOT NULL,
                name TEXT NOT NULL,
                period TEXT NOT NULL,
                adjust TEXT NOT NULL,
                side TEXT NOT NULL,
                signal_type INTEGER NOT NULL,
                signal_date TEXT NOT NULL,
                signal_time TEXT NOT NULL,
                price REAL NOT NULL,
                status TEXT NOT NULL,
                confidence REAL NOT NULL,
                reason TEXT NOT NULL,
                center_id INTEGER,
                segment_id INTEGER,
                source TEXT NOT NULL,
                last_kline_time TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (symbol, period, adjust, side, signal_type, signal_time)
            );

            CREATE INDEX IF NOT EXISTS idx_signal_lookup
            ON signal_points (signal_date, period, adjust, side, signal_type);
            """
        )


def is_index_current(symbol: str, period: str, adjust: str, target_date: str) -> bool:
    init_signal_store()
    with _DB_LOCK, _connect() as conn:
        row = conn.execute(
            """
            SELECT end_date FROM signal_index_state
            WHERE symbol = ? AND period = ? AND adjust = ? AND engine_version = ?
            """,
            (symbol, period, adjust, ANALYSIS_ENGINE_VERSION),
        ).fetchone()
    return bool(row and str(row["end_date"]) >= target_date)


def count_current_symbols(symbols: list[str], period: str, adjust: str, target_date: str) -> int:
    if not symbols:
        return 0
    init_signal_store()
    total = 0
    with _DB_LOCK, _connect() as conn:
        for index in range(0, len(symbols), 800):
            chunk = symbols[index : index + 800]
            placeholders = ",".join("?" for _ in chunk)
            row = conn.execute(
                f"""
                SELECT COUNT(*) AS count FROM signal_index_state
                WHERE period = ? AND adjust = ? AND end_date >= ? AND engine_version = ? AND symbol IN ({placeholders})
                """,
                (period, adjust, target_date, ANALYSIS_ENGINE_VERSION, *chunk),
            ).fetchone()
            total += int(row["count"] if row else 0)
    return total


def upsert_stock_signals(
    *,
    symbol: str,
    name: str,
    period: str,
    adjust: str,
    start_date: str,
    end_date: str,
    source: str,
    last_kline_time: str | None,
    signals: list[dict[str, Any]],
    updated_at: str,
) -> None:
    init_signal_store()
    signal_rows = [
        (
            symbol,
            name,
            period,
            adjust,
            signal["side"],
            int(signal["type"]),
            _signal_date(signal["time"]),
            signal["time"],
            float(signal["price"]),
            signal["status"],
            float(signal["confidence"]),
            signal.get("reason") or "",
            signal.get("center_id"),
            signal.get("segment_id"),
            source,
            last_kline_time,
            updated_at,
        )
        for signal in signals
    ]
    with _DB_LOCK, _connect() as conn:
        conn.execute(
            """
            DELETE FROM signal_points
            WHERE symbol = ? AND period = ? AND adjust = ? AND signal_date BETWEEN ? AND ?
            """,
            (symbol, period, adjust, start_date, end_date),
        )
        conn.executemany(
            """
            INSERT OR REPLACE INTO signal_points (
                symbol, name, period, adjust, side, signal_type, signal_date, signal_time,
                price, status, confidence, reason, center_id, segment_id, source,
                last_kline_time, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            signal_rows,
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO signal_index_state (
                symbol, name, period, adjust, start_date, end_date, last_kline_time,
                source, signal_count, engine_version, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                symbol,
                name,
                period,
                adjust,
                start_date,
                end_date,
                last_kline_time,
                source,
                len(signal_rows),
                ANALYSIS_ENGINE_VERSION,
                updated_at,
            ),
        )


def query_signal_matches(
    *,
    start_signal_date: str,
    end_signal_date: str,
    period: str,
    adjust: str,
    side: str,
    signal_type: int,
    max_results: int,
) -> list[dict[str, Any]]:
    init_signal_store()
    with _DB_LOCK, _connect() as conn:
        rows = conn.execute(
            """
            SELECT symbol, name, signal_time, price, status, confidence, source, last_kline_time
            FROM signal_points
            WHERE signal_date BETWEEN ? AND ?
              AND period = ?
              AND adjust = ?
              AND side = ?
              AND signal_type = ?
            ORDER BY signal_date DESC, confidence DESC, symbol ASC
            LIMIT ?
            """,
            (start_signal_date, end_signal_date, period, adjust, side, signal_type, max_results),
        ).fetchall()
    return [
        {
            "code": row["symbol"],
            "name": row["name"],
            "time": row["signal_time"],
            "price": row["price"],
            "status": row["status"],
            "confidence": row["confidence"],
            "source": row["source"],
            "last_kline_time": row["last_kline_time"],
        }
        for row in rows
    ]


@contextmanager
def _connect():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _signal_date(value: str) -> str:
    return value[:10].replace("-", "")
