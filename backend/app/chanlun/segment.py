from __future__ import annotations

from dataclasses import replace

from .models import Direction, Segment, Stroke


REVERSE_GAP_PCT = 0.035


def detect_segments(strokes: list[Stroke]) -> list[Segment]:
    if len(strokes) < 3:
        return []

    initial_start = _find_initial_segment_start(strokes)
    if initial_start is None:
        return []

    segments: list[Segment] = []
    running = _new_running_from_strokes(0, strokes, initial_start, initial_start + 2)
    reverse_features: list[tuple[int, Stroke]] = []

    for stroke_index, stroke in enumerate(strokes[initial_start + 3 :], start=initial_start + 3):
        if stroke.direction == running.direction:
            extended = _extends_running_endpoint(running, stroke)
            running = _extend_running_segment(running, stroke, stroke_index)
            if extended:
                reverse_features = []
            continue

        if _gap_breaks_running_segment(running, stroke):
            confirmed, running = _cut_by_gap(running, stroke, stroke_index)
            segments.append(confirmed)
            reverse_features = []
            continue

        reverse_features.append((stroke_index, stroke))
        if not _reverse_break_confirmed(running, reverse_features):
            running = _update_running_shadow(running, stroke, stroke_index)
            continue

        confirmed = _confirm_running_at_extreme(running)
        segments.append(confirmed)
        running = _new_running_from_reverse_features(len(segments), confirmed, reverse_features)
        reverse_features = []

    segments.append(replace(running, id=len(segments), status="IS_RUNNING"))
    return _renumber(segments)


def _find_initial_segment_start(strokes: list[Stroke]) -> int | None:
    for index in range(0, len(strokes) - 2):
        if _has_common_overlap(strokes[index : index + 3]):
            return index
    return None


def _new_running_from_strokes(segment_id: int, strokes: list[Stroke], start: int, end: int) -> Segment:
    group = strokes[start : end + 1]
    first = group[0]
    direction = first.direction
    end_index, end_time, end_price = _extreme_point(group, direction)
    return Segment(
        id=segment_id,
        start_index=first.start_index,
        end_index=end_index,
        start_time=first.start_time,
        end_time=end_time,
        start_price=first.start_price,
        end_price=end_price,
        direction=direction,
        high=max(stroke.high for stroke in group),
        low=min(stroke.low for stroke in group),
        stroke_ids=list(range(start, end + 1)),
        status="IS_RUNNING",
    )


def _new_running_segment(
    segment_id: int,
    start_index: int,
    start_time: str,
    start_price: float,
    stroke: Stroke,
    stroke_index: int,
    direction: Direction | None = None,
) -> Segment:
    segment_direction = direction or stroke.direction
    end_index, end_time, end_price = _stroke_extreme_point(stroke, segment_direction)
    if segment_direction == "up" and end_price < start_price:
        end_index, end_time, end_price = start_index, start_time, start_price
    if segment_direction == "down" and end_price > start_price:
        end_index, end_time, end_price = start_index, start_time, start_price
    return Segment(
        id=segment_id,
        start_index=start_index,
        end_index=end_index,
        start_time=start_time,
        end_time=end_time,
        start_price=start_price,
        end_price=end_price,
        direction=segment_direction,
        high=max(start_price, stroke.high, end_price),
        low=min(start_price, stroke.low, end_price),
        stroke_ids=[stroke_index],
        status="IS_RUNNING",
    )


def _extend_running_segment(segment: Segment, stroke: Stroke, stroke_index: int) -> Segment:
    extreme_index, extreme_time, extreme_price = _stroke_extreme_point(stroke, segment.direction)
    if segment.direction == "up":
        should_extend = extreme_price >= segment.end_price
    else:
        should_extend = extreme_price <= segment.end_price
    return replace(
        segment,
        end_index=extreme_index if should_extend else segment.end_index,
        end_time=extreme_time if should_extend else segment.end_time,
        end_price=extreme_price if should_extend else segment.end_price,
        high=max(segment.high, extreme_price),
        low=min(segment.low, extreme_price),
        stroke_ids=[*segment.stroke_ids, stroke_index],
        status="IS_RUNNING",
    )


def _update_running_shadow(segment: Segment, stroke: Stroke, stroke_index: int) -> Segment:
    return replace(
        segment,
        stroke_ids=[*segment.stroke_ids, stroke_index],
        status="IS_RUNNING",
    )


def _reverse_break_confirmed(running: Segment, reverse_features: list[tuple[int, Stroke]]) -> bool:
    if len(reverse_features) < 3:
        return False
    last_three = [stroke for _, stroke in reverse_features[-3:]]
    if not _has_common_overlap(last_three):
        return False
    _, current = reverse_features[-1]
    return _breaks_running_endpoint(running, current)


