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
    """Identify Chan buy/sell points from completed structure only.

    A confirmed signal always needs a completed structural sequence.  The only
    provisional records emitted here belong to the last running stroke/segment,
    so they can be rendered as dashed observation marks instead of facts.
    """
    del klines  # Kept for the public API used by the service layer.
    stroke_items = strokes or []
    first_points = _first_points(segments, centers, divergences)
    first_points = [_classify_first_point(signal, segments) for signal in first_points]
    first_points = _dedupe_signals(first_points)
    second_points = _second_points(stroke_items, first_points)
    third_points = _third_points(segments, centers, stroke_items)
    pending_points = _pending_points(stroke_items, centers)
    return _dedupe_signals(sorted([*first_points, *second_points, *third_points, *pending_points], key=lambda item: item.index))


def _first_points(
    segments: list[Segment], centers: list[Center], divergences: list[Divergence]
) -> list[BuySellSignal]:
    by_id = {segment.id: segment for segment in segments}
    signals: list[BuySellSignal] = []
    for divergence in divergences:
        leave = by_id.get(divergence.segment_id)
        if leave is None or leave.status != "CONFIRMED" or divergence.kind != "trend":
            continue
        center = _latest_center_before_segment(leave, centers, segments)
        if center is None:
            continue
        if divergence.side == "buy" and leave.direction == "down" and leave.low < center.zd:
            signals.append(_segment_signal("buy", 1, leave, leave.low, _first_confidence(divergence), "trend bottom divergence after leaving center", center.id))
        elif divergence.side == "sell" and leave.direction == "up" and leave.high > center.zg:
            signals.append(_segment_signal("sell", 1, leave, leave.high, _first_confidence(divergence), "trend top divergence after leaving center", center.id))
    return signals


def _second_points(strokes: list[Stroke], first_points: list[BuySellSignal]) -> list[BuySellSignal]:
    signals: list[BuySellSignal] = []
    for first in first_points:
        if first.type != 1 or first.status != "confirmed":
            continue
        after = [stroke for stroke in strokes if stroke.start_index >= first.index]
        reaction, retest = _reaction_and_retest(after, "up", "down") if first.side == "buy" else _reaction_and_retest(after, "down", "up")
        if reaction is None or retest is None:
            continue
        tolerance = max(abs(first.price) * 0.003, 0.01)
        if first.side == "buy" and retest.low >= first.price - tolerance:
            signal = _stroke_signal("buy", 2, retest, retest.low, _second_confidence(first, reaction, retest), "retest after buy-1 does not break its low", first.center_id)
            signals.append(_classify_follow_through(signal, strokes))
        elif first.side == "sell" and retest.high <= first.price + tolerance:
            signal = _stroke_signal("sell", 2, retest, retest.high, _second_confidence(first, reaction, retest), "retest after sell-1 does not break its high", first.center_id)
            signals.append(_classify_follow_through(signal, strokes))
    return signals


def _third_points(segments: list[Segment], centers: list[Center], strokes: list[Stroke]) -> list[BuySellSignal]:
    signals: list[BuySellSignal] = []
    for center in centers:
        if len(center.segment_ids) < 3:
            continue
        last_id = center.segment_ids[-1]
        after = [segment for segment in segments if segment.id > last_id]
        for leave, retest in zip(after, after[1:]):
            if leave.direction == "up" and leave.high > center.zg and retest.direction == "down":
                if retest.low > center.zg:
                    signal = _segment_signal("buy", 3, retest, retest.low, 0.72, "upward leave and retest stays above ZG", center.id)
                    signals.append(_classify_third_point(signal, strokes, center))
                    break
                if retest.low <= center.zg:
                    break
            if leave.direction == "down" and leave.low < center.zd and retest.direction == "up":
                if retest.high < center.zd:
                    signal = _segment_signal("sell", 3, retest, retest.high, 0.72, "downward leave and retest stays below ZD", center.id)
                    signals.append(_classify_third_point(signal, strokes, center))
                    break
                if retest.high >= center.zd:
                    break
    return signals


