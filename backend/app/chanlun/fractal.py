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
    """Keep only an ordered, strictly alternating fractal sequence.

    A same-side fractal can replace the pending endpoint when it is more
    extreme. An opposite-side fractal which is too close is not a valid
    replacement: changing the type of an accepted pivot can create adjacent
    tops/bottoms and strokes whose price direction is impossible.
    """
    result: list[Fractal] = []
    for fractal in fractals:
        if not result:
            result.append(fractal)
            continue

        last = result[-1]
        if fractal.kind == last.kind:
            if _more_extreme(fractal, last):
                result[-1] = fractal
            continue

        if fractal.index - last.index > min_gap:
            result.append(fractal)

        # An opposite fractal inside the minimum distance is ignored. It must
        # never replace ``last`` because that violates the alternation rule.
    return result


def _more_extreme(candidate: Fractal, reference: Fractal) -> bool:
    if candidate.kind == "top":
        return candidate.price > reference.price
    return candidate.price < reference.price