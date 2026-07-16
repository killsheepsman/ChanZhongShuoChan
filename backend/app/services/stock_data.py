from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable

import pandas as pd

from app.chanlun.kline import klines_from_frame
from app.chanlun.models import KLine
from app.services.market_cache import (
    cache_request_checked_today,
    get_cache_state,
    load_cached_klines,
    record_cache_check,
    upsert_cached_klines,
)
from app.services.tdx2db_service import (
    load_tdx2db_klines,
    load_tdx2db_stock_name,
    load_tdx2db_stocks,
)


@dataclass(frozen=True)
class KLineFetchResult:
    klines: list[KLine]
    source: str
    ok: bool
    message: str
    source_first_kline_time: str | None = None
    source_last_kline_time: str | None = None
    from_cache: bool = False
    cache_updated: bool = False
    failed_sources: tuple[dict[str, str], ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class StockInfo:
    code: str
    name: str


FALLBACK_STOCKS = [
    StockInfo("000001", "平安银行"),
    StockInfo("000002", "万科A"),
    StockInfo("600000", "浦发银行"),
    StockInfo("600519", "贵州茅台"),
]


def fetch_stock_name(symbol: str) -> str:
    local_name = load_tdx2db_stock_name(symbol)
    if local_name:
        return local_name
    fallback_names = {stock.code: stock.name for stock in FALLBACK_STOCKS}
    try:
        import akshare as ak

        frame = ak.stock_info_a_code_name()
        code_col, name_col = _code_name_columns(frame)
        matched = frame.loc[frame[code_col].astype(str).str.zfill(6) == symbol]
        if matched.empty:
            return fallback_names.get(symbol, symbol)
        return str(matched.iloc[0][name_col])
    except Exception:
        return fallback_names.get(symbol, symbol)


def fetch_stock_list() -> list[StockInfo]:
    local_stocks = [StockInfo(code, name) for code, name in load_tdx2db_stocks()]
    if len(local_stocks) >= 100:
        return sorted(local_stocks, key=lambda item: item.code)
    try:
        import akshare as ak

        frame = ak.stock_info_a_code_name()
        code_col, name_col = _code_name_columns(frame)
        stocks = [
            StockInfo(str(row[code_col]).zfill(6), str(row[name_col]))
            for _, row in frame.iterrows()
            if str(row[code_col]).strip()
        ]
        return sorted(stocks, key=lambda item: item.code) or FALLBACK_STOCKS
    except Exception:
        return FALLBACK_STOCKS


def fetch_akshare_klines(
    symbol: str,
    period: str,
    start_date: str,
    end_date: str,
    adjust: str,
) -> KLineFetchResult:
    try:
        import akshare as ak
    except ImportError as exc:
        return KLineFetchResult(_sample_klines(), "sample", False, f"AKShare 未安装，已使用示例数据：{exc}")

    attempts: list[tuple[str, str, Callable[[], pd.DataFrame]]] = []
    if period in {"1", "5", "15", "30", "60"}:
        attempts = [
            (
                "akshare-eastmoney-minute",
                "AKShare-东方财富分钟",
                lambda: _filter_minute_frame(
                    ak.stock_zh_a_hist_min_em(symbol=symbol, period=period, adjust=adjust),
                    start_date,
                    end_date,
                ),
            ),
            (
                "akshare-sina-minute",
                "AKShare-新浪分钟",
                lambda: _filter_minute_frame(
                    ak.stock_zh_a_minute(symbol=_market_symbol(symbol), period=period, adjust=adjust),
                    start_date,
                    end_date,
                ),
            ),
        ]
    else:
        attempts = [
            (
                "akshare-eastmoney-hist",
                "AKShare-东方财富历史",
                lambda: ak.stock_zh_a_hist(
                    symbol=symbol,
                    period=period,
                    start_date=start_date,
                    end_date=end_date,
                    adjust=adjust,
                ),
            )
        ]
        if period == "daily":
            attempts.extend(
                [
                    (
                        "akshare-sina-daily",
                        "AKShare-新浪日线",
                        lambda: ak.stock_zh_a_daily(
                            symbol=_market_symbol(symbol),
                            start_date=start_date,
                            end_date=end_date,
                            adjust=adjust,
                        ),
                    ),
                    (
                        "akshare-tencent-daily",
                        "AKShare-腾讯日线",
                        lambda: ak.stock_zh_a_hist_tx(
                            symbol=_market_symbol(symbol),
                            start_date=start_date,
                            end_date=end_date,
                            adjust=adjust,
                            timeout=15,
                        ),
                    ),
                ]
            )

    if period in _BAOSTOCK_FREQUENCIES:
        attempts.append(
            (
                "baostock",
                "BaoStock 免费历史行情",
                lambda: _fetch_baostock_klines(symbol, period, start_date, end_date, adjust),
            )
        )

    if period in _TDX_KLINE_CATEGORIES:
        attempts.append(
            (
                "tdx-public",
                "通达信公共行情（不复权）",
                lambda: _fetch_tdx_klines(symbol, period, start_date, end_date),
            )
        )

    errors: list[str] = []
    failed_sources: list[dict[str, str]] = []
    for source, label, loader in attempts:
        try:
            loaded = loader()
            source_klines = loaded if isinstance(loaded, list) else klines_from_frame(loaded)
            if not source_klines:
                error = "返回空数据"
                errors.append(f"{label}: {error}")
                failed_sources.append({"source": source, "label": label, "error": error})
                continue
            klines = filter_klines_to_range(source_klines, start_date, end_date)
            if not klines:
                error = "返回数据与请求区间没有重叠"
                errors.append(f"{label}: {error}")
                failed_sources.append({"source": source, "label": label, "error": error})
                continue

            source_first = source_klines[0].time
            source_last = source_klines[-1].time
            return KLineFetchResult(
                klines,
                source,
                True,
                _fetch_message(label, source_first, source_last, start_date, end_date),
                source_first,
                source_last,
                failed_sources=tuple(failed_sources),
            )
        except Exception as exc:
            error = _provider_error_text(exc)
            errors.append(f"{label}: {error}")
            failed_sources.append({"source": source, "label": label, "error": error})

    sample_message = "；".join(errors) if errors else "所有数据源均未返回数据"
    sample_klines = filter_klines_to_range(_sample_klines(), start_date, end_date)
    return KLineFetchResult(
        sample_klines,
        "sample",
        False,
        f"真实数据源全部失败，已使用示例数据：{sample_message}",
        failed_sources=tuple(failed_sources),
    )


def fetch_cached_or_akshare_klines(
    symbol: str,
    period: str,
    start_date: str,
    end_date: str,
    adjust: str,
    allow_external: bool = False,
) -> KLineFetchResult:
    """Read local TongDaXin/cache data first; online providers are opt-in supplements."""
    if allow_external:
        # Realtime mode must not remain pinned to yesterday's saved form value.
        today_key = datetime.now().strftime("%Y%m%d")
        if _date_key(end_date) < today_key:
            end_date = today_key
    tdx_klines = load_tdx2db_klines(symbol, period, start_date, end_date)
    cached = load_cached_klines(symbol, period, adjust, start_date, end_date)
    state = get_cache_state(symbol, period, adjust)
    local_klines = _merge_local_klines(tdx_klines, cached)
    local_source = _local_source_name(tdx_klines, cached)

    if local_klines and (not allow_external or _last_kline_date(local_klines) >= _date_key(end_date)):
        return KLineFetchResult(
            local_klines,
            local_source,
            True,
            _local_result_message(local_klines, start_date, end_date, allow_external),
            local_klines[0].time,
            local_klines[-1].time,
            from_cache=True,
        )

    if not allow_external:
        if local_klines:
            return KLineFetchResult(
                local_klines,
                local_source,
                True,
                _local_result_message(local_klines, start_date, end_date, False),
                local_klines[0].time,
                local_klines[-1].time,
                from_cache=True,
            )
        return KLineFetchResult(
            [],
            "local-only",
            False,
            "No local TongDaXin or project-cache K-lines cover this request. External supplementation is off; sync the local TongDaXin files or enable external supplementation.",
        )

    fetch_start = _next_request_date(local_klines[-1].time) if local_klines else _incremental_fetch_start(state, start_date)
    if _date_key(fetch_start) > _date_key(end_date):
        return KLineFetchResult(
            local_klines,
            local_source,
            bool(local_klines),
            _local_result_message(local_klines, start_date, end_date, True),
            local_klines[0].time if local_klines else None,
            local_klines[-1].time if local_klines else None,
            from_cache=bool(local_klines),
        )

    fetch_result = fetch_akshare_klines(symbol, period, fetch_start, end_date, adjust)
    if fetch_result.ok:
        local_last = local_klines[-1].time if local_klines else None
        provider_last = fetch_result.source_last_kline_time
        if local_last and provider_last and _date_key(provider_last) <= _date_key(local_last):
            message = (
                f"外部数据未更新：本地最新 {local_last}，外部源最新 {provider_last}；"
                f"已尝试请求 {fetch_start} 至 {end_date}。"
            )
            return KLineFetchResult(
                local_klines,
                f"{local_source}+external-not-updated",
                True,
                message,
                local_klines[0].time,
                local_klines[-1].time,
                from_cache=True,
                failed_sources=fetch_result.failed_sources,
            )
        upsert_cached_klines(
            symbol=symbol,
            period=period,
            adjust=adjust,
            klines=fetch_result.klines,
            source=fetch_result.source,
            requested_start=fetch_start,
            requested_end=end_date,
        )
        refreshed_cache = load_cached_klines(symbol, period, adjust, start_date, end_date)
        merged = _merge_local_klines(tdx_klines, refreshed_cache)
        merged_source = _local_source_name(tdx_klines, refreshed_cache)
        return KLineFetchResult(
            merged,
            f"{merged_source}+{fetch_result.source}" if tdx_klines else f"local-cache+{fetch_result.source}",
            True,
            f"{_local_result_message(merged, start_date, end_date, True)} External supplementation requested {fetch_start} to {end_date}; provider returned through {fetch_result.source_last_kline_time}; saved to project cache.",
            merged[0].time if merged else fetch_result.source_first_kline_time,
            merged[-1].time if merged else fetch_result.source_last_kline_time,
            from_cache=bool(local_klines),
            cache_updated=True,
            failed_sources=fetch_result.failed_sources,
        )

    record_cache_check(
        symbol=symbol,
        period=period,
        adjust=adjust,
        source=fetch_result.source,
        requested_start=fetch_start,
        requested_end=end_date,
        error=fetch_result.message,
    )
    if local_klines:
        return KLineFetchResult(
            local_klines,
            local_source,
            True,
            f"{_local_result_message(local_klines, start_date, end_date, True)} External supplementation failed: {fetch_result.message}",
            local_klines[0].time,
            local_klines[-1].time,
            from_cache=True,
            failed_sources=fetch_result.failed_sources,
        )
    return fetch_result


def _merge_local_klines(*collections: list[KLine]) -> list[KLine]:
    """Merge local sources by timestamp while keeping TongDaXin bars ahead of cached bars."""
    by_time: dict[str, KLine] = {}
    for collection in collections:
        for item in collection:
            by_time.setdefault(item.time, item)
    return [
        KLine(
            index=index,
            time=item.time,
            open=item.open,
            high=item.high,
            low=item.low,
            close=item.close,
            volume=item.volume,
            amount=item.amount,
        )
        for index, item in enumerate(sorted(by_time.values(), key=lambda item: item.time))
    ]


def _local_source_name(tdx_klines: list[KLine], cached: list[KLine]) -> str:
    if tdx_klines and cached:
        return "tdx2db-local+local-cache"
    if tdx_klines:
        return "tdx2db-local"
    return "local-cache"


def _local_result_message(klines: list[KLine], start_date: str, end_date: str, allow_external: bool) -> str:
    if not klines:
        return "No local K-lines are available."
    range_text = f"{klines[0].time} to {klines[-1].time}"
    request_text = f"{_date_key(start_date)} to {_date_key(end_date)}"
    policy = "External supplementation is enabled." if allow_external else "External supplementation is off."
    return f"Loaded {len(klines)} local K-lines ({range_text}); requested {request_text}. {policy}"


def _last_kline_date(klines: list[KLine]) -> str:
    return _date_key(klines[-1].time)


def _next_request_date(value: str) -> str:
    return (datetime.strptime(_date_key(value), "%Y%m%d").date() + timedelta(days=1)).strftime("%Y%m%d")


_BAOSTOCK_FREQUENCIES = {"5": "5", "15": "15", "30": "30", "60": "60", "daily": "d", "weekly": "w", "monthly": "m"}
_BAOSTOCK_LOCK = threading.Lock()


def _fetch_baostock_klines(symbol: str, period: str, start_date: str, end_date: str, adjust: str) -> list[KLine]:
    """Fetch free historical bars from BaoStock. Its login session is process-global, so serialize access."""
    try:
        import baostock as bs
    except ImportError as exc:
        raise RuntimeError(f"BaoStock 未安装：{exc}") from exc

    frequency = _BAOSTOCK_FREQUENCIES.get(period)
    if frequency is None:
        raise ValueError(f"BaoStock 暂不支持周期 {period}")
    code = _baostock_symbol(symbol)
    if code is None:
        raise ValueError(f"BaoStock 暂不支持市场代码 {symbol}")

    with _BAOSTOCK_LOCK:
        login = bs.login()
        if str(login.error_code) != "0":
            raise RuntimeError(f"登录失败：{login.error_code} {login.error_msg}")
        try:
            result = bs.query_history_k_data_plus(
                code,
                "date,time,code,open,high,low,close,volume,amount",
                start_date=_format_baostock_date(start_date),
                end_date=_format_baostock_date(end_date),
                frequency=frequency,
                adjustflag={"qfq": "2", "hfq": "1"}.get(adjust, "3"),
            )
            if str(result.error_code) != "0":
                raise RuntimeError(f"查询失败：{result.error_code} {result.error_msg}")
            rows: list[KLine] = []
            while result.next():
                row = result.get_row_data()
                if len(row) < 9:
                    continue
                rows.append(
                    KLine(
                        index=len(rows),
                        time=_baostock_time(row[0], row[1], frequency),
                        open=_float_or_zero(row[3]),
                        high=_float_or_zero(row[4]),
                        low=_float_or_zero(row[5]),
                        close=_float_or_zero(row[6]),
                        volume=_float_or_zero(row[7]),
                        amount=_float_or_zero(row[8]),
                    )
                )
            return rows
        finally:
            bs.logout()


def _baostock_symbol(symbol: str) -> str | None:
    code = symbol.strip()
    if code.startswith(("6", "9")):
        return f"sh.{code}"
    if code.startswith(("0", "2", "3")):
        return f"sz.{code}"
    return None


def _format_baostock_date(value: str) -> str:
    return _parse_request_date(value).strftime("%Y-%m-%d")


def _baostock_time(day: str, raw_time: str, frequency: str) -> str:
    if frequency in {"d", "w", "m"} or not raw_time or raw_time == "0":
        return str(day)
    digits = "".join(char for char in str(raw_time) if char.isdigit())
    if len(digits) >= 14:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]} {digits[8:10]}:{digits[10:12]}:{digits[12:14]}"
    return str(day)


