from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.chanlun.models import KLine

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
CONFIG_PATH = DATA_DIR / "tdx2db_config.json"
TDX_DB_NAME = "chanlun_tdx"
TDX_DB_PATH = DATA_DIR / f"{TDX_DB_NAME}.db"
TDX_SH_DB_PATH = DATA_DIR / f"{TDX_DB_NAME}_sh.db"
TDX_SZ_DB_PATH = DATA_DIR / f"{TDX_DB_NAME}_sz.db"
STATS_PATH = DATA_DIR / "tdx2db_stats.json"
LOG_PATH = PROJECT_ROOT / "logs" / "tdx2db-sync.log"

_TABLES = {
    "daily": "daily_data",
    "5": "minute5_data",
    "15": "minute15_data",
    "30": "minute30_data",
    "60": "minute60_data",
}
_DERIVED_MINUTE_PERIODS = {"15": 3, "30": 6, "60": 12}
_DEFAULT_TDX_PATHS = (
    "C:/new_tdx64",
    "C:/new_tdx",
    "D:/new_tdx64",
    "D:/new_tdx",
    "C:/zd_zsone",
    "D:/zd_zsone",
    "C:/tdx",
    "D:/tdx",
)
_SYNC_LOCK = threading.Lock()
_SYNC_PROCESS: subprocess.Popen[str] | None = None
_SYNC_THREAD: threading.Thread | None = None
_SYNC_CANCEL_EVENT = threading.Event()
_SYNC_STATE: dict[str, Any] = {
    "status": "idle",
    "message": "Waiting for local TongDaXin configuration.",
    "started_at": None,
    "finished_at": None,
    "exit_code": None,
    "processed_stocks": 0,
    "total_stocks": 0,
    "daily_bars_imported": 0,
    "minute5_bars_imported": 0,
    "current_code": None,
    "daily_failed": 0,
}


def init_tdx2db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    config = _read_config()
    if not config.get("tdx_path"):
        detected = detect_tdx_path()
        if detected:
            _write_config({"tdx_path": detected})


def detect_tdx_path() -> str | None:
    for candidate in _DEFAULT_TDX_PATHS:
        if _is_tdx_path(candidate):
            return str(Path(candidate))
    return None


def configure_tdx2db(tdx_path: str) -> dict[str, Any]:
    normalized = str(Path(tdx_path).expanduser())
    if not _is_tdx_path(normalized):
        raise ValueError("The selected TongDaXin directory must contain the vipdoc folder.")
    _write_config({"tdx_path": normalized})
    return get_tdx2db_status()


def get_tdx2db_status() -> dict[str, Any]:
    # Keep the status endpoint useful even before FastAPI startup has run.
    init_tdx2db()
    config = _read_config()
    configured_path = str(config.get("tdx_path") or "")
    detected_path = detect_tdx_path()
    with _SYNC_LOCK:
        process = _SYNC_PROCESS
        thread = _SYNC_THREAD
        running = bool((process and process.poll() is None) or (thread and getattr(thread, "is_alive", lambda: False)()))
        sync = dict(_SYNC_STATE)
    sync["running"] = running
    return {
        "configured_path": configured_path,
        "detected_path": detected_path,
        "path_valid": _is_tdx_path(configured_path),
        "database_path": str(TDX_DB_PATH),
        "database_files": _database_files(),
        "installed": True,
        "executable": "项目内置本地导入器",
        "sync": sync,
        "tables": _database_summary(),
    }


def start_tdx2db_sync(full_history: bool = False) -> dict[str, Any]:
    init_tdx2db()
    _invalidate_stats_if_database_changed()
    config = _read_config()
    tdx_path = str(config.get("tdx_path") or "")
    if not _is_tdx_path(tdx_path):
        raise ValueError("TongDaXin data directory is not configured. Select the folder containing vipdoc first.")

    global _SYNC_THREAD
    sync_thread: threading.Thread | None = None
    with _SYNC_LOCK:
        thread_running = bool(_SYNC_THREAD and _SYNC_THREAD.is_alive())
        if not thread_running:
            _SYNC_CANCEL_EVENT.clear()
            _SYNC_STATE.update(
                {
                    "status": "running",
                    "message": "Reading local daily and 5-minute files into market shards.",
                    "started_at": _now(),
                    "finished_at": None,
                    "exit_code": None,
                    "processed_stocks": 0,
                    "total_stocks": 0,
                    "daily_bars_imported": 0,
                    "minute5_bars_imported": 0,
                    "current_code": None,
                    "daily_failed": 0,
                }
            )
            sync_thread = threading.Thread(
                target=_sync_local_daily_minute5,
                args=(tdx_path, full_history),
                daemon=True,
            )
            _SYNC_THREAD = sync_thread
    if sync_thread is not None:
        sync_thread.start()
    return get_tdx2db_status()


