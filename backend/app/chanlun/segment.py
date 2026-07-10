from __future__ import annotations

from dataclasses import replace

from .models import Direction, Segment, Stroke


def detect_segments(strokes: list[Stroke]) -> list[Segment]:
    """Build continuous segments with one running state-machine record.

    A segment begins with a valid consecutive three-stroke overlap.  The
    scanner then advances stroke by stroke: only a later valid *opposite*
    three-stroke unit confirms the running segment.  This matters when the
    first possible reverse unit has no overlap; stepping by three would skip a
    later valid reverse unit and incorrectly absorb it into the old segment.
    """
    if len(strokes) < 3:
        return []

    first_start = _find_first_overlap(strokes)
    if first_start is None:
        return []

    running = _segment_from_strokes(0, strokes, first_start, first_start + 2, "IS_RUNNING")
    segments: list[Segment] = []
    last_consumed = first_start + 2
    scan = first_start + 3

    while scan + 2 < len(strokes):
        candidate = strokes[scan : scan + 3]
        if _has_common_overlap(candidate) and candidate[0].direction != running.direction:
            # Lock the old line at its directional extreme before the reverse
            # unit. The next line will be anchored to this same endpoint.
            if last_consumed + 1 < scan:
                running = _extend_to_stroke(running, strokes[last_consumed + 1 : scan], scan - 1)
            segments.append(replace(running, id=len(segments), status="CONFIRMED"))

            running = _segment_from_strokes(len(segments), strokes, scan, scan + 2, "IS_RUNNING")
            last_consumed = scan + 2
            scan += 3
            continue

        # No reversing unit yet: the single pending line keeps only its
        # directional high/low as its visible endpoint.
        if last_consumed < scan:
            running = _extend_to_stroke(running, [strokes[scan]], scan)
            last_consumed = scan
        scan += 1

    if last_consumed + 1 < len(strokes):
        running = _extend_to_stroke(running, strokes[last_consumed + 1 :], len(strokes) - 1)

    segments.append(replace(running, id=len(segments), status="IS_RUNNING"))
    return _renumber_continuous(segments)


def _find_first_overlap(strokes: list[Stroke]) -> int | None:
    for start in range(len(strokes) - 2):
        if _has_common_overlap(strokes[start : start + 3]):
            return start
    return None


def _segment_from_strokes(
    segment_id: int,
    strokes: list[Stroke],
    start_stroke: int,
    end_stroke: int,
    status: str,
) -> Segment:
    group = strokes[start_stroke : end_stroke + 1]
    first = group[0]
    end_index, end_time, end_price = _directional_endpoint(group, first.direction)
    return Segment(
        id=segment_id,
        start_index=first.start_index,
        end_index=end_index,
        start_time=first.start_time,
        end_time=end_time,
        start_price=first.start_price,
        end_price=end_price,
        direction=first.direction,
        high=max(first.start_price, end_price),
        low=min(first.start_price, end_price),
        stroke_ids=list(range(start_stroke, end_stroke + 1)),
        status=status,  # type: ignore[arg-type]
    )


def _extend_to_stroke(segment: Segment, extra_strokes: list[Stroke], end_stroke_id: int) -> Segment:
    if not extra_strokes:
        return segment
    end_index, end_time, end_price = _directional_endpoint(extra_strokes, segment.direction, segment)
    return replace(
        segment,
        end_index=end_index,
        end_time=end_time,
        end_price=end_price,
        high=max(segment.start_price, end_price),
        low=min(segment.start_price, end_price),
        stroke_ids=[*segment.stroke_ids, *range(end_stroke_id - len(extra_strokes) + 1, end_stroke_id + 1)],
        status="IS_RUNNING",
    )


def _directional_endpoint(
    strokes: list[Stroke], direction: Direction, previous: Segment | None = None
) -> tuple[int, str, float]:
    if previous is not None:
        best_index, best_time, best_price = previous.end_index, previous.end_time, previous.end_price
    else:
        best_index, best_time, best_price = _stroke_extreme_point(strokes[0], direction)

    for stroke in strokes:
        index, time, price = _stroke_extreme_point(stroke, direction)
        if (direction == "up" and price > best_price) or (direction == "down" and price < best_price):
            best_index, best_time, best_price = index, time, price
    return best_index, best_time, best_price


def _stroke_extreme_point(stroke: Stroke, direction: Direction) -> tuple[int, str, float]:
    if direction == "up":
        if stroke.direction == "up":
            return stroke.end_index, stroke.end_time, stroke.high
        return stroke.start_index, stroke.start_time, stroke.high
    if stroke.direction == "down":
        return stroke.end_index, stroke.end_time, stroke.low
    return stroke.start_index, stroke.start_time, stroke.low


def _has_common_overlap(strokes: list[Stroke]) -> bool:
    if len(strokes) != 3:
        return False
    zg = min(stroke.high for stroke in strokes)
    zd = max(stroke.low for stroke in strokes)
    return zg > zd


def _renumber_continuous(segments: list[Segment]) -> list[Segment]:
    result: list[Segment] = []
    for segment_id, segment in enumerate(segments):
        current = replace(segment, id=segment_id)
        if result:
            previous = result[-1]
            current = replace(
                current,
                start_index=previous.end_index,
                start_time=previous.end_time,
                start_price=previous.end_price,
                high=max(previous.end_price, current.end_price),
                low=min(previous.end_price, current.end_price),
            )
        result.append(current)
    return result