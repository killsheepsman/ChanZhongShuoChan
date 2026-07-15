from __future__ import annotations

from dataclasses import replace

from .models import Direction, Segment, SegmentEvidence, Stroke


def detect_segments(strokes: list[Stroke]) -> list[Segment]:
    """Build same-level segments from strokes with a running-state machine.

    A segment starts only after three adjacent strokes share a common price
    range. It remains ``IS_RUNNING`` until an opposite segment is present and
    either its characteristic sequence or a fixed-boundary break confirms it:

    * an up segment ends after the down-stroke characteristic sequence forms
      a top fractal;
    * a down segment ends after the up-stroke characteristic sequence forms
      a bottom fractal.

    The first reverse three actual strokes must have one common overlap. Once
    formed, that reverse line keeps updating its extreme. It may also end the
    old line by crossing the old line's *fixed starting boundary*; the
    boundary never drifts with later internal highs or lows.
    """
    first_start = _find_first_overlap(strokes)
    if first_start is None:
        return []

    running = _segment_from_range(strokes, first_start, first_start + 2, 0, "IS_RUNNING")
    segments: list[Segment] = []
    running_start = first_start
    # A characteristic sequence contains every stroke opposite to the segment
    # direction, including elements in the three strokes that formed it. Those
    # early elements provide the left side of the first valid fractal; the new
    # reverse segment still has to form outside the initial three strokes.
    feature_ids = [
        item
        for item in range(first_start, first_start + 3)
        if strokes[item].direction != running.direction
    ]

    candidate_start: int | None = None
    for index in range(first_start + 3, len(strokes)):
        stroke = strokes[index]
        if stroke.direction != running.direction:
            feature_ids.append(index)

        if candidate_start is not None and _candidate_is_invalidated(
            strokes[index], strokes[candidate_start], running.direction
        ):
            candidate_start = None

        # Any reverse three-stroke overlap starts one candidate line. It is
        # not allowed to end the old line until later confirmation arrives.
        window_start = index - 2
        window_candidate = (
            _candidate_from_reverse_strokes(strokes, window_start, index, running.direction)
            if window_start >= running_start + 3
            else None
        )
        if candidate_start is None and window_candidate is not None:
            candidate_start = window_start

        running_candidate = (
            _candidate_from_reverse_strokes(strokes, candidate_start, index, running.direction)
            if candidate_start is not None
            else None
        )
        boundary_break = running_candidate is not None and _breaks_start_boundary(running, running_candidate)

        characteristic_ids = feature_ids[-3:] if len(feature_ids) >= 3 else []
        characteristic_break = (
            running_candidate is not None
            and bool(characteristic_ids)
            and _breaks_characteristic_sequence(strokes, characteristic_ids, running.direction)
        )
        if not (boundary_break or characteristic_break):
            running = _extend_segment(running, strokes, index)
            continue

        confirmation_candidate = running_candidate
        confirmation_start = candidate_start
        assert confirmation_candidate is not None and confirmation_start is not None
        confirmation_boundary_break = _breaks_start_boundary(running, confirmation_candidate)
        break_condition = _break_condition(
            running.direction, characteristic_break, confirmation_boundary_break
        )

        # The opposite line is already structurally complete. Lock the old
        # line immediately before the candidate starts, then create the new
        # line at the exact locked endpoint.
        confirmed = _segment_from_range(
            strokes,
            running_start,
            confirmation_start - 1,
            len(segments),
            "CONFIRMED",
            formation_ids=running.evidence.formation_stroke_ids if running.evidence else None,
            confirmation_candidate=confirmation_candidate,
            characteristic_ids=characteristic_ids if characteristic_break else None,
            break_condition=break_condition,
            start_anchor=(running.start_index, running.start_time, running.start_price),
        )
        segments.append(confirmed)

        running_start = confirmation_start
        running = _anchor_to_previous(
            _segment_from_range(
                strokes,
                running_start,
                index,
                len(segments),
                "IS_RUNNING",
                formation_ids=(confirmation_candidate.evidence.formation_stroke_ids if confirmation_candidate.evidence else None),
            ),
            confirmed,
        )
        feature_ids = [
            item
            for item in range(running_start, index + 1)
            if strokes[item].direction != running.direction
        ]
        candidate_start = None

    segments.append(replace(running, id=len(segments), status="IS_RUNNING"))
    return segments


def _find_first_overlap(strokes: list[Stroke]) -> int | None:
    for start in range(len(strokes) - 2):
        if _overlap_bounds(strokes[start : start + 3]) is not None:
            return start
    return None