def stop_tdx2db_sync() -> dict[str, Any]:
    with _SYNC_LOCK:
        process = _SYNC_PROCESS
        if not process or process.poll() is not None:
            process = None
        if process is not None:
            process.terminate()
        thread = _SYNC_THREAD
        if thread is not None and thread.is_alive():
            _SYNC_CANCEL_EVENT.set()
        if process is not None or (thread is not None and thread.is_alive()):
            _SYNC_STATE.update({"status": "stopping", "message": "Stopping the local TongDaXin synchronization."})
    return get_tdx2db_status()


def optimize_tdx2db() -> dict[str, Any]:
    """Remove generated higher-period tables and compact the local SQLite file."""
    with _SYNC_LOCK:
        active = bool(_SYNC_THREAD and _SYNC_THREAD.is_alive()) or bool(_SYNC_PROCESS and _SYNC_PROCESS.poll() is None)
    if active:
        raise RuntimeError("请先停止通达信同步，再执行数据库清理")
    before = TDX_DB_PATH.stat().st_size if TDX_DB_PATH.exists() else 0
    removed: list[str] = []
    if TDX_DB_PATH.exists():
        with _db_connection() as conn:
            for table in ("minute15_data", "minute30_data", "minute60_data"):
                if _table_exists(conn, table):
                    conn.execute(f"DROP TABLE {table}")
                    removed.append(table)
            conn.commit()
            conn.execute("VACUUM")
    _write_stats_cache([])
    after = TDX_DB_PATH.stat().st_size if TDX_DB_PATH.exists() else 0
    return {**get_tdx2db_status(), "optimization": {"removed_tables": removed, "before_bytes": before, "after_bytes": after}}


def shutdown_tdx2db_sync(timeout: float = 5.0) -> None:
    """Stop project-owned synchronization when the API process exits."""
    global _SYNC_PROCESS
    with _SYNC_LOCK:
        process = _SYNC_PROCESS
        thread = _SYNC_THREAD
        _SYNC_CANCEL_EVENT.set()
        if process and process.poll() is None:
            process.terminate()
    if thread and thread.is_alive() and thread is not threading.current_thread():
        thread.join(timeout=timeout)
    if process and process.poll() is None:
        process.kill()
    _SYNC_PROCESS = None


def _sync_local_daily_minute5(tdx_path: str, full_history: bool) -> None:
    """Run the cancellable local importer in the API-owned thread.

    The importer currently writes the canonical 5-minute table and stock metadata;
    higher minute periods are derived on read and are never generated by sync.
    """
    _backfill_local_minute5_history(tdx_path)


