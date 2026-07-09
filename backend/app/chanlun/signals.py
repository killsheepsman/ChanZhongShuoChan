from __future__ import annotations

from dataclasses import replace

from .models import BuySellSignal, Center, Divergence, KLine, Segment, Stroke


def detect_buy_sell_points(
    segments: list[Segment],
    centers: list[Center],
    divergences: list[Divergence],
    klines: list[KLine] | None = None,
    strokes: list[Stroke] | None = None,
) -> list[BuySellSignal]:
    stroke_items = strokes or []
    first_points = [_classify_status(signal, segments) for signal in _detect_first_points(segments, centers, divergences)]
    all_first = _dedupe_signals(sorted(first_points, key=lambda item: item.index))
    second_points = _detect_second_points(stroke_items, all_first)
    third_points = _detect_third_points(stroke_items, centers, segments, divergences, all_first)
    pending_first_points = _detect_pending_first_points(stroke_items, centers)
    pending_points = _detect_pending_breakout_points(stroke_items, centers, segments, klines or [])
    return _dedupe_signals(sorted([*all_first, *second_points, *third_points, *pending_first_points, *pending_points], key=lambda item: item.index))


def _detect_first_points(segments: list[Segment], centers: list[Center], divergences: list[Divergence]) -> list[BuySellSignal]:
    signals: list[BuySellSignal] = []
    by_id = {segment.id: segment for segment in segments}
    for divergence in divergences:
        leave = by_id.get(divergence.segment_id)
        if not leave:
            continue
        center = _last_center_before_index(leave.end_index, centers, segments)
        if not center:
            continue
        formation_end = _center_formation_end_index(center, segments)
        if formation_end is None or leave.start_index <= formation_end:
            continue
        trend_count = _strict_trend_count(center, centers, divergence.side)
        if divergence.kind != "trend" or trend_count < 2:
            continue
        if divergence.side == "buy" and leave.direction == "down" and leave.low < center.zd:
            base = 0.58
            confidence = _confidence(base, divergence.strength, max(1, trend_count), _leave_ratio(leave.low, center, "buy"))
            signals.append(_segment_signal("buy", 1, leave, leave.low, confidence, "下跌趋势离开最后中枢且底背驰，候选一类买点", center.id))
        elif divergence.side == "sell" and leave.direction == "up" and leave.high > center.zg:
            base = 0.58
            confidence = _confidence(base, divergence.strength, max(1, trend_count), _leave_ratio(leave.high, center, "sell"))
            signals.append(_segment_signal("sell", 1, leave, leave.high, confidence, "上涨趋势离开最后中枢且顶背驰，候选一类卖点", center.id))
    return signals


def _detect_second_points(strokes: list[Stroke], first_points: list[BuySellSignal]) -> list[BuySellSignal]:
    signals: list[BuySellSignal] = []
    for first in first_points:
        if first.type != 1 or first.status != "confirmed":
            continue
        after = [stroke for stroke in strokes if stroke.start_index >= first.index]
        if len(after) < 2:
            continue
        tolerance = max(abs(first.price) * 0.003, 0.01)
        if first.side == "buy":
            pair = _first_reaction_pullback(after, "up", "down")
            if not pair:
                continue
            reaction, pullback = pair
            if pullback.low >= first.price - tolerance:
                confidence = _second_confidence(first, reaction, pullback, "buy")
                signal = _stroke_signal("buy", 2, pullback, pullback.low, confidence, "一买后反弹回踩不破一买低点，候选二类买点", first.center_id)
                signals.append(_classify_signal_with_strokes(signal, strokes))
        elif first.side == "sell":
            pair = _first_reaction_pullback(after, "down", "up")
            if not pair:
                continue
            reaction, pullback = pair
            if pullback.high <= first.price + tolerance:
                confidence = _second_confidence(first, reaction, pullback, "sell")
                signal = _stroke_signal("sell", 2, pullback, pullback.high, confidence, "一卖后下跌反弹不破一卖高点，候选二类卖点", first.center_id)
                signals.append(_classify_signal_with_strokes(signal, strokes))
    return signals


