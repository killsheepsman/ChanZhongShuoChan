from __future__ import annotations

from typing import Any


PRIORITY_POSITION = {"P0": 35, "P1": 25, "P2": 15, "P3": 10, "P4": 0}
MARKET_COEFFICIENT = 0.6


def build_watch_decision(
    symbol: str,
    daily: dict[str, Any],
    minute30: dict[str, Any],
) -> dict[str, Any]:
    daily_view = _level_view(daily, "日线")
    minute_view = _level_view(minute30, "30分钟")
    risks: list[str] = ["未接入上证指数和板块数据，仓位按中性系数 0.6 折算"]

    if not daily_view["available"] or not minute_view["available"]:
        missing = "、".join(level["level"] for level in (daily_view, minute_view) if not level["available"])
        return {
            "symbol": symbol,
            "action": "NO_TRADE",
            "order_allowed": False,
            "priority": "P4",
            "position_percent": 0,
            "market_coefficient": MARKET_COEFFICIENT,
            "current_price": minute_view["close"] or daily_view["close"],
            "structure": f"{missing}数据不足",
            "latest_signal": None,
            "trigger_conditions": [f"补齐{missing}K线后重新研判"],
            "stop_loss": None,
            "targets": [],
            "risks": risks + ["多级别前置数据不完整，禁止据此下单"],
            "conclusion": f"不可下单：缺少{missing}完整结构数据。",
            "levels": {"daily": daily_view, "minute30": minute_view},
        }

    daily_buy1 = _latest_signal(daily, "buy", 1, confirmed_only=True)
    m30_buy1 = _latest_signal(minute30, "buy", 1, confirmed_only=True)
    m30_buy2 = _latest_signal(minute30, "buy", 2, confirmed_only=True)
    daily_consolidation_buy = any(
        item.get("side") == "buy" and item.get("kind") == "consolidation"
        for item in daily.get("divergences", [])[-3:]
    )

    priority = "P4"
    basis = "未出现满足背驰与多级别确认条件的买点"
    signal = None
    if daily_buy1 and m30_buy2:
        priority, signal, basis = "P0", m30_buy2, "日线一买与30分钟二买共振"
    elif daily_buy1:
        priority, signal, basis = "P1", daily_buy1, "日线一买已确认"
    elif m30_buy1 and daily_consolidation_buy:
        priority, signal, basis = "P2", m30_buy1, "30分钟一买叠加日线盘整背驰"
    elif m30_buy2 and daily_view["trend"] == "空头":
        priority, signal, basis = "P3", m30_buy2, "日线仍为空头，30分钟二买仅作反弹"

    latest_sell = _newest(
        _latest_signal(daily, "sell", confirmed_only=True),
        _latest_signal(minute30, "sell", confirmed_only=True),
    )
    latest_buy = _newest(signal, _latest_signal(minute30, "buy", confirmed_only=True))
    sell_dominates = latest_sell and (not latest_buy or _signal_time(latest_sell) > _signal_time(latest_buy))

    if sell_dominates and (daily_view["trend"] == "空头" or latest_sell.get("type") in {1, 3}):
        action = "SELL"
        order_allowed = True
        position = 0
        signal = latest_sell
        basis = f"最新确认信号为{_signal_label(signal)}，且大级别未支持做多"
        trigger_conditions = ["持仓按计划减仓或离场", "不在卖点后逆势补仓"]
        stop_loss = None
        targets: list[float] = []
        risks.append("卖出判断用于持仓管理，不等同于A股融券做空建议")
        conclusion = f"可执行卖出/减仓：{basis}。"
    elif priority != "P4":
        action = "BUY"
        order_allowed = True
        position = round(PRIORITY_POSITION[priority] * MARKET_COEFFICIENT)
        stop_loss = _buy_stop(minute30, signal)
        targets = _buy_targets(daily_view, minute_view, minute30)
        trigger_conditions = [
            "30分钟底分型保持有效",
            "30分钟MACD绿柱缩短或金叉",
            "价格不跌破止损位后再执行条件单",
        ]
        conclusion = f"允许条件买入：{priority}，{basis}；建议仓位 {position}%。"
    else:
        action = "WAIT" if minute_view["macd_state"] in {"绿柱缩短", "金叉/红柱"} else "NO_TRADE"
        order_allowed = False
        position = 0
        stop_loss = None
        targets = _buy_targets(daily_view, minute_view, minute30)
        trigger_conditions = ["等待日线一买确认", "或等待30分钟一买/二买与日线背驰共振"]
        risks.append("仅有止跌迹象或底分型时属于P4，不构成下单依据")
        conclusion = f"暂不下单：{basis}。"

    return {
        "symbol": symbol,
        "action": action,
        "order_allowed": order_allowed,
        "priority": priority,
        "position_percent": position,
        "market_coefficient": MARKET_COEFFICIENT,
        "current_price": minute_view["close"],
        "structure": f"日线{daily_view['trend']}；30分钟{minute_view['trend']}，{minute_view['segment_state']}",
        "latest_signal": _signal_summary(signal),
        "trigger_conditions": trigger_conditions,
        "stop_loss": stop_loss,
        "targets": targets,
        "risks": risks,
        "conclusion": conclusion,
        "levels": {"daily": daily_view, "minute30": minute_view},
    }


