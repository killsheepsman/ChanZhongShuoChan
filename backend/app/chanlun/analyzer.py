from __future__ import annotations

from dataclasses import asdict

from .center import detect_centers
from .divergence import detect_divergences
from .fractal import detect_fractals
from .kline import process_inclusion
from .macd import calculate_macd
from .models import KLine, Stroke
from .segment import detect_segments
from .signals import detect_buy_sell_points
from .stroke import detect_strokes
from .theory import detect_theory_marks
from .trend import classify_trend


def analyze_klines(klines: list[KLine]) -> dict:
    processed = process_inclusion(klines)
    fractals = detect_fractals(processed)
    strokes = detect_strokes(fractals)
    strokes = _append_pending_stroke(strokes, processed)
    segments = detect_segments(strokes)
    confirmed_segments = [segment for segment in segments if segment.status == "CONFIRMED"]
    centers = detect_centers(confirmed_segments)
    macd = calculate_macd(processed)
    divergences = detect_divergences(confirmed_segments, centers, macd)
    signals = detect_buy_sell_points(segments, centers, divergences, processed, strokes)
    theory_marks = detect_theory_marks(processed, segments, centers, divergences, signals, macd)
    trend = classify_trend(centers)

    return {
        "klines": [asdict(item) for item in processed],
        "fractals": [asdict(item) for item in fractals],
        "strokes": [asdict(item) for item in strokes],
        "segments": [asdict(item) for item in segments],
        "centers": [asdict(item) for item in centers],
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
            "divergence_count": len(divergences),
            "signal_count": len(signals),
            "theory_mark_count": len(theory_marks),
        },
    }


def _append_pending_stroke(strokes: list[Stroke], klines: list[KLine]) -> list[Stroke]:
    if not strokes or not klines:
        return strokes
    latest = klines[-1]
    last = strokes[-1]
    if latest.index <= last.end_index:
        return strokes

    min_amplitude_pct = 0.003
    if last.direction == "up" and latest.low < last.end_price:
        amplitude = (last.end_price - latest.low) / max(abs(last.end_price), 0.01)
        if amplitude < min_amplitude_pct:
            return strokes
        return [
            *strokes,
            Stroke(
                start_index=last.end_index,
                end_index=latest.index,
                start_time=last.end_time,
                end_time=latest.time,
                start_price=last.end_price,
                end_price=latest.low,
                direction="down",
                high=max(last.end_price, latest.high),
                low=min(last.end_price, latest.low),
            ),
        ]
    if last.direction == "down" and latest.high > last.end_price:
        amplitude = (latest.high - last.end_price) / max(abs(last.end_price), 0.01)
        if amplitude < min_amplitude_pct:
            return strokes
        return [
            *strokes,
            Stroke(
                start_index=last.end_index,
                end_index=latest.index,
                start_time=last.end_time,
                end_time=latest.time,
                start_price=last.end_price,
                end_price=latest.high,
                direction="up",
                high=max(last.end_price, latest.high),
                low=min(last.end_price, latest.low),
            ),
        ]
    return strokes