def _detect_pending_first_points(strokes: list[Stroke], centers: list[Center]) -> list[BuySellSignal]:
    if not strokes or not centers:
        return []
    latest = strokes[-1]
    center = _last_center_before_index(latest.end_index, centers, [])
    if not center:
        return []
    if latest.start_index <= center.end_index:
        return []
    previous_same = _previous_same_direction_before(strokes[:-1], latest.direction, center.start_index)
    if latest.direction == "down" and latest.low < center.zd and _strict_trend_count(center, centers, "buy") >= 2:
        confidence = 0.52
        reason = "未完成下跌离开中枢下沿，候选一类买点"
        if previous_same and _stroke_power(latest) < _stroke_power(previous_same):
            confidence = 0.66
            reason = "未完成下跌离开中枢且力度弱于前下跌段，候选一类买点"
        return [_stroke_signal("buy", 1, latest, latest.end_price, confidence, reason, center.id)]
    if latest.direction == "up" and latest.high > center.zg and _strict_trend_count(center, centers, "sell") >= 2:
        confidence = 0.52
        reason = "未完成上涨离开中枢上沿，候选一类卖点"
        if previous_same and _stroke_power(latest) < _stroke_power(previous_same):
            confidence = 0.66
            reason = "未完成上涨离开中枢且力度弱于前上涨段，候选一类卖点"
        return [_stroke_signal("sell", 1, latest, latest.end_price, confidence, reason, center.id)]
    return []


def _detect_third_points(
    strokes: list[Stroke],
    centers: list[Center],
    segments: list[Segment],
    divergences: list[Divergence],
    first_points: list[BuySellSignal],
) -> list[BuySellSignal]:
    signals: list[BuySellSignal] = []
    for center in centers:
        center_direction = _center_direction(center, centers)
        formation_end = _center_formation_end_index(center, segments)
        if formation_end is None:
            continue
        after = [stroke for stroke in strokes if stroke.start_index > formation_end]
        found_buy = False
        found_sell = False
        for leave, test in zip(after, after[1:]):
            if center_direction == "up" and not found_buy and leave.direction == "up" and leave.high > center.zg and test.direction == "down" and test.low > center.zg:
                confidence = 0.66 + min(0.1, _leave_ratio(leave.high, center, "sell") * 0.04)
                signal = _stroke_signal("buy", 3, test, test.low, round(confidence, 3), "上涨中枢向上离开后回抽不进中枢，候选三类买点", center.id)
                signals.append(_classify_signal_with_strokes(signal, strokes))
                found_buy = True
            if center_direction == "down" and not found_sell and leave.direction == "down" and leave.low < center.zd and test.direction == "up" and test.high < center.zd:
                confidence = 0.66 + min(0.1, _leave_ratio(leave.low, center, "buy") * 0.04)
                signal = _stroke_signal("sell", 3, test, test.high, round(confidence, 3), "下跌中枢向下离开后反抽不进中枢，候选三类卖点", center.id)
                signals.append(_classify_signal_with_strokes(signal, strokes))
                found_sell = True
            if found_buy and found_sell:
                break
    return signals


def _detect_pending_breakout_points(strokes: list[Stroke], centers: list[Center], segments: list[Segment], klines: list[KLine]) -> list[BuySellSignal]:
    if not centers or not klines:
        return []
    center = centers[-1]
    latest = klines[-1]
    formation_end = _center_formation_end_index(center, segments)
    if formation_end is None or latest.index <= formation_end:
        return []
    last_stroke = strokes[-1] if strokes else None
    center_direction = _center_direction(center, centers)
    if center_direction == "up" and latest.close > center.zg and (not last_stroke or last_stroke.direction == "up"):
        return [_kline_signal("buy", 3, latest, latest.low, 0.52, "价格向上离开上涨中枢，等待回抽不进中枢确认三买", center.id)]
    if center_direction == "down" and latest.close < center.zd and (not last_stroke or last_stroke.direction == "down"):
        return [_kline_signal("sell", 3, latest, latest.high, 0.52, "价格向下离开下跌中枢，等待反抽不进中枢确认三卖", center.id)]
    return []


def _classify_status(signal: BuySellSignal, segments: list[Segment]) -> BuySellSignal:
    future = [segment for segment in segments if segment.start_index > signal.index]
    if not future:
        return replace(signal, status="candidate")
    first = future[0]
    tolerance = max(signal.price * 0.002, 0.01)
    if signal.side == "buy":
        if first.low < signal.price - tolerance:
            return replace(signal, status="invalidated", confidence=max(0.25, signal.confidence - 0.25))
        if first.direction == "up" or first.high > signal.price + tolerance:
            return replace(signal, status="confirmed", confidence=min(0.95, signal.confidence + 0.08))
    else:
        if first.high > signal.price + tolerance:
            return replace(signal, status="invalidated", confidence=max(0.25, signal.confidence - 0.25))
        if first.direction == "down" or first.low < signal.price - tolerance:
            return replace(signal, status="confirmed", confidence=min(0.95, signal.confidence + 0.08))
    return replace(signal, status="candidate")