def _backfill_local_minute5_history(tdx_path: str) -> None:
    """Import raw TongDaXin lc5 files directly, including bars older than the DB tail."""
    global _SYNC_THREAD
    imported_bars = 0
    imported_daily_bars = 0
    processed = 0
    failed = 0
    daily_failed = 0
    try:
        from tdx2db.reader import TdxDataReader

        reader = TdxDataReader(tdx_path)
        stocks = reader.get_stock_list()
        total = len(stocks.index)
        if total == 0:
            raise RuntimeError("No stocks were found in the configured TongDaXin data directory.")

        for _, stock in stocks.iterrows():
            if _SYNC_CANCEL_EVENT.is_set():
                break
            source_code = str(stock.get("code") or "")
            code = _plain_code(source_code)
            market = 1 if source_code.lower().startswith("sh") else 0
            try:
                try:
                    daily_frame = reader.read_daily_data(market, code)
                    daily_rows = _daily_rows_from_frame(daily_frame, code, market)
                    latest_daily = _latest_daily_date(code)
                    if latest_daily:
                        daily_rows = [row for row in daily_rows if row[2] > latest_daily]
                    imported_daily_bars += _upsert_daily_rows(daily_rows)
                except Exception as exc:
                    daily_failed += 1
                    _append_sync_log(f"{_now()}  Daily import failed for {source_code}: {exc}\\n")
                frame = reader.read_5min_data(market, code)
                rows = _minute5_rows_from_frame(frame, code, market)
                latest_time = _latest_minute5_time(code)
                if latest_time:
                    rows = [row for row in rows if row[2] > latest_time]
                imported_bars += _upsert_minute5_rows(rows)
                _upsert_stock_info(code, str(stock.get("name") or code), market)
            except FileNotFoundError:
                # TongDaXin may have daily data for a stock but no downloaded lc5 history.
                pass
            except Exception as exc:
                failed += 1
                _append_sync_log(f"{_now()}  Failed to import {source_code}: {exc}\\n")
            finally:
                processed += 1
                with _SYNC_LOCK:
                    _SYNC_STATE.update(
                        {
                            "processed_stocks": processed,
                            "total_stocks": total,
                            "daily_bars_imported": imported_daily_bars,
                            "minute5_bars_imported": imported_bars,
                            "daily_failed": daily_failed,
                            "current_code": code,
                            "message": (
                                f"日线 {processed}/{total} 只，新增 {imported_daily_bars:,} 根；"
                                f"5分钟新增 {imported_bars:,} 根；日线失败 {daily_failed} 只；当前 {code}。"
                            )
                        }
                    )

        cancelled = _SYNC_CANCEL_EVENT.is_set()
        with _SYNC_LOCK:
            _SYNC_THREAD = None
            if cancelled:
                _SYNC_STATE.update(
                    {
                        "status": "stopped",
                        "message": f"5分钟同步已停止：{processed}/{total} 只；累计 {imported_bars:,} 根。",
                        "finished_at": _now(),
                        "exit_code": None,
                    }
                )
            elif processed == 0:
                _SYNC_STATE.update(
                    {
                        "status": "failed",
                        "message": "没有处理到股票，请检查通达信目录。",
                        "finished_at": _now(),
                        "exit_code": 1,
                    }
                )
            else:
                failure_note = f" ({failed} files skipped)" if failed else ""
                _refresh_stats_snapshot()
                _SYNC_STATE.update(
                    {
                        "status": "completed",
                        "message": f"5分钟增量同步完成：{processed}/{total} 只；新增 {imported_bars:,} 根{failure_note}。",
                        "finished_at": _now(),
                        "exit_code": 0,
                    }
                )
    except Exception as exc:
        _append_sync_log(f"{_now()}  Local history import failed: {exc}\\n")
        with _SYNC_LOCK:
            _SYNC_THREAD = None
            _SYNC_STATE.update(
                {
                    "status": "failed",
                    "message": f"Local history import failed: {exc}",
                    "finished_at": _now(),
                    "exit_code": 1,
                }
            )


def _minute5_rows_from_frame(frame: Any, code: str, market: int) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    for item in frame.itertuples(index=False):
        timestamp = getattr(item, "datetime")
        if not hasattr(timestamp, "strftime"):
            continue
        rows.append(
            (
                code,
                market,
                timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                timestamp.strftime("%Y-%m-%d"),
                _number(getattr(item, "open", 0)),
                _number(getattr(item, "high", 0)),
                _number(getattr(item, "low", 0)),
                _number(getattr(item, "close", 0)),
                _number(getattr(item, "volume", 0)),
                _number(getattr(item, "amount", 0)),
            )
        )
    return rows


def _daily_rows_from_frame(frame: Any, code: str, market: int) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    has_date_column = "date" in getattr(frame, "columns", []) or "datetime" in getattr(frame, "columns", [])
    iterator = zip(frame.itertuples(index=False), frame.index) if not has_date_column else ((item, None) for item in frame.itertuples(index=False))
    for item, index_value in iterator:
        timestamp = getattr(item, "date", None)
        if timestamp is None:
            timestamp = getattr(item, "datetime", None)
        if timestamp is None:
            timestamp = index_value if index_value is not None else getattr(item, "name", None)
        if not hasattr(timestamp, "strftime"):
            continue
        rows.append((code, market, timestamp.strftime("%Y-%m-%d"), _number(getattr(item, "open", 0)), _number(getattr(item, "high", 0)), _number(getattr(item, "low", 0)), _number(getattr(item, "close", 0)), _number(getattr(item, "volume", 0)), _number(getattr(item, "amount", 0))))
    return rows


