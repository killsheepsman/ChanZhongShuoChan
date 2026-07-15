from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import zlib
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from app.chanlun.analyzer import ANALYSIS_ENGINE_VERSION, analyze_klines, continue_analysis
from app.chanlun.models import KLine


DB_PATH = Path(__file__).resolve().parents[3] / "data" / "analysis_cache.sqlite3"
_DB_LOCK = threading.Lock()


def init_analysis_cache() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _DB_LOCK, _connection() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS analysis_snapshots (
                symbol TEXT NOT NULL,
                period TEXT NOT NULL,
                adjust TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                engine_version TEXT NOT NULL,
                raw_count INTEGER NOT NULL,
                first_kline_time TEXT,
                last_kline_time TEXT,
                raw_hash TEXT NOT NULL,
                payload BLOB NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (symbol, period, adjust, start_date)
            )
            """
        )


def analyze_with_cache(
    *, symbol: str, period: str, adjust: str, start_date: str, end_date: str, klines: list[KLine]
) -> dict:
    init_analysis_cache()
    cached = _load(symbol, period, adjust, start_date)
    current_hash = _raw_hash(klines)
    mode = "rebuild"
    new_count = len(klines)
    recomputed_from = klines[0].time if klines else None

    if cached and cached["engine_version"] == ANALYSIS_ENGINE_VERSION:
        cached_count = int(cached["raw_count"])
        if cached_count == len(klines) and cached["raw_hash"] == current_hash:
            result = cached["result"]
            mode = "hit"
            new_count = 0
            recomputed_from = None
        elif cached_count < len(klines) and cached["raw_hash"] == _raw_hash(klines[:cached_count]):
            result, metadata = continue_analysis(cached["result"], klines)
            mode = metadata["mode"]
            new_count = metadata["new_kline_count"]
            recomputed_from = metadata["recomputed_from_time"]
        else:
            result = analyze_klines(klines)
    else:
        result = analyze_klines(klines)

    updated_at = _now()
    result["analysis_cache"] = {
        "mode": mode,
        "hit": mode == "hit",
        "new_kline_count": new_count,
        "recomputed_from_time": recomputed_from,
        "engine_version": ANALYSIS_ENGINE_VERSION,
        "updated_at": cached["updated_at"] if mode == "hit" and cached else updated_at,
    }
    if mode != "hit":
        _save(
            symbol=symbol,
            period=period,
            adjust=adjust,
            start_date=start_date,
            end_date=end_date,
            klines=klines,
            raw_hash=current_hash,
            result=result,
            updated_at=updated_at,
        )
    return result


def _load(symbol: str, period: str, adjust: str, start_date: str) -> dict[str, Any] | None:
    with _DB_LOCK, _connection() as conn:
        row = conn.execute(
            """
            SELECT engine_version, raw_count, raw_hash, payload, updated_at
            FROM analysis_snapshots
            WHERE symbol = ? AND period = ? AND adjust = ? AND start_date = ?
            """,
            (symbol, period, adjust, start_date),
        ).fetchone()
    if not row:
        return None
    try:
        result = json.loads(zlib.decompress(row["payload"]).decode("utf-8"))
    except (json.JSONDecodeError, zlib.error, UnicodeDecodeError):
        return None
    return {
        "engine_version": row["engine_version"],
        "raw_count": row["raw_count"],
        "raw_hash": row["raw_hash"],
        "updated_at": row["updated_at"],
        "result": result,
    }


def _save(
    *,
    symbol: str,
    period: str,
    adjust: str,
    start_date: str,
    end_date: str,
    klines: list[KLine],
    raw_hash: str,
    result: dict,
    updated_at: str,
) -> None:
    payload = zlib.compress(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), level=6)
    with _DB_LOCK, _connection() as conn:
        conn.execute(
            """
            INSERT INTO analysis_snapshots (
                symbol, period, adjust, start_date, end_date, engine_version,
                raw_count, first_kline_time, last_kline_time, raw_hash, payload, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, period, adjust, start_date) DO UPDATE SET
                end_date = excluded.end_date,
                engine_version = excluded.engine_version,
                raw_count = excluded.raw_count,
                first_kline_time = excluded.first_kline_time,
                last_kline_time = excluded.last_kline_time,
                raw_hash = excluded.raw_hash,
                payload = excluded.payload,
                updated_at = excluded.updated_at
            """,
            (
                symbol,
                period,
                adjust,
                start_date,
                end_date,
                ANALYSIS_ENGINE_VERSION,
                len(klines),
                klines[0].time if klines else None,
                klines[-1].time if klines else None,
                raw_hash,
                payload,
                updated_at,
            ),
        )


def _raw_hash(klines: list[KLine]) -> str:
    digest = hashlib.sha256()
    for item in klines:
        digest.update(
            f"{item.time}|{item.open:.10g}|{item.high:.10g}|{item.low:.10g}|{item.close:.10g}|{item.volume:.10g}|{item.amount:.10g}\n".encode()
        )
    return digest.hexdigest()


@contextmanager
def _connection():
    connection = sqlite3.connect(DB_PATH, timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