def _classify_signal_with_strokes(signal: BuySellSignal, strokes: list[Stroke]) -> BuySellSignal:
    future = [stroke for stroke in strokes if stroke.start_index > signal.index]
    if not future:
        return replace(signal, status="candidate")
    first = future[0]
    tolerance = max(signal.price * 0.002, 0.01)
    if signal.side == "buy":
        if first.low < signal.price - tolerance:
            return replace(signal, status="invalidated", confidence=max(0.35, signal.confidence - 0.18))
        if first.direction == "up" or first.high > signal.price + tolerance:
            return replace(signal, status="confirmed", confidence=min(0.92, signal.confidence + 0.08))
    else:
        if first.high > signal.price + tolerance:
            return replace(signal, status="invalidated", confidence=max(0.35, signal.confidence - 0.18))
        if first.direction == "down" or first.low < signal.price - tolerance:
            return replace(signal, status="confirmed", confidence=min(0.92, signal.confidence + 0.08))
    return replace(signal, status="candidate")


def _last_center_before_index(index: int, centers: list[Center], segments: list[Segment]) -> Center | None:
    previous = []
    for center in centers:
        formation_end = _center_formation_end_index(center, segments)
        if formation_end is not None and formation_end < index:
            previous.append(center)
    return previous[-1] if previous else None


def _center_formation_end_index(center: Center, segments: list[Segment]) -> int | None:
    if len(center.segment_ids) >= 3:
        formation_id = center.segment_ids[2]
    elif center.segment_ids:
        formation_id = center.segment_ids[-1]
    else:
        return None
    for segment in segments:
        if segment.id == formation_id:
            return segment.end_index
    return center.end_index


def _strict_trend_count(center: Center, centers: list[Center], side: str) -> int:
    previous = [item for item in centers if item.end_index <= center.end_index]
    chain: list[Center] = []
    for item in previous:
        if not chain:
            chain = [item]
            continue
        last = chain[-1]
        if side == "buy" and item.zg < last.zd:
            chain.append(item)
        elif side == "sell" and item.zd > last.zg:
            chain.append(item)
        else:
            chain = [item]
    return len(chain)


def _center_direction(center: Center, centers: list[Center]) -> str | None:
    previous = [item for item in centers if item.end_index < center.start_index]
    if not previous:
        return None
    last = previous[-1]
    if center.zd > last.zg:
        return "up"
    if center.zg < last.zd:
        return "down"
    return None


def _first_reaction_pullback(after: list[Stroke], reaction_direction: str, pullback_direction: str) -> tuple[Stroke, Stroke] | None:
    reaction: Stroke | None = None
    for stroke in after:
        if reaction is None:
            if stroke.direction == reaction_direction:
                reaction = stroke
            continue
        if stroke.direction == pullback_direction:
            return reaction, stroke
        if stroke.direction == reaction_direction:
            reaction = _stronger_reaction(reaction, stroke, reaction_direction)
    return None


def _stronger_reaction(left: Stroke, right: Stroke, direction: str) -> Stroke:
    if direction == "up":
        return right if right.high > left.high else left
    return right if right.low < left.low else left


def _previous_same_direction_before(strokes: list[Stroke], direction: str, before_index: int) -> Stroke | None:
    for stroke in reversed(strokes):
        if stroke.end_index >= before_index:
            continue
        if stroke.direction == direction:
            return stroke
    return None


def _stroke_power(stroke: Stroke) -> float:
    return max(stroke.high - stroke.low, 0.01)


def _leave_ratio(value: float, center: Center, side: str) -> float:
    height = max(center.zg - center.zd, 0.01)
    if side == "buy":
        return max(0.0, (center.zd - value) / height)
    return max(0.0, (value - center.zg) / height)


def _confidence(base: float, divergence_strength: float, trend_count: int, leave_ratio: float) -> float:
    value = base + min(0.18, divergence_strength * 0.22) + min(0.08, (trend_count - 2) * 0.03) + min(0.1, leave_ratio * 0.04)
    return round(max(0.35, min(0.9, value)), 3)


