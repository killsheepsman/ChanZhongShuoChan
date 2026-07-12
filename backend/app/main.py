from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.chanlun import analyze_klines
from app.chanlun.kline import klines_from_frame
from app.chanlun.models import KLine
from app.services.signal_store import (
    count_current_symbols,
    init_signal_store,
    is_index_current,
    query_signal_matches,
    upsert_stock_signals,
)
from app.services.stock_data import (
    StockInfo,
    fetch_akshare_klines,
    fetch_stock_list,
    fetch_stock_name,
    filter_klines_to_range,
)


app = FastAPI(title="Chanlun Stock Analyzer", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_no_cache_for_frontend(request, call_next):
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response

_STOCK_CACHE: list[StockInfo] | None = None
_STOCK_CACHE_LOCK = threading.Lock()
_SCAN_JOBS: dict[str, dict] = {}
_SCAN_JOBS_LOCK = threading.Lock()

ANALYSIS_ENGINE = {
    "segment_engine": "state-machine-v2",
    "rule_profile": "三笔共同重叠成段；反向完整线段突破守卫后确认",
}


@app.on_event("startup")
def startup() -> None:
    init_signal_store()


@app.get("/api/health")
def health() -> dict[str, str]:
    init_signal_store()
    return {"status": "ok"}


@app.get("/api/stocks")
def stocks() -> dict:
    return {"stocks": [stock.__dict__ for stock in _get_stock_list_cached()]}


@app.get("/api/analyze")
def analyze_stock(
    symbol: str = Query("000001"),
    period: str = Query("daily"),
    start_date: str = Query(default_factory=lambda: (date.today() - timedelta(days=380)).strftime("%Y%m%d")),
    end_date: str = Query(default_factory=lambda: date.today().strftime("%Y%m%d")),
    adjust: Literal["", "qfq", "hfq"] = Query("qfq"),
) -> dict:
    fetch_result = fetch_akshare_klines(symbol, period, start_date, end_date, adjust)
    analysis = analyze_klines(fetch_result.klines)
    symbol_name = fetch_stock_name(symbol)
    first_kline = fetch_result.klines[0].time if fetch_result.klines else None
    last_kline = fetch_result.klines[-1].time if fetch_result.klines else None
    analysis["request"] = {
        "symbol": symbol,
        "symbol_name": symbol_name,
        "period": period,
        "start_date": start_date,
        "end_date": end_date,
        "adjust": adjust,
    }
    analysis["engine"] = ANALYSIS_ENGINE
    analysis["data_status"] = {
        "ok": fetch_result.ok,
        "source": fetch_result.source,
        "message": fetch_result.message,
        "refreshed_at": _now(),
        "first_kline_time": first_kline,
        "last_kline_time": last_kline,
        "source_first_kline_time": fetch_result.source_first_kline_time,
        "source_last_kline_time": fetch_result.source_last_kline_time,
        "kline_count": len(fetch_result.klines),
    }
    return analysis


@app.get("/api/signal-scan/start")
def start_signal_scan(
    signal_date: str = Query(...),
    period: str = Query("daily"),
    side: Literal["buy", "sell"] = Query("buy"),
    signal_type: int = Query(1, ge=1, le=3),
    adjust: Literal["", "qfq", "hfq"] = Query("qfq"),
    scan_limit: int = Query(0, ge=0),
    max_results: int = Query(300, ge=1, le=1000),
) -> dict:
    target_date = _normalize_signal_date(signal_date)
    stocks_to_scan = _get_stock_list_cached()
    if scan_limit > 0:
        stocks_to_scan = stocks_to_scan[:scan_limit]

    stock_codes = [stock.code for stock in stocks_to_scan]
    indexed_count = count_current_symbols(stock_codes, period, adjust, target_date)
    initial_matches = query_signal_matches(
        signal_date=target_date,
        period=period,
        adjust=adjust,
        side=side,
        signal_type=signal_type,
        max_results=max_results,
    )

    job_id = uuid.uuid4().hex
    job = {
        "job_id": job_id,
        "status": "running",
        "criteria": {
            "signal_date": target_date,
            "period": period,
            "side": side,
            "type": signal_type,
            "adjust": adjust,
        },
        "scan_range": {
            "start_date": _scan_start_date(target_date, period),
            "end_date": target_date,
        },
        "scanned_count": indexed_count,
        "failed_count": 0,
        "total_count": len(stocks_to_scan),
        "matched_count": len(initial_matches),
        "matches": initial_matches,
        "message": f"DB matched {len(initial_matches)} stocks; indexing missing stocks in background",
        "started_at": _now(),
        "refreshed_at": _now(),
    }
    with _SCAN_JOBS_LOCK:
        _SCAN_JOBS[job_id] = job

    thread = threading.Thread(target=_run_signal_scan_job, args=(job_id, stocks_to_scan, max_results), daemon=True)
    thread.start()
    return _public_job(job)


@app.get("/api/signal-scan/status/{job_id}")
def signal_scan_status(job_id: str) -> dict:
    with _SCAN_JOBS_LOCK:
        job = _SCAN_JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Signal scan job not found")
        return _public_job(job)


@app.get("/api/signal-scan")
def scan_by_signal(
    signal_date: str = Query(...),
    period: str = Query("daily"),
    side: Literal["buy", "sell"] = Query("buy"),
    signal_type: int = Query(1, ge=1, le=3),
    adjust: Literal["", "qfq", "hfq"] = Query("qfq"),
    scan_limit: int = Query(0, ge=0),
    max_results: int = Query(300, ge=1, le=1000),
) -> dict:
    start = start_signal_scan(signal_date, period, side, signal_type, adjust, scan_limit, max_results)
    job_id = start["job_id"]
    while True:
        with _SCAN_JOBS_LOCK:
            job = _SCAN_JOBS[job_id]
            if job["status"] in {"done", "failed"}:
                return _public_job(job)
        threading.Event().wait(0.5)


def _get_stock_list_cached() -> list[StockInfo]:
    global _STOCK_CACHE
    with _STOCK_CACHE_LOCK:
        if _STOCK_CACHE is None:
            _STOCK_CACHE = list(fetch_stock_list())
        return list(_STOCK_CACHE)


def _run_signal_scan_job(job_id: str, stocks_to_scan: list[StockInfo], max_results: int) -> None:
    with _SCAN_JOBS_LOCK:
        job = _SCAN_JOBS[job_id]
        criteria = dict(job["criteria"])
        start_date = job["scan_range"]["start_date"]
        end_date = job["scan_range"]["end_date"]

    stale_stocks = [
        stock
        for stock in stocks_to_scan
        if not is_index_current(stock.code, criteria["period"], criteria["adjust"], criteria["signal_date"])
    ]
    if not stale_stocks:
        _finish_job_from_db(job_id, max_results)
        return

    def scan_one(stock: StockInfo) -> bool:
        klines, source = _fetch_scan_klines(stock.code, criteria["period"], start_date, end_date, criteria["adjust"])
        if not klines:
            return False
        analysis = analyze_klines(klines)
        upsert_stock_signals(
            symbol=stock.code,
            name=stock.name,
            period=criteria["period"],
            adjust=criteria["adjust"],
            start_date=start_date,
            end_date=end_date,
            source=source,
            last_kline_time=klines[-1].time if klines else None,
            signals=analysis["signals"],
            updated_at=_now(),
        )
        return True

    try:
        max_workers = 12 if len(stale_stocks) >= 100 else 6
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(scan_one, stock) for stock in stale_stocks]
            for future in as_completed(futures):
                try:
                    ok = future.result()
                    _refresh_job_from_db(job_id, max_results, failed_increment=0 if ok else 1)
                except Exception:
                    _refresh_job_from_db(job_id, max_results, failed_increment=1)
        _finish_job_from_db(job_id, max_results)
    except Exception as exc:
        with _SCAN_JOBS_LOCK:
            job = _SCAN_JOBS[job_id]
            job["status"] = "failed"
            job["message"] = f"Scan failed: {exc}"
            job["refreshed_at"] = _now()