def _level_view(analysis: dict[str, Any], level: str) -> dict[str, Any]:
    klines = analysis.get("raw_klines") or analysis.get("klines") or []
    closes = [float(item["close"]) for item in klines]
    volumes = [float(item.get("volume", 0) or 0) for item in klines]
    mas = {f"ma{window}": _average(closes[-window:]) for window in (5, 10, 20, 30)}
    close = closes[-1] if closes else None
    trend = "数据不足"
    if close is not None and mas["ma20"] is not None:
        if close > mas["ma5"] > mas["ma10"] > mas["ma20"]:
            trend = "多头"
        elif close < mas["ma5"] < mas["ma10"] < mas["ma20"]:
            trend = "空头"
        else:
            trend = "震荡"

    macd = analysis.get("macd") or []
    hist = float(macd[-1].get("hist", 0)) if macd else 0.0
    previous_hist = float(macd[-2].get("hist", 0)) if len(macd) > 1 else hist
    if hist >= 0:
        macd_state = "金叉/红柱"
    elif hist > previous_hist:
        macd_state = "绿柱缩短"
    else:
        macd_state = "绿柱放大"

    segments = analysis.get("segments") or []
    latest_segment = segments[-1] if segments else None
    segment_state = "无有效线段"
    if latest_segment:
        direction = "上涨段" if latest_segment.get("direction") == "up" else "下跌段"
        state = "进行中" if latest_segment.get("status") == "IS_RUNNING" else "已确认"
        segment_state = f"{direction}{state}"

    volume_ratio = None
    if volumes and len(volumes) >= 6:
        baseline = _average(volumes[-6:-1])
        volume_ratio = round(volumes[-1] / baseline, 2) if baseline else None

    return {
        "level": level,
        "available": len(klines) >= 30,
        "last_time": klines[-1]["time"] if klines else None,
        "close": _round(close),
        "trend": trend,
        "segment_state": segment_state,
        "macd_state": macd_state,
        "volume_ratio": volume_ratio,
        **{key: _round(value) for key, value in mas.items()},
    }


def _latest_signal(
    analysis: dict[str, Any], side: str, signal_type: int | None = None, confirmed_only: bool = False
) -> dict[str, Any] | None:
    candidates = [
        item for item in analysis.get("signals", [])
        if item.get("side") == side
        and (signal_type is None or item.get("type") == signal_type)
        and item.get("status") not in {"expired", "invalidated"}
        and (not confirmed_only or item.get("status") == "confirmed")
    ]
    return max(candidates, key=_signal_index, default=None)


def _newest(*signals: dict[str, Any] | None) -> dict[str, Any] | None:
    return max((item for item in signals if item), key=_signal_time, default=None)


def _signal_index(signal: dict[str, Any]) -> int:
    return int(signal.get("index", -1))


def _signal_time(signal: dict[str, Any]) -> str:
    return str(signal.get("time", ""))


def _signal_summary(signal: dict[str, Any] | None) -> dict[str, Any] | None:
    if not signal:
        return None
    return {
        "label": _signal_label(signal),
        "time": signal.get("time"),
        "price": signal.get("price"),
        "status": signal.get("status"),
        "reason": signal.get("reason"),
    }


def _signal_label(signal: dict[str, Any]) -> str:
    return f"{'买' if signal.get('side') == 'buy' else '卖'}{signal.get('type')}"


def _buy_stop(analysis: dict[str, Any], signal: dict[str, Any] | None) -> float | None:
    klines = analysis.get("raw_klines") or analysis.get("klines") or []
    recent_low = min((float(item["low"]) for item in klines[-10:]), default=None)
    signal_price = float(signal["price"]) if signal and signal.get("price") is not None else None
    anchors = [value for value in (recent_low, signal_price) if value is not None]
    return _round(min(anchors) * 0.99) if anchors else None


def _buy_targets(daily_view: dict[str, Any], minute_view: dict[str, Any], analysis: dict[str, Any]) -> list[float]:
    close = minute_view.get("close")
    candidates = [minute_view.get("ma5"), minute_view.get("ma10"), daily_view.get("ma5")]
    centers = analysis.get("centers") or []
    if centers:
        candidates.append(centers[-1].get("zg"))
    values = sorted({_round(float(value)) for value in candidates if value is not None and (close is None or value > close)})
    return values[:2]


def _average(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _round(value: float | None) -> float | None:
    return round(value, 2) if value is not None else None