def _float_or_zero(value: str) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


_TDX_KLINE_CATEGORIES = {"1": 8, "5": 0, "15": 1, "30": 2, "60": 3, "daily": 4}
_TDX_SERVERS = (
    ("119.147.212.81", 7709),
    ("119.147.212.82", 7709),
    ("61.152.107.141", 7709),
)


def _fetch_tdx_klines(symbol: str, period: str, start_date: str, end_date: str) -> list[KLine]:
    """Read unadjusted bars from a public TongDaXin server and clip them to the request."""
    try:
        from pytdx.hq import TdxHq_API
    except ImportError as exc:
        raise RuntimeError(f"pytdx 未安装：{exc}") from exc

    category = _TDX_KLINE_CATEGORIES.get(period)
    market = _tdx_market(symbol)
    if category is None:
        raise ValueError(f"通达信暂不支持周期 {period}")
    if market is None:
        raise ValueError(f"通达信公共行情暂不支持市场代码 {symbol}")

    request_start, _ = _request_boundaries(start_date, end_date)
    errors: list[str] = []
    for host, port in _TDX_SERVERS:
        api = TdxHq_API(raise_exception=False)
        try:
            if not api.connect(host, port, time_out=5):
                errors.append(f"{host}:{port} 连接失败")
                continue
            rows_by_time: dict[str, KLine] = {}
            # The protocol returns at most 800 bars per request, newest-first by offset.
            # Cap the loop so an unavailable public archive cannot stall cache synchronization.
            for offset in range(0, 25_600, 800):
                bars = api.get_security_bars(category, market, symbol, offset, 800) or []
                if not bars:
                    break
                oldest: datetime | None = None
                for bar in bars:
                    timestamp = _tdx_bar_time(bar, period)
                    parsed = _parse_kline_time(timestamp)
                    if parsed is None:
                        continue
                    oldest = parsed if oldest is None or parsed < oldest else oldest
                    rows_by_time[timestamp] = KLine(
                        index=0,
                        time=timestamp,
                        open=float(bar.get("open", 0.0)),
                        high=float(bar.get("high", 0.0)),
                        low=float(bar.get("low", 0.0)),
                        close=float(bar.get("close", 0.0)),
                        volume=float(bar.get("vol", 0.0)),
                        amount=float(bar.get("amount", 0.0)),
                    )
                if len(bars) < 800 or (oldest is not None and oldest <= request_start):
                    break
            rows = list(rows_by_time.values())
            rows.sort(key=lambda item: _parse_kline_time(item.time) or datetime.min)
            clipped = filter_klines_to_range(rows, start_date, end_date)
            if clipped:
                return clipped
            errors.append(f"{host}:{port} 未返回请求区间内K线")
        except Exception as exc:
            errors.append(f"{host}:{port} {_provider_error_text(exc)}")
        finally:
            try:
                api.disconnect()
            except Exception:
                pass
    raise RuntimeError("通达信公共服务器均不可用：" + "；".join(errors))