def _upsert_daily_rows(rows: list[tuple[Any, ...]]) -> int:
    if not rows:
        return 0
    with _db_connection() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS daily_data (id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL, market INTEGER NOT NULL, date TEXT NOT NULL, open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL, volume REAL NOT NULL, amount REAL NOT NULL, UNIQUE(code, date))")
        conn.executemany("INSERT INTO daily_data (code, market, date, open, high, low, close, volume, amount) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(code, date) DO UPDATE SET market=excluded.market, open=excluded.open, high=excluded.high, low=excluded.low, close=excluded.close, volume=excluded.volume, amount=excluded.amount", rows)
        conn.commit()
    return len(rows)


def _upsert_minute5_rows(rows: list[tuple[Any, ...]]) -> int:
    if not rows:
        return 0
    with _db_connection() as conn:
        _ensure_minute5_table(conn)
        conn.executemany(
            """
            INSERT INTO minute5_data (code, market, datetime, date, open, high, low, close, volume, amount)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(code, datetime) DO UPDATE SET
                market = excluded.market,
                date = excluded.date,
                open = excluded.open,
                high = excluded.high,
                low = excluded.low,
                close = excluded.close,
                volume = excluded.volume,
                amount = excluded.amount
            """,
            rows,
        )
        conn.commit()
    return len(rows)


def _latest_daily_date(code: str) -> str | None:
    if not TDX_DB_PATH.exists():
        return None
    try:
        with _db_connection() as conn:
            if not _table_exists(conn, "daily_data"):
                return None
            row = conn.execute("SELECT MAX(date) FROM daily_data WHERE code = ?", (code,)).fetchone()
            return str(row[0])[:10] if row and row[0] else None
    except sqlite3.Error:
        return None


def _latest_minute5_time(code: str) -> str | None:
    if not TDX_DB_PATH.exists():
        return None
    try:
        with _db_connection() as conn:
            if not _table_exists(conn, "minute5_data"):
                return None
            row = conn.execute("SELECT MAX(datetime) FROM minute5_data WHERE code = ?", (code,)).fetchone()
            return str(row[0]) if row and row[0] else None
    except sqlite3.Error:
        return None


def _upsert_stock_info(code: str, name: str, market: int) -> None:
    with _db_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS stock_info (
                id INTEGER PRIMARY KEY,
                code TEXT UNIQUE,
                name TEXT,
                market INTEGER
            )
            """
        )
        conn.execute(
            """
            INSERT INTO stock_info (code, name, market) VALUES (?, ?, ?)
            ON CONFLICT(code) DO UPDATE SET name = excluded.name, market = excluded.market
            """,
            (code, name, market),
        )
        conn.commit()


def _ensure_minute5_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS minute5_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            market INTEGER NOT NULL,
            datetime TEXT NOT NULL,
            date TEXT NOT NULL,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL NOT NULL,
            amount REAL NOT NULL,
            UNIQUE(code, datetime)
        )
        """
    )


