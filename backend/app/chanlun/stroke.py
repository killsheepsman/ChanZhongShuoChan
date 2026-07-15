from __future__ import annotations

from .models import Fractal, Stroke


def detect_strokes(
    fractals: list[Fractal],
    min_kline_count: int = 4,
    min_amplitude_pct: float | None = None,
) -> list[Stroke]:
    """Build a continuous stroke chain from confirmed alternating fractals.

    A later, more extreme same-side fractal may replace the prior endpoint before
    the opposite fractal qualifies. Build the pivot list first, then materialize
    strokes, so a previously emitted stroke cannot retain an obsolete endpoint.
    """
    first_bottom = next((index for index, item in enumerate(fractals) if item.kind == "bottom"), None)
    if first_bottom is None or first_bottom >= len(fractals) - 1:
        return []

    pivots: list[Fractal] = [fractals[first_bottom]]
    for current in fractals[first_bottom + 1 :]:
        last = pivots[-1]
        if current.kind == last.kind:
            if _is_more_extreme(current, last):
                pivots[-1] = current
            continue
        if not _is_valid_distance(last, current, min_kline_count):
            continue
        if not _has_expected_price_direction(last, current):
            continue
        if min_amplitude_pct is not None and min_amplitude_pct > 0 and not _is_valid_amplitude(last, current, min_amplitude_pct):
            continue
        pivots.append(current)

    strokes: list[Stroke] = []
    last_position = len(pivots) - 2
    for position, (start, end) in enumerate(zip(pivots, pivots[1:])):
        direction = "up" if start.kind == "bottom" else "down"
        if not _matches_fractal_direction(start, end, direction):
            continue
        strokes.append(
            Stroke(
                start_index=start.index,
                end_index=end.index,
                start_time=start.time,
                end_time=end.time,
                start_price=start.price,
                end_price=end.price,
                direction=direction,
                high=max(start.price, end.price),
                low=min(start.price, end.price),
                status="PENDING" if position == last_position else "CONFIRMED",
            )
        )
    return strokes


def _is_more_extreme(candidate: Fractal, reference: Fractal) -> bool:
    if candidate.kind == "top":
        return candidate.high > reference.high
    return candidate.low < reference.low


def _is_valid_distance(left: Fractal, right: Fractal, min_kline_count: int) -> bool:
    # An index distance of four means five processed K-lines including endpoints.
    return abs(right.index - left.index) >= min_kline_count


def _is_valid_amplitude(left: Fractal, right: Fractal, min_amplitude_pct: float) -> bool:
    base = max(min(abs(left.price), abs(right.price)), 0.01)
    return abs(right.price - left.price) / base >= min_amplitude_pct


def _has_expected_price_direction(start: Fractal, end: Fractal) -> bool:
    return (start.kind == "bottom" and end.kind == "top" and end.high > start.high) or (
        start.kind == "top" and end.kind == "bottom" and end.low < start.low
    )


def _matches_fractal_direction(start: Fractal, end: Fractal, direction: str) -> bool:
    if direction == "up":
        return start.kind == "bottom" and end.kind == "top" and end.high > start.high
    return start.kind == "top" and end.kind == "bottom" and end.low < start.low


def _continuous_strokes(strokes: list[Stroke]) -> list[Stroke]:
    """Reject malformed links instead of allowing them to corrupt segments."""
    result: list[Stroke] = []
    for stroke in strokes:
        if stroke.end_index <= stroke.start_index:
            continue
        if stroke.direction == "up" and stroke.end_price <= stroke.start_price:
            continue
        if stroke.direction == "down" and stroke.end_price >= stroke.start_price:
            continue
        if result and result[-1].end_index != stroke.start_index:
            continue
        result.append(stroke)
    return result