def _confirm_running_at_extreme(segment: Segment) -> Segment:
    return replace(segment, status="CONFIRMED")


def _gap_breaks_running_segment(segment: Segment, stroke: Stroke) -> bool:
    base = max(abs(segment.end_price), 0.01)
    gap = abs(stroke.start_price - segment.end_price) / base
    if gap < REVERSE_GAP_PCT:
        return False
    if segment.direction == "up":
        return stroke.direction == "down" and stroke.start_price < segment.end_price
    return stroke.direction == "up" and stroke.start_price > segment.end_price


def _cut_by_gap(segment: Segment, stroke: Stroke, stroke_index: int) -> tuple[Segment, Segment]:
    confirmed = replace(
        segment,
        end_index=stroke.start_index,
        end_time=stroke.start_time,
        end_price=stroke.start_price,
        high=max(segment.high, stroke.start_price),
        low=min(segment.low, stroke.start_price),
        status="CONFIRMED",
    )
    running = _new_running_segment(
        segment.id + 1,
        stroke.start_index,
        stroke.start_time,
        stroke.start_price,
        stroke,
        stroke_index,
        direction=stroke.direction,
    )
    return confirmed, running


def _opposite(direction: Direction) -> Direction:
    return "down" if direction == "up" else "up"


def _renumber(segments: list[Segment]) -> list[Segment]:
    normalized: list[Segment] = []
    for index, segment in enumerate(segments):
        current = replace(segment, id=index)
        if normalized:
            previous = normalized[-1]
            current = replace(
                current,
                start_index=previous.end_index,
                start_time=previous.end_time,
                start_price=previous.end_price,
                high=max(current.high, previous.end_price),
                low=min(current.low, previous.end_price),
            )
        normalized.append(current)
    return normalized


def _new_running_from_reverse_features(
    segment_id: int,
    confirmed: Segment,
    reverse_features: list[tuple[int, Stroke]],
) -> Segment:
    direction = _opposite(confirmed.direction)
    stroke_ids = [stroke_index for stroke_index, _ in reverse_features]
    strokes = [stroke for _, stroke in reverse_features]
    end_index, end_time, end_price = _extreme_point(strokes, direction)
    return Segment(
        id=segment_id,
        start_index=confirmed.end_index,
        end_index=end_index,
        start_time=confirmed.end_time,
        end_time=end_time,
        start_price=confirmed.end_price,
        end_price=end_price,
        direction=direction,
        high=max([confirmed.end_price, *[stroke.high for stroke in strokes]]),
        low=min([confirmed.end_price, *[stroke.low for stroke in strokes]]),
        stroke_ids=stroke_ids,
        status="IS_RUNNING",
    )


def _extends_running_endpoint(segment: Segment, stroke: Stroke) -> bool:
    _, _, extreme_price = _stroke_extreme_point(stroke, segment.direction)
    if segment.direction == "up":
        return extreme_price > segment.end_price
    return extreme_price < segment.end_price


def _breaks_running_endpoint(segment: Segment, stroke: Stroke) -> bool:
    _, _, extreme_price = _stroke_extreme_point(stroke, _opposite(segment.direction))
    if segment.direction == "up":
        return extreme_price < segment.end_price
    return extreme_price > segment.end_price


def _has_common_overlap(strokes: list[Stroke]) -> bool:
    if len(strokes) < 3:
        return False
    zg = min(stroke.high for stroke in strokes)
    zd = max(stroke.low for stroke in strokes)
    return zg >= zd


def _extreme_point(strokes: list[Stroke], direction: Direction) -> tuple[int, str, float]:
    points: list[tuple[int, str, float]] = []
    for stroke in strokes:
        points.append((stroke.start_index, stroke.start_time, stroke.start_price))
        points.append((stroke.end_index, stroke.end_time, stroke.end_price))
    if direction == "up":
        return max(points, key=lambda item: (item[2], item[0]))
    return min(points, key=lambda item: (item[2], -item[0]))


def _stroke_extreme_point(stroke: Stroke, direction: Direction) -> tuple[int, str, float]:
    if direction == "up":
        if stroke.start_price >= stroke.end_price:
            return stroke.start_index, stroke.start_time, stroke.start_price
        return stroke.end_index, stroke.end_time, stroke.end_price
    if stroke.start_price <= stroke.end_price:
        return stroke.start_index, stroke.start_time, stroke.start_price
    return stroke.end_index, stroke.end_time, stroke.end_price
