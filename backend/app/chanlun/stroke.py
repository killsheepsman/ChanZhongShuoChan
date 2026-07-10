from __future__ import annotations

from .models import Fractal, Stroke


def detect_strokes(
    fractals: list[Fractal],
    min_kline_count: int = 3,
    min_amplitude_pct: float = 0.003,
) -> list[Stroke]:
    """Build a continuous stroke chain from confirmed alternating fractals.

    A later, more extreme same-side fractal may replace the prior endpoint before
    the opposite fractal qualifies. Build the pivot list first, then materialize
    strokes, so a previously emitted stroke cannot retain an obsolete endpoint.
    """
    if len(fractals) < 2:
        return []

    pivots: list[Fractal] = [fractals[0]]
    for current in fractals[1:]:
        last = pivots[-1]
        if current.kind == last.kind:
            if _more_extreme(last, current) != last:
                pivots[-1] = current
            continue
        if (
            _is_valid_distance(last, current, min_kline_count)
            and _is_valid_amplitude(last, current, min_amplitude_pct)
            and _has_expected_price_direction(last, current)
        ):
            pivots.append(current)

    strokes: list[Stroke] = []
    for start, end in zip(pivots, pivots[1:]):
        direction = "up" if end.price > start.price else "down"
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
            )
        )
    return _continuous_strokes(strokes)


def _more_extreme(left: Fractal, right: Fractal) -> Fractal:
    if left.kind == "top":
        return right if right.price > left.price else left
    return right if right.price < left.price else left


def _is_valid_distance(left: Fractal, right: Fractal, min_kline_count: int) -> bool:
    return abs(right.index - left.index) >= min_kline_count


def _is_valid_amplitude(left: Fractal, right: Fractal, min_amplitude_pct: float) -> bool:
    base = max(min(abs(left.price), abs(right.price)), 0.01)
    return abs(right.price - left.price) / base >= min_amplitude_pct


def _has_expected_price_direction(start: Fractal, end: Fractal) -> bool:
    return (start.kind == "bottom" and end.kind == "top" and end.price > start.price) or (
        start.kind == "top" and end.kind == "bottom" and end.price < start.price
    )


def _matches_fractal_direction(start: Fractal, end: Fractal, direction: str) -> bool:
    if direction == "up":
        return start.kind == "bottom" and end.kind == "top" and end.price > start.price
    return start.kind == "top" and end.kind == "bottom" and end.price < start.price


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