def _second_confidence(first: BuySellSignal, reaction: Stroke, pullback: Stroke, side: str) -> float:
    tolerance = max(first.price * 0.01, 0.01)
    if side == "buy":
        near_score = max(0.0, 1 - (pullback.low - first.price) / tolerance)
        reaction_score = max(0.0, (reaction.high - first.price) / max(first.price, 0.01))
    else:
        near_score = max(0.0, 1 - (first.price - pullback.high) / tolerance)
        reaction_score = max(0.0, (first.price - reaction.low) / max(first.price, 0.01))
    value = 0.56 + min(0.12, near_score * 0.08) + min(0.08, reaction_score * 3)
    return round(min(0.82, value), 3)


def _dedupe_signals(signals: list[BuySellSignal]) -> list[BuySellSignal]:
    kept: list[BuySellSignal] = []
    min_gap = 3
    for signal in signals:
        opposite = _find_same_price_opposite_signal(kept, signal)
        if opposite:
            if _priority(signal) > _priority(opposite) or (
                _priority(signal) == _priority(opposite) and signal.confidence > opposite.confidence
            ):
                kept[kept.index(opposite)] = signal
            continue
        repeated_third = _find_repeated_third_signal(kept, signal)
        if repeated_third:
            if _status_rank(signal.status) > _status_rank(repeated_third.status):
                kept[kept.index(repeated_third)] = signal
            continue
        conflict = next(
            (
                item
                for item in kept
                if item.side == signal.side
                and item.type == signal.type
                and item.center_id == signal.center_id
                and abs(item.index - signal.index) <= min_gap
            ),
            None,
        )
        if not conflict:
            kept.append(signal)
            continue
        if _status_rank(signal.status) > _status_rank(conflict.status) or (
            _status_rank(signal.status) == _status_rank(conflict.status) and signal.confidence > conflict.confidence
        ):
            kept[kept.index(conflict)] = signal
    return kept


def _priority(signal: BuySellSignal) -> int:
    return {3: 3, 2: 2, 1: 1}.get(signal.type, 0)


def _find_repeated_third_signal(kept: list[BuySellSignal], signal: BuySellSignal) -> BuySellSignal | None:
    if signal.type != 3:
        return None
    for item in reversed(kept):
        if item.side != signal.side:
            return None
        if item.type == 3 and item.side == signal.side and item.center_id == signal.center_id:
            return item
    return None


def _find_same_price_opposite_signal(kept: list[BuySellSignal], signal: BuySellSignal) -> BuySellSignal | None:
    tolerance = max(abs(signal.price) * 0.002, 0.01)
    for item in reversed(kept):
        if item.side == signal.side:
            continue
        if abs(item.index - signal.index) > 1:
            continue
        if abs(item.price - signal.price) <= tolerance:
            return item
    return None


def _status_rank(status: str) -> int:
    return {"invalidated": 0, "candidate": 1, "confirmed": 2}.get(status, 0)


def _segment_signal(side: str, signal_type: int, segment: Segment, price: float, confidence: float, reason: str, center_id: int | None) -> BuySellSignal:
    return BuySellSignal(
        id=f"{side}-{signal_type}-seg-{segment.id}",
        side=side,  # type: ignore[arg-type]
        type=signal_type,
        index=segment.end_index,
        time=segment.end_time,
        price=price,
        status="candidate",
        confidence=confidence,
        reason=reason,
        center_id=center_id,
        segment_id=segment.id,
    )


def _stroke_signal(side: str, signal_type: int, stroke: Stroke, price: float, confidence: float, reason: str, center_id: int | None) -> BuySellSignal:
    return BuySellSignal(
        id=f"{side}-{signal_type}-stroke-{stroke.end_index}",
        side=side,  # type: ignore[arg-type]
        type=signal_type,
        index=stroke.end_index,
        time=stroke.end_time,
        price=price,
        status="candidate",
        confidence=confidence,
        reason=reason,
        center_id=center_id,
        segment_id=None,
    )


def _kline_signal(side: str, signal_type: int, kline: KLine, price: float, confidence: float, reason: str, center_id: int | None) -> BuySellSignal:
    return BuySellSignal(
        id=f"{side}-{signal_type}-pending-{kline.index}",
        side=side,  # type: ignore[arg-type]
        type=signal_type,
        index=kline.index,
        time=kline.time,
        price=price,
        status="candidate",
        confidence=confidence,
        reason=reason,
        center_id=center_id,
        segment_id=None,
    )