def _append_sync_log(message: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(message)

def load_tdx2db_klines(symbol: str, period: str, start_date: str, end_date: str) -> list[KLine]:
    table = _TABLES.get(period)
    if not table or not TDX_DB_PATH.exists():
        return []
    code = _plain_code(symbol)
    start = _date_text(start_date)
    end = _date_text(end_date)
    query_table = "minute5_data" if period in _DERIVED_MINUTE_PERIODS else table
    time_column = "datetime" if period in _DERIVED_MINUTE_PERIODS else ("date" if period == "daily" else "datetime")
    try:
        with _db_connection() as conn:
            if not _table_exists(conn, query_table):
                return []
            rows = conn.execute(
                f"""
                SELECT {time_column} AS kline_time, open, high, low, close, volume, amount
                FROM {query_table}
                WHERE code = ? AND {time_column} >= ? AND {time_column} < date(?, '+1 day')
                ORDER BY {time_column}
                """,
                (code, start, end),
            ).fetchall()
    except sqlite3.Error:
        return []
    klines = [
        KLine(
            index=index,
            time=_time_text(row["kline_time"]),
            open=_number(row["open"]),
            high=_number(row["high"]),
            low=_number(row["low"]),
            close=_number(row["close"]),
            volume=_number(row["volume"]),
            amount=_number(row["amount"]),
        )
        for index, row in enumerate(rows)
    ]
    if period in _DERIVED_MINUTE_PERIODS:
        return _resample_session_klines(klines, _DERIVED_MINUTE_PERIODS[period])
    return klines


def _resample_session_klines(klines: list[KLine], bars_per_period: int) -> list[KLine]:
    """Aggregate 5-minute bars separately for the morning and afternoon A-share sessions."""
    sessions: dict[tuple[str, str], list[KLine]] = {}
    for item in klines:
        parsed = _parse_kline_time(item.time)
        if parsed is None:
            continue
        clock = parsed.strftime("%H:%M")
        if "09:35" <= clock <= "11:30":
            session = "morning"
        elif "13:05" <= clock <= "15:00":
            session = "afternoon"
        else:
            continue
        sessions.setdefault((parsed.strftime("%Y-%m-%d"), session), []).append(item)

    result: list[KLine] = []
    # Do not sort the textual labels directly: "afternoon" sorts before
    # "morning", which would scramble the resulting intraday timeline.
    session_order = {"morning": 0, "afternoon": 1}
    for _, session_bars in sorted(
        sessions.items(), key=lambda entry: (entry[0][0], session_order[entry[0][1]])
    ):
        session_bars.sort(key=lambda item: item.time)
        for offset in range(0, len(session_bars), bars_per_period):
            group = session_bars[offset : offset + bars_per_period]
            if len(group) != bars_per_period or not _is_contiguous_five_minutes(group):
                continue
            result.append(
                KLine(
                    index=len(result),
                    time=group[-1].time,
                    open=group[0].open,
                    high=max(item.high for item in group),
                    low=min(item.low for item in group),
                    close=group[-1].close,
                    volume=sum(item.volume for item in group),
                    amount=sum(item.amount for item in group),
                )
            )
    return result


def _is_contiguous_five_minutes(klines: list[KLine]) -> bool:
    timestamps = [_parse_kline_time(item.time) for item in klines]
    return all(
        current is not None and previous is not None and current - previous == timedelta(minutes=5)
        for previous, current in zip(timestamps, timestamps[1:])
    )


def _parse_kline_time(value: str) -> datetime | None:
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value, pattern)
        except ValueError:
            continue
    return None


def load_tdx2db_stocks() -> list[tuple[str, str]]:
    if not TDX_DB_PATH.exists():
        return []
    try:
        with _db_connection() as conn:
            if not _table_exists(conn, "stock_info"):
                return []
            rows = conn.execute(
                "SELECT code, name FROM stock_info WHERE code IS NOT NULL ORDER BY code"
            ).fetchall()
    except sqlite3.Error:
        return []
    stocks: dict[str, str] = {}
    for row in rows:
        code = _plain_code(row["code"])
        if len(code) == 6 and code.isdigit():
            stocks[code] = str(row["name"] or code)
    return sorted(stocks.items())


def load_tdx2db_stock_name(symbol: str) -> str | None:
    if not TDX_DB_PATH.exists():
        return None
    try:
        with _db_connection() as conn:
            if not _table_exists(conn, "stock_info"):
                return None
            code = _plain_code(symbol)
            row = conn.execute(
                "SELECT name FROM stock_info WHERE code = ? OR substr(code, -6) = ? LIMIT 1",
                (code, code),
            ).fetchone()
    except sqlite3.Error:
        return None
    return str(row["name"]) if row and row["name"] else None


def init_tdx2db_paths() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)


