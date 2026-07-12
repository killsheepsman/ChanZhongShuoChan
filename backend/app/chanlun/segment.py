from __future__ import annotations

from dataclasses import replace

from .models import Direction, Segment, SegmentEvidence, Stroke


def detect_segments(strokes: list[Stroke]) -> list[Segment]:
    """Build line segments with a single running-state record.

    A segment is born only from three consecutive strokes with one common
    overlap.  It remains running while ordinary counter-trend strokes appear.
    It can be confirmed as finished only when a *new*, opposite three-stroke
    segment both has common overlap and crosses the prior segment guard.  The
    output retains the candidate and confirmation evidence so each drawn line
    can be audited instead of being inferred from its colour on the chart.
    """
    if len(strokes) < 3:
        return []

    first_start = _find_first_overlap(strokes)
    if first_start is None:
        return []

    running = _segment_from_strokes(strokes, first_start, first_start + 2, 0, "IS_RUNNING")
    segments: list[Segment] = []
    last_consumed = first_start + 2
    scan = first_start + 3

    while scan + 2 < len(strokes):
        # Before assessing a reverse three-stroke candidate, absorb every
        # earlier, unconsumed stroke into the one running segment. The three
        # candidate strokes themselves stay outside the old segment until the
        # break is confirmed.
        if last_consumed < scan - 1:
            running = _extend_to_strokes(running, strokes[last_consumed + 1 : scan], scan - 1)
            last_consumed = scan - 1

        candidate = _candidate_from_strokes(strokes, scan)
        if candidate is not None and candidate.direction != running.direction:
            # The candidate is deliberately recorded even when it cannot yet
            # break the running segment.  This prevents a small counter-move
            # from being silently promoted to a confirmed segment.
            observed = _with_candidate_evidence(running, candidate)
            if _breaks_running_segment(observed, candidate):
                confirmed = _confirm_segment(
                    observed,
                    candidate,
                    strokes[scan : scan + 3],
                    len(segments),
                )
                segments.append(confirmed)

                # The new segment is created immediately at the locked former
                # endpoint.  It is still running until another full reverse
                # segment breaks it.
                running = _anchor_to_previous(
                    _segment_from_strokes(strokes, scan, scan + 2, len(segments), "IS_RUNNING"),
                    confirmed,
                )
                last_consumed = scan + 2
                scan += 3
                continue
            running = observed

        scan += 1

    if last_consumed + 1 < len(strokes):
        running = _extend_to_strokes(running, strokes[last_consumed + 1 :], len(strokes) - 1)

    segments.append(replace(running, id=len(segments), status="IS_RUNNING"))
    return segments


def _find_first_overlap(strokes: list[Stroke]) -> int | None:
    for start in range(len(strokes) - 2):
        if _overlap_bounds(strokes[start : start + 3]) is not None:
            return start
    return None


def _segment_from_strokes(
    strokes: list[Stroke],
    start_stroke: int,
    end_stroke: int,
    segment_id: int,
    status: str,
) -> Segment:
    group = strokes[start_stroke : end_stroke + 1]
    first = group[0]
    end_index, end_time, end_price = _directional_endpoint(group, first.direction)
    overlap = _overlap_bounds(group)
    evidence = SegmentEvidence(
        formation_stroke_ids=list(range(start_stroke, end_stroke + 1)),
        formation_zd=overlap[0] if overlap else None,
        formation_zg=overlap[1] if overlap else None,
        guard_side=_guard_side(first.direction),
        guard_price=_guard_price_from_range(first.direction, group),
    )
    return Segment(
        id=segment_id,
        start_index=first.start_index,
        end_index=end_index,
        start_time=first.start_time,
        end_time=end_time,
        start_price=first.start_price,
        end_price=end_price,
        direction=first.direction,
        high=max(stroke.high for stroke in group),
        low=min(stroke.low for stroke in group),
        stroke_ids=list(range(start_stroke, end_stroke + 1)),
        status=status,  # type: ignore[arg-type]
        evidence=evidence,
    )


def _anchor_to_previous(segment: Segment, previous: Segment) -> Segment:
    """Create the next running line at the exact locked old-line endpoint."""
    return replace(
        segment,
        start_index=previous.end_index,
        start_time=previous.end_time,
        start_price=previous.end_price,
        high=max(previous.end_price, segment.high),
        low=min(previous.end_price, segment.low),
    )