def _tdx_market(symbol: str) -> int | None:
    code = symbol.strip()
    if code.startswith(("6", "9")):
        return 1
    if code.startswith(("0", "2", "3")):
        return 0
    return None


def _tdx_bar_time(bar: dict, period: str) -> str:
    date_text = f"{int(bar['year']):04d}-{int(bar['month']):02d}-{int(bar['day']):02d}"
    if period == "daily":
        return date_text
    return f"{date_text} {int(bar.get('hour', 0)):02d}:{int(bar.get('minute', 0)):02d}:00"


def _provider_error_text(exc: Exception) -> str:
    text = str(exc).strip().replace("\n", " ")
    return text[:240] if text else exc.__class__.__name__


def _cache_state_covers_request(state: dict | None, start_date: str, end_date: str) -> bool:
    if not state or not state.get("first_kline_time") or not state.get("last_kline_time"):
        return False
    first = _date_key(str(state["first_kline_time"]))
    last = _date_key(str(state["last_kline_time"]))
    return first <= _date_key(start_date) and last >= _date_key(end_date)


def _incremental_fetch_start(state: dict | None, requested_start: str) -> str:
    if not state or not state.get("first_kline_time") or not state.get("last_kline_time"):
        return requested_start
    if _date_key(str(state["first_kline_time"])) > _date_key(requested_start):
        return requested_start
    return max(_date_key(requested_start), _date_key(str(state["last_kline_time"])))


