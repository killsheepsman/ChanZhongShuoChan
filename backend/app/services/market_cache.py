from __future__ import annotations

import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterable

from app.chanlun.models import KLine


DB_PATH = Path(__file__).resolve().parents[3] / "data" / "market_cache.sqlite3"
_DB_LOCK = threading.Lock()


def init_market_cache() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _DB_LOCK, _connection() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS market_klines (
                symbol TEXT NOT NULL,
                period TEXT NOT NULL,
                adjust TEXT NOT NULL,
                time TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL DEFAULT 0,
                amount REAL NOT NULL DEFAULT 0,
                source TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (symbol, period, adjust, time)
            );

            CREATE INDEX IF NOT EXISTS idx_market_klines_range
            ON market_klines (symbol, period, adjust, time);

            CREATE TABLE IF NOT EXISTS market_cache_state (
                symbol TEXT NOT NULL,
                period TEXT NOT NULL,
                adjust TEXT NOT NULL,
                first_kline_time TEXT,
                last_kline_time TEXT,
                source TEXT NOT NULL DEFAULT 'local-cache',
                updated_at TEXT NOT NULL,
                last_checked_at TEXT,
                last_request_start TEXT,
                last_request_end TEXT,
                last_error TEXT,
                PRIMARY KEY (symbol, period, adjust)
            );

            CREATE TABLE IF NOT EXISTS cache_sync_jobs (
                job_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                periods TEXT NOT NULL,
                adjust TEXT NOT NULL,
                batch_size INTEGER NOT NULL,
                message TEXT NOT NULL,
                started_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS cache_sync_items (
                job_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                name TEXT NOT NULL,
                period TEXT NOT NULL,
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                kline_count INTEGER NOT NULL DEFAULT 0,
                source TEXT,
                first_kline_time TEXT,
                last_kline_time TEXT,
                message TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (job_id, symbol, period),
                FOREIGN KEY (job_id) REFERENCES cache_sync_jobs(job_id)
            );

            CREATE INDEX IF NOT EXISTS idx_cache_sync_items_pending
            ON cache_sync_items (job_id, status, period, symbol);
            """
        )


def load_cached_klines(symbol: str, period: str, adjust: str, start_date: str, end_date: str) -> list[KLine]:
    init_market_cache()
    start, end = _range_bounds(start_date, end_date)
    with _DB_LOCK, _connection() as conn:
        rows = conn.execute(
            """
            SELECT time, open, high, low, close, volume, amount
            FROM market_klines
            WHERE symbol = ? AND period = ? AND adjust = ?
              AND time >= ? AND time <= ?
            ORDER BY time ASC
            """,
            (symbol, period, adjust, start, end),
        ).fetchall()
    return [_row_to_kline(index, row) for index, row in enumerate(rows)]


def get_cache_state(symbol: str, period: str, adjust: str) -> dict | None:
    init_market_cache()
    with _DB_LOCK, _connection() as conn:
        row = conn.execute(
            """
            SELECT first_kline_time, last_kline_time, source, updated_at,
                   last_checked_at, last_request_start, last_request_end, last_error
            FROM market_cache_state
            WHERE symbol = ? AND period = ? AND adjust = ?
            """,
            (symbol, period, adjust),
        ).fetchone()
    return dict(row) if row else None


def upsert_cached_klines(
    *,
    symbol: str,
    period: str,
    adjust: str,
    klines: Iterable[KLine],
    source: str,
    requested_start: str | None = None,
    requested_end: str | None = None,
) -> int:
    rows = list(klines)
    if not rows:
        return 0
    init_market_cache()
    now = _now()
    values = [
        (
            symbol,
            period,
            adjust,
            item.time,
            item.open,
            item.high,
            item.low,
            item.close,
            item.volume,
            item.amount,
            source,
            now,
        )
        for item in rows
    ]
    with _DB_LOCK, _connection() as conn:
        conn.executemany(
            """
            INSERT INTO market_klines (
                symbol, period, adjust, time, open, high, low, close, volume, amount, source, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, period, adjust, time) DO UPDATE SET
                open = excluded.open,
                high = excluded.high,
                low = excluded.low,
                close = excluded.close,
                volume = excluded.volume,
                amount = excluded.amount,
                source = excluded.source,
                updated_at = excluded.updated_at
            """,
            values,
        )
        coverage = conn.execute(
            """
            SELECT MIN(time) AS first_kline_time, MAX(time) AS last_kline_time
            FROM market_klines
            WHERE symbol = ? AND period = ? AND adjust = ?
            """,
            (symbol, period, adjust),
        ).fetchone()
        conn.execute(
            """
            INSERT INTO market_cache_state (
                symbol, period, adjust, first_kline_time, last_kline_time, source, updated_at,
                last_checked_at, last_request_start, last_request_end, last_error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            ON CONFLICT(symbol, period, adjust) DO UPDATE SET
                first_kline_time = excluded.first_kline_time,
                last_kline_time = excluded.last_kline_time,
                source = excluded.source,
                updated_at = excluded.updated_at,
                last_checked_at = excluded.last_checked_at,
                last_request_start = excluded.last_request_start,
                last_request_end = excluded.last_request_end,
                last_error = NULL
            """,
            (
                symbol,
                period,
                adjust,
                coverage["first_kline_time"],
                coverage["last_kline_time"],
                source,
                now,
                now,
                requested_start,
                requested_end,
            ),
        )
    return len(rows)


def record_cache_check(
    *,
    symbol: str,
    period: str,
    adjust: str,
    source: str,
    requested_start: str,
    requested_end: str,
    error: str | None,
) -> None:
    init_market_cache()
    now = _now()
    with _DB_LOCK, _connection() as conn:
        existing = conn.execute(
            """
            SELECT first_kline_time, last_kline_time
            FROM market_cache_state
            WHERE symbol = ? AND period = ? AND adjust = ?
            """,
            (symbol, period, adjust),
        ).fetchone()
        conn.execute(
            """
            INSERT INTO market_cache_state (
                symbol, period, adjust, first_kline_time, last_kline_time, source, updated_at,
                last_checked_at, last_request_start, last_request_end, last_error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, period, adjust) DO UPDATE SET
                source = excluded.source,
                updated_at = excluded.updated_at,
                last_checked_at = excluded.last_checked_at,
                last_request_start = excluded.last_request_start,
                last_request_end = excluded.last_request_end,
                last_error = excluded.last_error
            """,
            (
                symbol,
                period,
                adjust,
                existing["first_kline_time"] if existing else None,
                existing["last_kline_time"] if existing else None,
                source,
                now,
                now,
                requested_start,
                requested_end,
                error,
            ),
        )


def cache_request_checked_today(state: dict | None, start_date: str, end_date: str) -> bool:
    if not state or not state.get("last_checked_at"):
        return False
    checked_date = str(state["last_checked_at"])[:10]
    return (
        checked_date == datetime.now().strftime("%Y-%m-%d")
        and str(state.get("last_request_start") or "") == start_date
        and str(state.get("last_request_end") or "") == end_date
    )


def create_cache_sync_job(
    *,
    stocks: list[tuple[str, str]],
    periods: list[str],
    start_date: str,
    end_date: str,
    adjust: str,
    batch_size: int,
) -> dict:
    init_market_cache()
    job_id = uuid.uuid4().hex
    now = _now()
    with _DB_LOCK, _connection() as conn:
        conn.execute(
            """
            INSERT INTO cache_sync_jobs (
                job_id, status, start_date, end_date, periods, adjust, batch_size,
                message, started_at, updated_at
            ) VALUES (?, 'running', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                start_date,
                end_date,
                ",".join(periods),
                adjust,
                batch_size,
                "等待下载第一批数据",
                now,
                now,
            ),
        )
        conn.executemany(
            """
            INSERT INTO cache_sync_items (
                job_id, symbol, name, period, status, updated_at
            ) VALUES (?, ?, ?, ?, 'pending', ?)
            """,
            [(job_id, code, name, period, now) for period in periods for code, name in stocks],
        )
    return get_cache_sync_job(job_id) or {}


def get_active_cache_sync_job() -> dict | None:
    init_market_cache()
    with _DB_LOCK, _connection() as conn:
        row = conn.execute(
            """
            SELECT job_id FROM cache_sync_jobs
            WHERE status IN ('running', 'paused')
            ORDER BY updated_at DESC
            LIMIT 1
            """
        ).fetchone()
    return get_cache_sync_job(str(row["job_id"])) if row else None


def get_cache_sync_job(job_id: str | None = None) -> dict | None:
    init_market_cache()
    with _DB_LOCK, _connection() as conn:
        if job_id:
            job = conn.execute("SELECT * FROM cache_sync_jobs WHERE job_id = ?", (job_id,)).fetchone()
        else:
            job = conn.execute("SELECT * FROM cache_sync_jobs ORDER BY updated_at DESC LIMIT 1").fetchone()
        if not job:
            return None
        counts = conn.execute(
            """
            SELECT
                COUNT(*) AS total_count,
                SUM(CASE WHEN status IN ('completed', 'skipped') THEN 1 ELSE 0 END) AS completed_count,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_count,
                SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending_count,
                SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END) AS running_count
            FROM cache_sync_items WHERE job_id = ?
            """,
            (job["job_id"],),
        ).fetchone()
        current = conn.execute(
            """
            SELECT symbol, name, period, status, message
            FROM cache_sync_items
            WHERE job_id = ? AND status = 'running'
            ORDER BY updated_at DESC LIMIT 1
            """,
            (job["job_id"],),
        ).fetchone()

        stock_counts = conn.execute(
            """
            SELECT COUNT(DISTINCT symbol) AS total_stock_count
            FROM cache_sync_items WHERE job_id = ?
            """,
            (job["job_id"],),
        ).fetchone()
        processed_stock_counts = conn.execute(
            """
            SELECT COUNT(*) AS processed_stock_count
            FROM (
                SELECT symbol
                FROM cache_sync_items
                WHERE job_id = ?
                GROUP BY symbol
                HAVING SUM(CASE WHEN status IN ('pending', 'running') THEN 1 ELSE 0 END) = 0
            )
            """,
            (job["job_id"],),
        ).fetchone()

    total = int(counts["total_count"] or 0)
    completed = int(counts["completed_count"] or 0)
    failed = int(counts["failed_count"] or 0)
    processed = completed + failed
    payload = dict(job)
    payload.update(
        {
            "total_count": total,
            "completed_count": completed,
            "failed_count": failed,
            "pending_count": int(counts["pending_count"] or 0),
            "running_count": int(counts["running_count"] or 0),
            "progress": round(processed / total * 100, 1) if total else 0,
            "total_stock_count": int(stock_counts["total_stock_count"] or 0),
            "processed_stock_count": int(processed_stock_counts["processed_stock_count"] or 0),
            "pending_stock_count": max(0, int(stock_counts["total_stock_count"] or 0) - int(processed_stock_counts["processed_stock_count"] or 0)),
            "current_item": dict(current) if current else None,
            "periods": [value for value in str(job["periods"]).split(",") if value],
        }
    )
    return payload


def get_next_cache_sync_items(job_id: str, limit: int) -> list[dict]:
    init_market_cache()
    with _DB_LOCK, _connection() as conn:
        rows = conn.execute(
            """
            SELECT symbol, name, period
            FROM cache_sync_items
            WHERE job_id = ? AND status = 'pending'
            ORDER BY CASE period WHEN 'daily' THEN 0 WHEN '30' THEN 1 WHEN '5' THEN 2 ELSE 3 END, symbol
            LIMIT ?
            """,
            (job_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def get_next_cache_sync_symbols(job_id: str, limit: int) -> list[dict]:
    """Return distinct stocks that still have one or more period downloads pending."""
    init_market_cache()
    with _DB_LOCK, _connection() as conn:
        rows = conn.execute(
            """
            SELECT symbol, MIN(name) AS name
            FROM cache_sync_items
            WHERE job_id = ? AND status = 'pending'
            GROUP BY symbol
            ORDER BY symbol
            LIMIT ?
            """,
            (job_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def get_pending_cache_sync_items_for_symbols(job_id: str, symbols: list[str]) -> list[dict]:
    if not symbols:
        return []
    init_market_cache()
    placeholders = ", ".join("?" for _ in symbols)
    with _DB_LOCK, _connection() as conn:
        rows = conn.execute(
            f"""
            SELECT symbol, name, period
            FROM cache_sync_items
            WHERE job_id = ? AND status = 'pending' AND symbol IN ({placeholders})
            ORDER BY symbol, CASE period WHEN 'daily' THEN 0 WHEN '30' THEN 1 WHEN '5' THEN 2 ELSE 3 END
            """,
            (job_id, *symbols),
        ).fetchall()
    return [dict(row) for row in rows]


def mark_cache_sync_item_running(job_id: str, symbol: str, period: str) -> None:
    _update_sync_item(job_id, symbol, period, status="running", message="下载中")


def complete_cache_sync_item(
    *,
    job_id: str,
    symbol: str,
    period: str,
    source: str,
    klines: list[KLine],
    message: str,
) -> None:
    _update_sync_item(
        job_id,
        symbol,
        period,
        status="completed",
        attempts_delta=1,
        kline_count=len(klines),
        source=source,
        first_kline_time=klines[0].time if klines else None,
        last_kline_time=klines[-1].time if klines else None,
        message=message,
    )


def fail_cache_sync_item(job_id: str, symbol: str, period: str, message: str) -> None:
    _update_sync_item(job_id, symbol, period, status="failed", attempts_delta=1, message=message)


def pause_cache_sync_job(job_id: str) -> dict | None:
    init_market_cache()
    now = _now()
    with _DB_LOCK, _connection() as conn:
        conn.execute(
            """
            UPDATE cache_sync_jobs
            SET status = 'paused', message = '已暂停；已完成的数据已保留在本地缓存', updated_at = ?
            WHERE job_id = ? AND status = 'running'
            """,
            (now, job_id),
        )
        conn.execute(
            """
            UPDATE cache_sync_items SET status = 'pending', updated_at = ?
            WHERE job_id = ? AND status = 'running'
            """,
            (now, job_id),
        )
    return get_cache_sync_job(job_id)


def resume_cache_sync_job(job_id: str) -> dict | None:
    init_market_cache()
    now = _now()
    with _DB_LOCK, _connection() as conn:
        conn.execute(
            """
            UPDATE cache_sync_jobs
            SET status = 'running', message = '正在从未完成股票继续下载', updated_at = ?
            WHERE job_id = ? AND status IN ('paused', 'failed', 'completed')
            """,
            (now, job_id),
        )
        conn.execute(
            """
            UPDATE cache_sync_items SET status = 'pending', updated_at = ?
            WHERE job_id = ? AND status = 'running'
            """,
            (now, job_id),
        )
    return get_cache_sync_job(job_id)


def set_cache_sync_job_message(job_id: str, *, status: str | None = None, message: str) -> None:
    init_market_cache()
    now = _now()
    with _DB_LOCK, _connection() as conn:
        if status:
            conn.execute(
                "UPDATE cache_sync_jobs SET status = ?, message = ?, updated_at = ? WHERE job_id = ?",
                (status, message, now, job_id),
            )
        else:
            conn.execute(
                "UPDATE cache_sync_jobs SET message = ?, updated_at = ? WHERE job_id = ?",
                (message, now, job_id),
            )


def recover_interrupted_cache_sync_jobs() -> None:
    init_market_cache()
    now = _now()
    with _DB_LOCK, _connection() as conn:
        conn.execute(
            """
            UPDATE cache_sync_jobs
            SET status = 'paused', message = '程序已重启；点击继续可从断点恢复', updated_at = ?
            WHERE status = 'running'
            """,
            (now,),
        )
        conn.execute(
            "UPDATE cache_sync_items SET status = 'pending', updated_at = ? WHERE status = 'running'",
            (now,),
        )


def cache_summary() -> dict:
    init_market_cache()
    with _DB_LOCK, _connection() as conn:
        totals = conn.execute(
            """
            SELECT COUNT(*) AS kline_count, COUNT(DISTINCT symbol) AS stock_count,
                   MIN(time) AS first_kline_time, MAX(time) AS last_kline_time
            FROM market_klines
            """
        ).fetchone()
        periods = conn.execute(
            """
            SELECT period, COUNT(*) AS kline_count, COUNT(DISTINCT symbol) AS stock_count,
                   MIN(time) AS first_kline_time, MAX(time) AS last_kline_time
            FROM market_klines GROUP BY period ORDER BY period
            """
        ).fetchall()
    return {**dict(totals), "periods": [dict(row) for row in periods], "path": str(DB_PATH)}


def _update_sync_item(
    job_id: str,
    symbol: str,
    period: str,
    *,
    status: str,
    attempts_delta: int = 0,
    kline_count: int | None = None,
    source: str | None = None,
    first_kline_time: str | None = None,
    last_kline_time: str | None = None,
    message: str | None = None,
) -> None:
    init_market_cache()
    now = _now()
    with _DB_LOCK, _connection() as conn:
        conn.execute(
            """
            UPDATE cache_sync_items
            SET status = ?, attempts = attempts + ?,
                kline_count = COALESCE(?, kline_count),
                source = COALESCE(?, source),
                first_kline_time = COALESCE(?, first_kline_time),
                last_kline_time = COALESCE(?, last_kline_time),
                message = COALESCE(?, message), updated_at = ?
            WHERE job_id = ? AND symbol = ? AND period = ?
            """,
            (
                status,
                attempts_delta,
                kline_count,
                source,
                first_kline_time,
                last_kline_time,
                message,
                now,
                job_id,
                symbol,
                period,
            ),
        )


def _range_bounds(start_date: str, end_date: str) -> tuple[str, str]:
    start = _date_key(start_date)
    end = _date_key(end_date)
    if end < start:
        raise ValueError("end_date must not be earlier than start_date")
    return f"{start[:4]}-{start[4:6]}-{start[6:8]} 00:00:00", f"{end[:4]}-{end[4:6]}-{end[6:8]} 23:59:59"


def _date_key(value: str) -> str:
    normalized = str(value).strip()[:10].replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError("date must use YYYYMMDD or YYYY-MM-DD")
    return normalized


def _row_to_kline(index: int, row: sqlite3.Row) -> KLine:
    return KLine(
        index=index,
        time=str(row["time"]),
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
        volume=float(row["volume"]),
        amount=float(row["amount"]),
    )


@contextmanager
def _connection():
    conn = _connect()
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()
    finally:
        conn.close()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
