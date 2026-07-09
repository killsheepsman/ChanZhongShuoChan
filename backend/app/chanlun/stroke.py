from __future__ import annotations

from .models import Fractal, Stroke


def detect_strokes(
    fractals: list[Fractal],
    min_kline_count: int = 3,
    min_amplitude_pct: float = 0.003,
) -> list[Stroke]:
    strokes: list[Stroke] = []
    if len(fractals) < 2:
        return strokes

    last = fractals[0]
    for current in fractals[1:]:
        if current.kind == last.kind:
            last = _more_extreme(last, current)
            continue
        if not _is_valid_distance(last, current, min_kline_count) or not _is_valid_amplitude(last, current, min_amplitude_pct):
            continue
        direction = "up" if last.kind == "bottom" and current.kind == "top" else "down"
        strokes.append(
            Stroke(
                start_index=last.index,
                end_index=current.index,
                start_time=last.time,
                end_time=current.time,
                start_price=last.price,
                end_price=current.price,
                direction=direction,
                high=max(last.price, current.price),
                low=min(last.price, current.price),
            )
        )
        last = current
    return strokes


def _more_extreme(left: Fractal, right: Fractal) -> Fractal:
    if left.kind == "top":
        return right if right.price > left.price else left
    return right if right.price < left.price else left


def _is_valid_distance(left: Fractal, right: Fractal, min_kline_count: int) -> bool:
    return abs(right.index - left.index) >= min_kline_count


def _is_valid_amplitude(left: Fractal, right: Fractal, min_amplitude_pct: float) -> bool:
    base = max(min(abs(left.price), abs(right.price)), 0.01)
    return abs(right.price - left.price) / base >= min_amplitude_pct