def _pending_points(strokes: list[Stroke], centers: list[Center]) -> list[BuySellSignal]:
    """Return only the current, unconfirmed first-point observation."""
    if not strokes or not centers:
        return []
    current = strokes[-1]
    center = _latest_center_before_index(current.start_index, centers)
    if center is None or current.start_index <= center.end_index:
        return []
    previous = _previous_same_direction(strokes[:-1], current.direction, center.start_index)
    if current.direction == "down" and current.low < center.zd and previous and _stroke_power(current) < _stroke_power(previous):
        return [_stroke_signal("buy", 1, current, current.end_price, 0.56, "running downward leave is weaker than prior down stroke", center.id)]
    if current.direction == "up" and current.high > center.zg and previous and _stroke_power(current) < _stroke_power(previous):
        return [_stroke_signal("sell", 1, current, current.end_price, 0.56, "running upward leave is weaker than prior up stroke", center.id)]
    return []


def _latest_center_before_segment(segment: Segment, centers: list[Center], segments: list[Segment]) -> Center | None:
    candidates = []
    for center in centers:
        formation_end = _center_formation_end(center, segments)
        if formation_end is not None and formation_end < segment.start_index:
            candidates.append(center)
    return candidates[-1] if candidates else None


def _latest_center_before_index(index: int, centers: list[Center]) -> Center | None:
    candidates = [center for center in centers if center.end_index < index]
    return candidates[-1] if candidates else None


def _center_formation_end(center: Center, segments: list[Segment]) -> int | None:
    if len(center.segment_ids) < 3:
        return None
    formation_id = center.segment_ids[2]
    for segment in segments:
        if segment.id == formation_id:
            return segment.end_index
    return None


def _reaction_and_retest(strokes: list[Stroke], reaction_direction: str, retest_direction: str) -> tuple[Stroke | None, Stroke | None]:
    reaction: Stroke | None = None
    for stroke in strokes:
        if reaction is None:
            if stroke.direction == reaction_direction:
                reaction = stroke
            continue
        if stroke.direction == retest_direction:
            return reaction, stroke
        if stroke.direction == reaction_direction:
            reaction = _stronger(reaction, stroke, reaction_direction)
    return None, None


def _stronger(left: Stroke, right: Stroke, direction: str) -> Stroke:
    if direction == "up":
        return right if right.high > left.high else left
    return right if right.low < left.low else left


def _previous_same_direction(strokes: list[Stroke], direction: str, before_index: int) -> Stroke | None:
    for stroke in reversed(strokes):
        if stroke.end_index < before_index and stroke.direction == direction:
            return stroke
    return None


def _classify_first_point(signal: BuySellSignal, segments: list[Segment]) -> BuySellSignal:
    future = [segment for segment in segments if segment.start_index >= signal.index]
    if not future:
        return replace(signal, status="candidate")
    next_segment = future[0]
    tolerance = max(abs(signal.price) * 0.003, 0.01)
    if signal.side == "buy":
        if next_segment.low < signal.price - tolerance:
            return replace(signal, status="invalidated", confidence=max(0.25, signal.confidence - 0.25))
        if next_segment.direction == "up":
            return replace(signal, status="confirmed", confidence=min(0.95, signal.confidence + 0.08))
    else:
        if next_segment.high > signal.price + tolerance:
            return replace(signal, status="invalidated", confidence=max(0.25, signal.confidence - 0.25))
        if next_segment.direction == "down":
            return replace(signal, status="confirmed", confidence=min(0.95, signal.confidence + 0.08))
    return replace(signal, status="candidate")

def _classify_third_point(signal: BuySellSignal, strokes: list[Stroke], center: Center) -> BuySellSignal:
    future = [stroke for stroke in strokes if stroke.start_index >= signal.index]
    if not future:
        return replace(signal, status="candidate")

    confirmed = False
    for stroke in future:
        if signal.side == "buy":
            if stroke.low <= center.zg:
                return replace(signal, status="invalidated", confidence=max(0.3, signal.confidence - 0.25))
            if stroke.direction == "up":
                confirmed = True
        else:
            if stroke.high >= center.zd:
                return replace(signal, status="invalidated", confidence=max(0.3, signal.confidence - 0.25))
            if stroke.direction == "down":
                confirmed = True
    if confirmed:
        return replace(signal, status="confirmed", confidence=min(0.94, signal.confidence + 0.08))
    return replace(signal, status="candidate")