def _watch_sync_process(process: subprocess.Popen[str], log_handle: Any) -> None:
    exit_code = process.wait()
    log_handle.close()
    global _SYNC_PROCESS
    with _SYNC_LOCK:
        if _SYNC_PROCESS is process:
            _SYNC_PROCESS = None
        stopped_by_user = _SYNC_STATE.get("status") == "stopping"
        _SYNC_STATE.update(
            {
                "status": "stopped" if stopped_by_user else ("completed" if exit_code == 0 else "failed"),
                "message": (
                    "Local TongDaXin synchronization stopped by user."
                    if stopped_by_user
                    else ("Local TongDaXin synchronization completed." if exit_code == 0 else "tdx2db stopped with an error. Check logs/tdx2db-sync.log.")
                ),
                "finished_at": _now(),
                "exit_code": exit_code,
            }
        )


def _database_summary() -> list[dict[str, Any]]:
    if not TDX_DB_PATH.exists():
        return []
    cached = _read_stats_cache()
    if cached:
        return cached
    # Never perform a multi-GB aggregate during a status poll. The importer
    # writes this snapshot at completion; an absent snapshot means statistics
    # are intentionally unavailable until the next completed sync.
    return []


def _refresh_stats_snapshot() -> None:
    summaries: list[dict[str, Any]] = []
    try:
        with _db_connection() as conn:
            for period, table in _TABLES.items():
                if not _table_exists(conn, table):
                    continue
                time_column = "date" if period == "daily" else "datetime"
                row = conn.execute(f"SELECT COUNT(*) AS bars, COUNT(DISTINCT code) AS stocks, MIN({time_column}) AS first_time, MAX({time_column}) AS last_time FROM {table}").fetchone()
                summaries.append({"period": period, "table": table, "bar_count": int(row["bars"] or 0), "stock_count": int(row["stocks"] or 0), "first_time": _time_text(row["first_time"]) if row["first_time"] else None, "last_time": _time_text(row["last_time"]) if row["last_time"] else None})
    except sqlite3.Error:
        return
    _write_stats_cache(summaries)


def _database_files() -> list[dict[str, Any]]:
    return [
        {"path": str(path), "bytes": path.stat().st_size}
        for path in (TDX_DB_PATH, TDX_SH_DB_PATH, TDX_SZ_DB_PATH)
        if path.exists()
    ]


def _read_stats_cache() -> list[dict[str, Any]]:
    try:
        payload = json.loads(STATS_PATH.read_text(encoding="utf-8"))
        if payload.get("database_fingerprint") != _database_fingerprint():
            return []
        return payload.get("tables", []) if isinstance(payload, dict) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def _write_stats_cache(tables: list[dict[str, Any]]) -> None:
    try:
        STATS_PATH.write_text(json.dumps({"updated_at": _now(), "database_fingerprint": _database_fingerprint(), "tables": tables}, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _database_fingerprint() -> dict[str, Any] | None:
    if not TDX_DB_PATH.exists():
        return None
    try:
        stat = TDX_DB_PATH.stat()
        return {"path": str(TDX_DB_PATH), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    except OSError:
        return None


def _invalidate_stats_if_database_changed() -> None:
    try:
        payload = json.loads(STATS_PATH.read_text(encoding="utf-8"))
        if payload.get("database_fingerprint") != _database_fingerprint():
            STATS_PATH.unlink(missing_ok=True)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return


def _tdx2db_executable() -> str | None:
    bundled = PROJECT_ROOT / ".venv" / "Scripts" / "tdx2db.exe"
    if bundled.exists():
        return str(bundled)
    return shutil.which("tdx2db")


def _read_config() -> dict[str, Any]:
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_config(values: dict[str, Any]) -> None:
    current = _read_config()
    current.update(values)
    CONFIG_PATH.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")


def _is_tdx_path(value: str) -> bool:
    return bool(value) and (Path(value) / "vipdoc").is_dir()


def _plain_code(value: Any) -> str:
    text = str(value or "").strip()
    digits = "".join(char for char in text if char.isdigit())
    return digits[-6:].zfill(6) if digits else text[-6:].zfill(6)


@contextmanager
def _db_connection():
    connection = sqlite3.connect(TDX_DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
    finally:
        connection.close()


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    return row is not None


def _date_text(value: str) -> str:
    digits = "".join(char for char in str(value) if char.isdigit())
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return str(value)[:10]


def _time_text(value: Any) -> str:
    text = str(value)
    return text.replace("T", " ")[:19]


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