def _refresh_job_from_db(job_id: str, max_results: int, failed_increment: int = 0) -> None:
    with _SCAN_JOBS_LOCK:
        job = _SCAN_JOBS[job_id]
        criteria = dict(job["criteria"])
        job["scanned_count"] = min(job["total_count"], int(job["scanned_count"]) + 1)
        job["failed_count"] += failed_increment
        job["matches"] = query_signal_matches(
            signal_date=criteria["signal_date"],
            period=criteria["period"],
            adjust=criteria["adjust"],
            side=criteria["side"],
            signal_type=criteria["type"],
            max_results=max_results,
        )
        job["matched_count"] = len(job["matches"])
        job["message"] = f"Indexing {job['scanned_count']}/{job['total_count']}; DB matched {job['matched_count']}"
        job["refreshed_at"] = _now()


def _finish_job_from_db(job_id: str, max_results: int) -> None:
    with _SCAN_JOBS_LOCK:
        job = _SCAN_JOBS[job_id]
        criteria = dict(job["criteria"])
        job["matches"] = query_signal_matches(
            signal_date=criteria["signal_date"],
            period=criteria["period"],
            adjust=criteria["adjust"],
            side=criteria["side"],
            signal_type=criteria["type"],
            max_results=max_results,
        )
        job["matched_count"] = len(job["matches"])
        job["scanned_count"] = job["total_count"]
        job["status"] = "done"
        job["message"] = f"Scan done: indexed/reused {job['total_count']} stocks; matched {job['matched_count']}"
        job["refreshed_at"] = _now()