def _date_key(value: str) -> str:
    normalized = str(value).strip()[:10].replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError("date must use YYYYMMDD or YYYY-MM-DD")
    return normalized


def _code_name_columns(frame: pd.DataFrame) -> tuple[str, str]:
    if "code" in frame.columns and "name" in frame.columns:
        return "code", "name"
    if "代码" in frame.columns and "名称" in frame.columns:
        return "代码", "名称"
    raise ValueError("股票列表缺少代码/名称字段")


def _market_symbol(symbol: str) -> str:
    code = symbol.strip()
    if code.startswith(("6", "9")):
        return f"sh{code}"
    if code.startswith(("0", "2", "3")):
        return f"sz{code}"
    if code.startswith(("4", "8")):
        return f"bj{code}"
    return code


def _filter_minute_frame(frame: pd.DataFrame, start_date: str, end_date: str) -> pd.DataFrame:
    time_columns = [
        column
        for column in frame.columns
        if str(column) in {"时间", "日期", "datetime", "date", "time", "day"}
    ]
    if not time_columns:
        return frame
    column = time_columns[0]
    values = frame[column].astype(str)
    return frame[(values >= _format_min_date(start_date)) & (values <= _format_min_date(end_date, end=True))]


def _format_min_date(value: str, end: bool = False) -> str:
    if not value:
        return "1900-01-01 00:00:00"
    suffix = "23:59:59" if end else "00:00:00"
    return f"{value[:4]}-{value[4:6]}-{value[6:8]} {suffix}"


