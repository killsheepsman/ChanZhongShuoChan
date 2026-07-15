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
    executable = _tdx2db_executable()
    with _SYNC_LOCK:
        process = _SYNC_PROCESS
        thread = _SYNC_THREAD
        running = bool((process and process.poll() is None) or (thread and thread.is_alive()))
        sync = dict(_SYNC_STATE)
    sync["running"] = running
    return {
        "configured_path": configured_path,
        "detected_path": detected_path,
        "path_valid": _is_tdx_path(configured_path),
        "database_path": str(TDX_DB_PATH),
        "installed": bool(executable),
        "executable": executable or "",
        "sync": sync,
        "tables": _database_summary(),
    }


def start_tdx2db_sync(full_history: bool = False) -> dict[str, Any]:
    init_tdx2db()
    config = _read_config()
    tdx_path = str(config.get("tdx_path") or "")
    if not _is_tdx_path(tdx_path):
        raise ValueError("TongDaXin data directory is not configured. Select the folder containing vipdoc first.")

    global _SYNC_PROCESS, _SYNC_THREAD
    if full_history:
        history_thread: threading.Thread | None = None
        with _SYNC_LOCK:
            process_running = bool(_SYNC_PROCESS and _SYNC_PROCESS.poll() is None)
            thread_running = bool(_SYNC_THREAD and _SYNC_THREAD.is_alive())
            if not process_running and not thread_running:
                _SYNC_CANCEL_EVENT.clear()
                _SYNC_STATE.update(
                    {
                        "status": "running",
                        "message": "Reading local TongDaXin .lc5 history into the project database.",
                        "started_at": _now(),
                        "finished_at": None,
                        "exit_code": None,
                    }
                )
                history_thread = threading.Thread(
                    target=_backfill_local_minute5_history,
                    args=(tdx_path,),
                    daemon=True,
                )
                _SYNC_THREAD = history_thread
        if history_thread is not None:
            history_thread.start()
        return get_tdx2db_status()

    executable = _tdx2db_executable()
    if not executable:
        raise RuntimeError("tdx2db is not installed. Run the project's Install Dependencies command after the network is available.")

    watcher: threading.Thread | None = None
    with _SYNC_LOCK:
        process_running = bool(_SYNC_PROCESS and _SYNC_PROCESS.poll() is None)
        thread_running = bool(_SYNC_THREAD and _SYNC_THREAD.is_alive())
        if not process_running and not thread_running:
            log_handle = LOG_PATH.open("a", encoding="utf-8")
            command = [
                executable,
                "--tdx-path",
                tdx_path,
                "--db-type",
                "sqlite",
                "--db-name",
                TDX_DB_NAME,
                "--no-tqdm",
                "sync",
            ]
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            try:
                process = subprocess.Popen(
                    command,
                    cwd=str(DATA_DIR),
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    text=True,
                    creationflags=creationflags,
                )
            except Exception:
                log_handle.close()
                raise

            _SYNC_PROCESS = process
            _SYNC_STATE.update(
                {
                    "status": "running",
                    "message": "TongDaXin local files are synchronizing incrementally.",
                    "started_at": _now(),
                    "finished_at": None,
                    "exit_code": None,
                }
            )
            watcher = threading.Thread(target=_watch_sync_process, args=(process, log_handle), daemon=True)

    if watcher is not None:
        watcher.start()
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


def _backfill_local_minute5_history(tdx_path: str) -> None:
    """Import raw TongDaXin lc5 files directly, including bars older than the DB tail."""
    global _SYNC_THREAD
    imported_bars = 0
    processed = 0
    failed = 0
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
                frame = reader.read_5min_data(market, code)
                imported_bars += _upsert_minute5_rows(_minute5_rows_from_frame(frame, code, market))
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
                            "message": (
                                f"Local 5-minute history: {processed}/{total} stocks, "
                                f"{imported_bars:,} bars imported; current {code}."
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
                        "message": f"Local history import stopped after {processed}/{total} stocks; {imported_bars:,} bars imported.",
                        "finished_at": _now(),
                        "exit_code": None,
                    }
                )
            elif imported_bars == 0:
                _SYNC_STATE.update(
                    {
                        "status": "failed",
                        "message": "No readable local 5-minute bars were imported. Check the configured TongDaXin directory and lc5 files.",
                        "finished_at": _now(),
                        "exit_code": 1,
                    }
                )
            else:
                failure_note = f" ({failed} files skipped)" if failed else ""
                _SYNC_STATE.update(
                    {
                        "status": "completed",
                        "message": f"Local 5-minute history import completed: {processed}/{total} stocks, {imported_bars:,} bars written{failure_note}.",
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
    summaries: list[dict[str, Any]] = []
    try:
        with _db_connection() as conn:
            for period, table in _TABLES.items():
                if not _table_exists(conn, table):
                    continue
                time_column = "date" if period == "daily" else "datetime"
                row = conn.execute(
                    f"SELECT COUNT(*) AS bars, COUNT(DISTINCT code) AS stocks, MIN({time_column}) AS first_time, MAX({time_column}) AS last_time FROM {table}"
                ).fetchone()
                summaries.append(
                    {
                        "period": period,
                        "table": table,
                        "bar_count": int(row["bars"] or 0),
                        "stock_count": int(row["stocks"] or 0),
                        "first_time": _time_text(row["first_time"]) if row["first_time"] else None,
                        "last_time": _time_text(row["last_time"]) if row["last_time"] else None,
                    }
                )
    except sqlite3.Error:
        return []
    return summaries


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