def _classify_follow_through(signal: BuySellSignal, strokes: list[Stroke]) -> BuySellSignal:
    future = [stroke for stroke in strokes if stroke.start_index >= signal.index]
    if not future:
        return replace(signal, status="candidate")
    next_stroke = future[0]
    tolerance = max(abs(signal.price) * 0.002, 0.01)
    if signal.side == "buy":
        if next_stroke.low < signal.price - tolerance:
            return replace(signal, status="invalidated", confidence=max(0.3, signal.confidence - 0.18))
        if next_stroke.direction == "up":
            return replace(signal, status="confirmed", confidence=min(0.92, signal.confidence + 0.08))
    else:
        if next_stroke.high > signal.price + tolerance:
            return replace(signal, status="invalidated", confidence=max(0.3, signal.confidence - 0.18))
        if next_stroke.direction == "down":
            return replace(signal, status="confirmed", confidence=min(0.92, signal.confidence + 0.08))
    return replace(signal, status="candidate")


def _classify_segment_follow_through(signal: BuySellSignal, segments: list[Segment]) -> BuySellSignal:
    future = [segment for segment in segments if segment.start_index >= signal.index]
    if not future:
        return replace(signal, status="candidate")
    next_segment = future[0]
    tolerance = max(abs(signal.price) * 0.002, 0.01)
    if signal.side == "buy":
        if next_segment.low < signal.price - tolerance:
            return replace(signal, status="invalidated", confidence=max(0.35, signal.confidence - 0.22))
        if next_segment.direction == "up":
            return replace(signal, status="confirmed", confidence=min(0.94, signal.confidence + 0.08))
    else:
        if next_segment.high > signal.price + tolerance:
            return replace(signal, status="invalidated", confidence=max(0.35, signal.confidence - 0.22))
        if next_segment.direction == "down":
            return replace(signal, status="confirmed", confidence=min(0.94, signal.confidence + 0.08))
    return replace(signal, status="candidate")


def _first_confidence(divergence: Divergence) -> float:
    return round(min(0.85, 0.58 + divergence.strength * 0.22), 3)


def _second_confidence(first: BuySellSignal, reaction: Stroke, retest: Stroke) -> float:
    base = 0.62
    reaction_size = max(reaction.high - reaction.low, 0.01)
    retest_size = max(retest.high - retest.low, 0.01)
    return round(min(0.84, base + min(0.12, reaction_size / retest_size * 0.04)), 3)


def _stroke_power(stroke: Stroke) -> float:
    return max(stroke.high - stroke.low, 0.0)


def _dedupe_signals(signals: list[BuySellSignal]) -> list[BuySellSignal]:
    kept: list[BuySellSignal] = []
    for signal in sorted(signals, key=lambda item: (item.index, item.type)):
        conflict = next((item for item in kept if _conflicts(item, signal)), None)
        if conflict is None:
            kept.append(signal)
            continue
        if _signal_rank(signal) > _signal_rank(conflict):
            kept[kept.index(conflict)] = signal
    return kept


def _conflicts(left: BuySellSignal, right: BuySellSignal) -> bool:
    if left.center_id != right.center_id:
        return False
    if left.side != right.side and abs(left.index - right.index) <= 3:
        return True
    return left.side == right.side and left.type == right.type and abs(left.index - right.index) <= 3


def _signal_rank(signal: BuySellSignal) -> tuple[int, float, int]:
    status = {"invalidated": 0, "candidate": 1, "confirmed": 2}.get(signal.status, 0)
    return status, signal.confidence, signal.type


def _segment_signal(side: str, signal_type: int, segment: Segment, price: float, confidence: float, reason: str, center_id: int | None) -> BuySellSignal:
    return BuySellSignal(
        id=f"{side}-{signal_type}-seg-{segment.id}", side=side, type=signal_type,
        index=segment.end_index, time=segment.end_time, price=price, status="candidate",
        confidence=confidence, reason=reason, center_id=center_id, segment_id=segment.id,
    )  # type: ignore[arg-type]


def _stroke_signal(side: str, signal_type: int, stroke: Stroke, price: float, confidence: float, reason: str, center_id: int | None) -> BuySellSignal:
    return BuySellSignal(
        id=f"{side}-{signal_type}-stroke-{stroke.end_index}", side=side, type=signal_type,
        index=stroke.end_index, time=stroke.end_time, price=price, status="candidate",
        confidence=confidence, reason=reason, center_id=center_id, segment_id=None,
    )  # type: ignore[arg-type]
