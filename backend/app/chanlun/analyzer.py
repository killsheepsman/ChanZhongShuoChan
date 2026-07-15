from __future__ import annotations

from dataclasses import asdict, replace

from .center import detect_center_expansions, detect_centers
from .divergence import detect_divergences
from .fractal import _dedupe_alternating, detect_fractals
from .kline import process_inclusion
from .macd import calculate_macd, continue_macd
from .models import Fractal, KLine
from .segment import detect_segments
from .signals import detect_buy_sell_points
from .stroke import detect_strokes
from .theory import detect_theory_marks
from .trend import classify_trend


ANALYSIS_ENGINE_VERSION = "chan-structure-v5"
INCREMENTAL_KLINE_OVERLAP = 5


def analyze_klines(klines: list[KLine]) -> dict:
    processed = process_inclusion(klines)
    fractals = detect_fractals(processed)
    macd = calculate_macd(processed)
    return _assemble(klines, processed, fractals, macd)


def continue_analysis(cached: dict, klines: list[KLine]) -> tuple[dict, dict]:
    """Continue a cached analysis from a bounded mutable K-line tail."""
    cached_raw = [KLine(**item) for item in cached.get("raw_klines", [])]
    cached_processed = [KLine(**item) for item in cached.get("klines", [])]
    if not cached_raw or not cached_processed or len(klines) <= len(cached_raw):
        return analyze_klines(klines), {"mode": "rebuild", "new_kline_count": 0, "recomputed_from_time": klines[0].time if klines else None}

    new_raw = klines[len(cached_raw) :]
    tail_start = max(0, len(cached_processed) - INCREMENTAL_KLINE_OVERLAP)
    tail_input = [*cached_processed[tail_start:], *new_raw]
    rebuilt_tail = process_inclusion(tail_input)
    processed = [*cached_processed[:tail_start], *rebuilt_tail]
    processed = [replace(item, index=index) for index, item in enumerate(processed)]

    # Same-side fractals can keep replacing the pending endpoint for an
    # arbitrarily long swing. The last confirmed stroke's start pivot is the
    # safe structural boundary; everything after it is a mutable tail.
    cached_strokes = cached.get("strokes", [])
    confirmed_strokes = [item for item in cached_strokes if item.get("status") == "CONFIRMED"]
    stable_pivot = confirmed_strokes[-1]["start_index"] if confirmed_strokes else 1
    fractal_start = max(0, int(stable_pivot) - 1)
    old_fractals = [Fractal(**item) for item in cached.get("fractals", [])]
    preserved_fractals = [item for item in old_fractals if item.index < stable_pivot]
    tail_fractals = detect_fractals(processed[fractal_start:])
    fractals = _dedupe_alternating([*preserved_fractals, *tail_fractals], min_gap=1)

    cached_macd = cached.get("macd", [])
    if tail_start and len(cached_macd) >= tail_start and "ema12" in cached_macd[tail_start - 1]:
        macd = continue_macd(cached_macd[:tail_start], processed[tail_start:])
    else:
        macd = calculate_macd(processed)

    result = _assemble(klines, processed, fractals, macd)
    return result, {
        "mode": "incremental",
        "new_kline_count": len(new_raw),
        "recomputed_from_time": processed[tail_start].time if processed else None,
    }


def _assemble(
    raw: list[KLine], processed: list[KLine], fractals: list[Fractal], macd: list[dict[str, float]]
) -> dict:
    strokes = detect_strokes(fractals)
    confirmed_strokes = [stroke for stroke in strokes if stroke.status == "CONFIRMED"]
    segments = detect_segments(confirmed_strokes)
    confirmed_segments = [segment for segment in segments if segment.status == "CONFIRMED"]
    centers = detect_centers(confirmed_segments)
    center_expansions = detect_center_expansions(centers)
    divergences = detect_divergences(confirmed_segments, centers, macd)
    signals = detect_buy_sell_points(segments, centers, divergences, processed, confirmed_strokes)
    theory_marks = detect_theory_marks(processed, segments, centers, divergences, signals, macd)
    trend = classify_trend(centers)
    return {
        "raw_klines": [asdict(item) for item in raw],
        "klines": [asdict(item) for item in processed],
        "fractals": [asdict(item) for item in fractals],
        "strokes": [asdict(item) for item in strokes],
        "segments": [asdict(item) for item in segments],
        "centers": [asdict(item) for item in centers],
        "center_expansions": [asdict(item) for item in center_expansions],
        "divergences": [asdict(item) for item in divergences],
        "macd": macd,
        "signals": [asdict(item) for item in signals],
        "theory_marks": [asdict(item) for item in theory_marks],
        "trend": trend,
        "summary": {
            "kline_count": len(processed),
            "fractal_count": len(fractals),
            "stroke_count": len(strokes),
            "segment_count": len(segments),
            "center_count": len(centers),
            "center_expansion_count": len(center_expansions),
            "divergence_count": len(divergences),
            "signal_count": len(signals),
            "theory_mark_count": len(theory_marks),
        },
    }
