from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable

import pandas as pd

from app.chanlun.kline import klines_from_frame
from app.chanlun.models import KLine


@dataclass(frozen=True)
class KLineFetchResult:
    klines: list[KLine]
    source: str
    ok: bool
    message: str
    source_first_kline_time: str | None = None
    source_last_kline_time: str | None = None


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

    errors: list[str] = []
    for source, label, loader in attempts:
        try:
            source_klines = klines_from_frame(loader())
            if not source_klines:
                errors.append(f"{label}: 返回空数据")
                continue
            klines = filter_klines_to_range(source_klines, start_date, end_date)
            if not klines:
                errors.append(f"{label}: 返回数据与请求区间没有重叠")
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
            )
        except Exception as exc:
            errors.append(f"{label}: {exc}")

    sample_message = "；".join(errors) if errors else "所有数据源均未返回数据"
    sample_klines = filter_klines_to_range(_sample_klines(), start_date, end_date)
    return KLineFetchResult(sample_klines, "sample", False, f"真实数据源全部失败，已使用示例数据：{sample_message}")


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