def filter_klines_to_range(klines: list[KLine], start_date: str, end_date: str) -> list[KLine]:
    """Return valid source K-lines within the inclusive user-requested calendar range."""
    start, end = _request_boundaries(start_date, end_date)
    selected: list[tuple[datetime, KLine]] = []
    for kline in klines:
        timestamp = _parse_kline_time(kline.time)
        if timestamp is not None and start <= timestamp <= end:
            selected.append((timestamp, kline))

    selected.sort(key=lambda item: item[0])
    return [
        KLine(
            index=index,
            time=kline.time,
            open=kline.open,
            high=kline.high,
            low=kline.low,
            close=kline.close,
            volume=kline.volume,
            amount=kline.amount,
        )
        for index, (_, kline) in enumerate(selected)
    ]


def _request_boundaries(start_date: str, end_date: str) -> tuple[datetime, datetime]:
    start = _parse_request_date(start_date)
    end = _parse_request_date(end_date)
    if end < start:
        raise ValueError("end_date must not be earlier than start_date")
    return (
        datetime.combine(start, datetime.min.time()),
        datetime.combine(end, datetime.max.time()),
    )


def _parse_request_date(value: str) -> date:
    normalized = str(value).strip().replace("-", "")
    if len(normalized) != 8 or not normalized.isdigit():
        raise ValueError("date must use YYYYMMDD or YYYY-MM-DD")
    return datetime.strptime(normalized, "%Y%m%d").date()