def _extend_to_strokes(segment: Segment, extra_strokes: list[Stroke], end_stroke_id: int) -> Segment:
    if not extra_strokes:
        return segment
    end_index, end_time, end_price = _directional_endpoint(extra_strokes, segment.direction, segment)
    evidence = segment.evidence or SegmentEvidence()
    high = max(segment.high, *(stroke.high for stroke in extra_strokes))
    low = min(segment.low, *(stroke.low for stroke in extra_strokes))
    return replace(
        segment,
        end_index=end_index,
        end_time=end_time,
        end_price=end_price,
        high=high,
        low=low,
        stroke_ids=[*segment.stroke_ids, *range(end_stroke_id - len(extra_strokes) + 1, end_stroke_id + 1)],
        status="IS_RUNNING",
        evidence=replace(
            evidence,
            guard_side=_guard_side(segment.direction),
            guard_price=low if segment.direction == "up" else high,
        ),
    )


def _candidate_from_strokes(strokes: list[Stroke], start: int) -> Segment | None:
    group = strokes[start : start + 3]
    if len(group) != 3:
        return None
    overlap = _overlap_bounds(group)
    if overlap is None:
        return None
    return _segment_from_strokes(strokes, start, start + 2, -1, "IS_RUNNING")


def _with_candidate_evidence(running: Segment, candidate: Segment) -> Segment:
    candidate_evidence = candidate.evidence or SegmentEvidence()
    evidence = running.evidence or SegmentEvidence()
    return replace(
        running,
        evidence=replace(
            evidence,
            candidate_stroke_ids=list(candidate.stroke_ids),
            candidate_zd=candidate_evidence.formation_zd,
            candidate_zg=candidate_evidence.formation_zg,
            guard_side=_guard_side(running.direction),
            guard_price=_guard_price(running),
            candidate_extreme=_candidate_extreme(candidate),
            break_stroke_id=None,
            break_time=None,
            break_reason=None,
        ),
    )


def _breaks_running_segment(running: Segment, candidate: Segment) -> bool:
    """A reverse three-stroke line must break the old line's opposite guard."""
    guard = _guard_price(running)
    extreme = _candidate_extreme(candidate)
    return extreme < guard if running.direction == "up" else extreme > guard


def _confirm_segment(
    running: Segment,
    candidate: Segment,
    candidate_strokes: list[Stroke],
    segment_id: int,
) -> Segment:
    evidence = running.evidence or SegmentEvidence()
    break_stroke_id, break_stroke = _break_stroke(candidate_strokes, candidate.direction, candidate.stroke_ids)
    return replace(
        running,
        id=segment_id,
        status="CONFIRMED",
        evidence=replace(
            evidence,
            break_stroke_id=break_stroke_id,
            break_time=_stroke_extreme_point(break_stroke, candidate.direction)[1],
            break_reason=(
                f"reverse three-stroke overlap [{evidence.candidate_zd:.2f}, {evidence.candidate_zg:.2f}] "
                f"crossed {evidence.guard_side} guard {evidence.guard_price:.2f}"
            ),
        ),
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
        if stroke.direction == "down":
            return stroke.end_index, stroke.end_time, stroke.low
        return stroke.start_index, stroke.start_time, stroke.low
    return stroke.start_index, stroke.start_time, stroke.low


def _overlap_bounds(strokes: list[Stroke]) -> tuple[float, float] | None:
    if len(strokes) != 3:
        return None
    zg = min(stroke.high for stroke in strokes)
    zd = max(stroke.low for stroke in strokes)
    return (zd, zg) if zg > zd else None


def _guard_side(direction: Direction) -> str:
    return "low" if direction == "up" else "high"


def _guard_price(segment: Segment) -> float:
    return segment.low if segment.direction == "up" else segment.high


def _guard_price_from_range(direction: Direction, strokes: list[Stroke]) -> float:
    return min(stroke.low for stroke in strokes) if direction == "up" else max(stroke.high for stroke in strokes)


def _candidate_extreme(candidate: Segment) -> float:
    return candidate.high if candidate.direction == "up" else candidate.low


def _break_stroke(
    candidate_strokes: list[Stroke], direction: Direction, stroke_ids: list[int]
) -> tuple[int, Stroke]:
    """Return the actual candidate stroke that crosses the old guard."""
    if direction == "up":
        position = max(range(len(candidate_strokes)), key=lambda item: candidate_strokes[item].high)
    else:
        position = min(range(len(candidate_strokes)), key=lambda item: candidate_strokes[item].low)
    return stroke_ids[position], candidate_strokes[position]
