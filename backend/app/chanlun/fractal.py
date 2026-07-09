from __future__ import annotations

from .models import Fractal, KLine


def detect_fractals(klines: list[KLine], min_gap: int = 1) -> list[Fractal]:
    fractals: list[Fractal] = []
    if len(klines) < 3:
        return fractals

    for i in range(1, len(klines) - 1):
        prev_k = klines[i - 1]
        current = klines[i]
        next_k = klines[i + 1]

        is_top = current.high > prev_k.high and current.high > next_k.high
        is_bottom = current.low < prev_k.low and current.low < next_k.low

        if is_top:
            fractals.append(
                Fractal(index=current.index, time=current.time, kind="top", price=current.high, high=current.high, low=current.low)
            )
        elif is_bottom:
            fractals.append(
                Fractal(index=current.index, time=current.time, kind="bottom", price=current.low, high=current.high, low=current.low)
            )
    return _dedupe_alternating(fractals, min_gap)


def _dedupe_alternating(fractals: list[Fractal], min_gap: int) -> list[Fractal]:
    result: list[Fractal] = []
    for fractal in fractals:
        if not result:
            result.append(fractal)
            continue
        last = result[-1]
        if fractal.kind != last.kind and fractal.index - last.index > min_gap:
            result.append(fractal)
            continue
        if fractal.kind == "top" and fractal.price > last.price:
            result[-1] = fractal
        elif fractal.kind == "bottom" and fractal.price < last.price:
            result[-1] = fractal
    return result