def _parse_kline_time(value: str) -> datetime | None:
    try:
        timestamp = pd.to_datetime(value, errors="coerce")
    except (TypeError, ValueError):
        return None
    if pd.isna(timestamp):
        return None
    return timestamp.to_pydatetime().replace(tzinfo=None)


def _fetch_message(label: str, source_first: str, source_last: str, start_date: str, end_date: str) -> str:
    requested_start, requested_end = _request_boundaries(start_date, end_date)
    first = _parse_kline_time(source_first)
    last = _parse_kline_time(source_last)
    if first is not None and last is not None and (first > requested_start or last < requested_end):
        return (
            f"{label} 数据刷新成功；数据源仅返回 {source_first} 至 {source_last}，"
            "未覆盖完整请求区间，图表仅显示数据源实际提供的K线。"
        )
    return f"{label} 数据刷新成功；已严格按请求区间裁剪图表K线。"


def _sample_klines(days: int = 220) -> list[KLine]:
    start = date.today() - timedelta(days=days)
    rows = []
    price = 10.0
    for i in range(days):
        cycle = (i // 35) % 4
        drift = [0.035, -0.028, 0.045, -0.018][cycle] * (i % 35)
        base = 10 + (i // 35) * 0.42
        wave = math.sin(i / 4.5) * 0.42 + math.sin(i / 13) * 0.55
        open_price = price
        close = max(1.0, base + drift + wave)
        high = max(open_price, close) + 0.18 + abs(math.sin(i / 5)) * 0.12
        low = min(open_price, close) - 0.18 - abs(math.cos(i / 7)) * 0.12
        rows.append(
            {
                "日期": str(start + timedelta(days=i)),
                "开盘": round(open_price, 2),
                "最高": round(high, 2),
                "最低": round(low, 2),
                "收盘": round(close, 2),
                "成交量": 100000 + i * 300,
                "成交额": 1000000 + i * 5000,
            }
        )
        price = close
    return klines_from_frame(pd.DataFrame(rows))