def _public_job(job: dict) -> dict:
    total = max(1, int(job.get("total_count", 0) or 1))
    scanned = int(job.get("scanned_count", 0) or 0)
    return {**job, "progress": min(100, round(scanned / total * 100, 1))}


def _fetch_scan_klines(symbol: str, period: str, start_date: str, end_date: str, adjust: str) -> tuple[list[KLine], str]:
    try:
        import akshare as ak

        if period == "daily":
            frame = ak.stock_zh_a_hist_tx(
                symbol=_market_symbol(symbol),
                start_date=start_date,
                end_date=end_date,
                adjust=adjust,
                timeout=10,
            )
            return filter_klines_to_range(klines_from_frame(frame), start_date, end_date), "akshare-tencent-daily"

        if period in {"1", "5", "15", "30", "60"}:
            frame = ak.stock_zh_a_hist_min_em(symbol=symbol, period=period, adjust=adjust)
            return filter_klines_to_range(klines_from_frame(frame), start_date, end_date), "akshare-eastmoney-minute"
    except Exception:
        return [], ""

    fetch_result = fetch_akshare_klines(symbol, period, start_date, end_date, adjust)
    return (fetch_result.klines, fetch_result.source) if fetch_result.ok else ([], "")


def _market_symbol(symbol: str) -> str:
    code = symbol.strip()
    if code.startswith(("6", "9")):
        return f"sh{code}"
    if code.startswith(("0", "2", "3")):
        return f"sz{code}"
    if code.startswith(("4", "8")):
        return f"bj{code}"
    return code


def _filter_minute_frame(frame, start_date: str, end_date: str):
    time_columns = [column for column in frame.columns if str(column) in {"时间", "日期", "datetime", "date", "time", "day"}]
    if not time_columns:
        return frame
    column = time_columns[0]
    values = frame[column].astype(str)
    start = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]} 00:00:00"
    end = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]} 23:59:59"
    return frame[(values >= start) & (values <= end)]


def _normalize_signal_date(value: str) -> str:
    normalized = value.strip().replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError("signal_date must be YYYYMMDD or YYYY-MM-DD")
    return normalized


def _scan_start_date(target_date: str, period: str) -> str:
    target = datetime.strptime(target_date, "%Y%m%d").date()
    lookback_days = 12 if period in {"1", "5", "15", "30", "60"} else 460
    return (target - timedelta(days=lookback_days)).strftime("%Y%m%d")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


_FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="frontend")