def _segment_from_range(
    strokes: list[Stroke],
    start: int,
    end: int,
    segment_id: int,
    status: str,
    formation_ids: list[int] | None = None,
    confirmation_candidate: Segment | None = None,
    characteristic_ids: list[int] | None = None,
    break_condition: str | None = None,
    start_anchor: tuple[int, str, float] | None = None,
) -> Segment:
    group = strokes[start : end + 1]
    first = group[0]
    end_index, end_time, end_price = _directional_endpoint(group, first.direction)
    formation_ids = formation_ids or list(range(start, min(start + 3, end + 1)))
    formation = [strokes[item] for item in formation_ids]
    formation_overlap = _overlap_bounds(formation)
    start_index, start_time, start_price = start_anchor or (first.start_index, first.start_time, first.start_price)
    evidence = SegmentEvidence(
        formation_stroke_ids=list(formation_ids),
        formation_zd=formation_overlap[0] if formation_overlap else None,
        formation_zg=formation_overlap[1] if formation_overlap else None,
        guard_side=_guard_side(first.direction),
        guard_price=start_price,
    )
    if confirmation_candidate is not None:
        candidate_evidence = confirmation_candidate.evidence or SegmentEvidence()
        break_id = confirmation_candidate.stroke_ids[-1]
        break_stroke = strokes[break_id]
        feature_pattern = _characteristic_pattern(first.direction) if characteristic_ids else None
        evidence = replace(
            evidence,
            candidate_stroke_ids=list(candidate_evidence.formation_stroke_ids),
            candidate_zd=candidate_evidence.formation_zd,
            candidate_zg=candidate_evidence.formation_zg,
            characteristic_stroke_ids=list(characteristic_ids or []),
            characteristic_pattern=feature_pattern,
            candidate_extreme=_candidate_extreme(confirmation_candidate),
            break_stroke_id=break_id,
            break_time=_stroke_extreme_point(break_stroke, confirmation_candidate.direction)[1],
            break_reason=(
                f"reverse three-stroke overlap [{candidate_evidence.formation_zd:.2f}, "
                f"{candidate_evidence.formation_zg:.2f}] and {break_condition}"
            ),
        )
    return Segment(
        id=segment_id,
        start_index=start_index,
        end_index=end_index,
        start_time=start_time,
        end_time=end_time,
        start_price=start_price,
        end_price=end_price,
        direction=first.direction,
        high=max(start_price, *(stroke.high for stroke in group)),
        low=min(start_price, *(stroke.low for stroke in group)),
        stroke_ids=list(range(start, end + 1)),
        status=status,  # type: ignore[arg-type]
        evidence=evidence,
    )


def _extend_segment(segment: Segment, strokes: list[Stroke], end: int) -> Segment:
    if not segment.stroke_ids or end <= segment.stroke_ids[-1]:
        return segment
    return _segment_from_range(
        strokes,
        segment.stroke_ids[0],
        end,
        segment.id,
        "IS_RUNNING",
        formation_ids=segment.evidence.formation_stroke_ids if segment.evidence else None,
        start_anchor=(segment.start_index, segment.start_time, segment.start_price),
    )


def _candidate_from_reverse_strokes(
    strokes: list[Stroke], start: int, end: int, running_direction: Direction
) -> Segment | None:
    if start + 2 >= len(strokes):
        return None
    group = strokes[start : start + 3]
    if group[0].direction == running_direction or _overlap_bounds(group) is None:
        return None
    return _segment_from_range(
        strokes,
        start,
        end,
        -1,
        "IS_RUNNING",
        formation_ids=list(range(start, start + 3)),
    )


def _breaks_characteristic_sequence(
    strokes: list[Stroke], feature_ids: list[int], running_direction: Direction
) -> bool:
    first, middle, last = (strokes[item] for item in feature_ids)
    if running_direction == "up":
        return middle.high > first.high and middle.high > last.high and middle.low > first.low and middle.low > last.low
    return middle.high < first.high and middle.high < last.high and middle.low < first.low and middle.low < last.low


def _characteristic_pattern(direction: Direction) -> str:
    if direction == "up":
        return "down-stroke characteristic sequence formed a top fractal"
    return "up-stroke characteristic sequence formed a bottom fractal"


def _breaks_start_boundary(running: Segment, candidate: Segment) -> bool:
    extreme = _candidate_extreme(candidate)
    return extreme < running.start_price if running.direction == "up" else extreme > running.start_price


def _candidate_is_invalidated(current: Stroke, candidate_first: Stroke, running_direction: Direction) -> bool:
    """A renewed old-direction extreme invalidates an unconfirmed candidate."""
    if current.direction != running_direction:
        return False
    if running_direction == "up":
        return current.high > candidate_first.high
    return current.low < candidate_first.low


def _break_condition(direction: Direction, characteristic_break: bool, boundary_break: bool) -> str:
    conditions: list[str] = []
    if characteristic_break:
        conditions.append(_characteristic_pattern(direction))
    if boundary_break:
        side = "low" if direction == "up" else "high"
        conditions.append(f"reverse-line extreme crossed original {side} boundary")
    return " and ".join(conditions)


def _anchor_to_previous(segment: Segment, previous: Segment) -> Segment:
    return replace(
        segment,
        start_index=previous.end_index,
        start_time=previous.end_time,
        start_price=previous.end_price,
        high=max(previous.end_price, segment.high),
        low=min(previous.end_price, segment.low),
    )


def _directional_endpoint(strokes: list[Stroke], direction: Direction) -> tuple[int, str, float]:
    best_index, best_time, best_price = _stroke_extreme_point(strokes[0], direction)
    for stroke in strokes[1:]:
        index, time, price = _stroke_extreme_point(stroke, direction)
        # Equal extrema belong to the later stroke so the rendered endpoint
        # stays at the final same-price pivot instead of ending in empty space.
        if (direction == "up" and price >= best_price) or (direction == "down" and price <= best_price):
            best_index, best_time, best_price = index, time, price
    return best_index, best_time, best_price


def _stroke_extreme_point(stroke: Stroke, direction: Direction) -> tuple[int, str, float]:
    if direction == "up":
        return (stroke.end_index, stroke.end_time, stroke.high) if stroke.direction == "up" else (stroke.start_index, stroke.start_time, stroke.high)
    return (stroke.end_index, stroke.end_time, stroke.low) if stroke.direction == "down" else (stroke.start_index, stroke.start_time, stroke.low)


def _overlap_bounds(strokes: list[Stroke]) -> tuple[float, float] | None:
    if len(strokes) != 3:
        return None
    zg = min(stroke.high for stroke in strokes)
    zd = max(stroke.low for stroke in strokes)
    return (zd, zg) if zg > zd else None


def _candidate_extreme(candidate: Segment) -> float:
    return candidate.high if candidate.direction == "up" else candidate.low


def _guard_side(direction: Direction) -> str:
    return "low" if direction == "up" else "high"
