from __future__ import annotations

import math
from typing import Iterable

import pandas as pd

from .models import Direction, KLine


COLUMN_ALIASES = {
    "日期": "time",
    "时间": "time",
    "交易时间": "time",
    "date": "time",
    "datetime": "time",
    "day": "time",
    "time": "time",
    "开": "open",
    "开盘": "open",
    "开盘价": "open",
    "open": "open",
    "高": "high",
    "最高": "high",
    "最高价": "high",
    "high": "high",
    "低": "low",
    "最低": "low",
    "最低价": "low",
    "low": "low",
    "收": "close",
    "收盘": "close",
    "收盘价": "close",
    "close": "close",
    "量": "volume",
    "成交量": "volume",
    "volume": "volume",
    "额": "amount",
    "成交额": "amount",
    "amount": "amount",
    "turnover": "amount",
}


def klines_from_frame(frame: pd.DataFrame) -> list[KLine]:
    renamed = frame.rename(columns={column: COLUMN_ALIASES.get(str(column).strip(), str(column)) for column in frame.columns})
    required = {"time", "open", "high", "low", "close"}
    missing = required - set(renamed.columns)
    if missing:
        raise ValueError(f"Missing K-line columns: {sorted(missing)}")

    cleaned = renamed.copy()
    for column in ["open", "high", "low", "close", "volume", "amount"]:
        if column in cleaned.columns:
            cleaned[column] = pd.to_numeric(cleaned[column], errors="coerce").fillna(0.0)

    cleaned = cleaned[
        (cleaned["open"] > 0)
        & (cleaned["high"] > 0)
        & (cleaned["low"] > 0)
        & (cleaned["close"] > 0)
        & (cleaned["high"] >= cleaned["low"])
    ].reset_index(drop=True)

    rows: list[KLine] = []
    for index, row in cleaned.iterrows():
        rows.append(
            KLine(
                index=int(index),
                time=str(row["time"]),
                open=_float(row["open"]),
                high=_float(row["high"]),
                low=_float(row["low"]),
                close=_float(row["close"]),
                volume=_float(row.get("volume", 0.0)),
                amount=_float(row.get("amount", 0.0)),
                source_start_time=str(row["time"]),
                source_end_time=str(row["time"]),
                high_time=str(row["time"]),
                low_time=str(row["time"]),
            )
        )
    return rows


def process_inclusion(klines: Iterable[KLine]) -> list[KLine]:
    result: list[KLine] = []
    for kline in klines:
        if not result:
            result.append(kline)
            continue

        last = result[-1]
        if not _contains(last, kline):
            result.append(kline)
            continue

        direction = _infer_direction(result, kline)
        result[-1] = _merge(last, kline, direction)
    return [kline.__class__(index=i, **{k: v for k, v in kline.__dict__.items() if k != "index"}) for i, kline in enumerate(result)]


def _contains(left: KLine, right: KLine) -> bool:
    return (left.high >= right.high and left.low <= right.low) or (
        right.high >= left.high and right.low <= left.low
    )


def _infer_direction(result: list[KLine], current: KLine) -> Direction:
    if len(result) < 2:
        return "up" if current.close >= result[-1].close else "down"
    prev = result[-2]
    last = result[-1]
    if last.high > prev.high and last.low > prev.low:
        return "up"
    if last.high < prev.high and last.low < prev.low:
        return "down"
    return "up" if last.close >= prev.close else "down"


def _merge(left: KLine, right: KLine, direction: Direction) -> KLine:
    if direction == "up":
        high = max(left.high, right.high)
        low = max(left.low, right.low)
    else:
        high = min(left.high, right.high)
        low = min(left.low, right.low)
    if direction == "up":
        high_time = (right.high_time or right.time) if right.high > left.high else (left.high_time or left.time)
        low_time = (right.low_time or right.time) if right.low > left.low else (left.low_time or left.time)
    else:
        high_time = (right.high_time or right.time) if right.high < left.high else (left.high_time or left.time)
        low_time = (right.low_time or right.time) if right.low < left.low else (left.low_time or left.time)

    return KLine(
        index=right.index,
        time=right.time,
        open=left.open,
        high=high,
        low=low,
        close=right.close,
        volume=left.volume + right.volume,
        amount=left.amount + right.amount,
        source_start_time=left.source_start_time or left.time,
        source_end_time=right.source_end_time or right.time,
        high_time=high_time,
        low_time=low_time,
    )


def _float(value: object) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if math.isnan(parsed) else parsed
