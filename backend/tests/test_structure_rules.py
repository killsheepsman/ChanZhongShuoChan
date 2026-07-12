from __future__ import annotations

import json
import unittest
from pathlib import Path

from app.chanlun import analyze_klines
from app.chanlun.center import detect_centers
from app.chanlun.fractal import _dedupe_alternating
from app.chanlun.models import Fractal, KLine, Segment, Stroke
from app.chanlun.segment import detect_segments
from app.chanlun.stroke import detect_strokes


def _fractal(index: int, kind: str, price: float) -> Fractal:
    return Fractal(index=index, time=str(index), kind=kind, price=price, high=price, low=price)


def _stroke(index: int, start: float, end: float) -> Stroke:
    return Stroke(
        start_index=index,
        end_index=index + 1,
        start_time=str(index),
        end_time=str(index + 1),
        start_price=start,
        end_price=end,
        direction="up" if end > start else "down",
        high=max(start, end),
        low=min(start, end),
    )


class StructureRuleTests(unittest.TestCase):
    def test_fractals_leave_an_independent_kline_gap(self) -> None:
        fractals = [
            _fractal(1, "top", 12),
            _fractal(3, "bottom", 9),
            _fractal(5, "bottom", 8),
        ]

        accepted = _dedupe_alternating(fractals, min_gap=1)

        self.assertEqual([item.index for item in accepted], [1, 5])

    def test_strokes_cover_at_least_five_processed_klines(self) -> None:
        strokes = detect_strokes(
            [
                _fractal(0, "bottom", 10),
                _fractal(4, "top", 12),
                _fractal(8, "bottom", 9),
            ]
        )

        self.assertEqual(len(strokes), 2)
        self.assertTrue(all(stroke.end_index - stroke.start_index >= 4 for stroke in strokes))

    def test_reverse_overlap_does_not_confirm_without_boundary_break(self) -> None:
        strokes = [
            _stroke(0, 10, 12),
            _stroke(1, 12, 11),
            _stroke(2, 11, 13),
            _stroke(3, 13, 11.5),
            _stroke(4, 11.5, 12.5),
            _stroke(5, 12.5, 11.4),
        ]

        segments = detect_segments(strokes)

        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].status, "IS_RUNNING")

    def test_reverse_overlap_confirms_only_after_boundary_break(self) -> None:
        strokes = [
            _stroke(0, 10, 12),
            _stroke(1, 12, 11),
            _stroke(2, 11, 13),
            _stroke(3, 13, 11.5),
            _stroke(4, 11.5, 12.5),
            _stroke(5, 12.5, 11.4),
            _stroke(6, 11.4, 12.4),
            _stroke(7, 12.4, 9.8),
        ]

        segments = detect_segments(strokes)

        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0].status, "CONFIRMED")
        self.assertEqual(segments[1].status, "IS_RUNNING")
        self.assertEqual(segments[1].start_index, segments[0].end_index)
        self.assertEqual(segments[1].start_price, segments[0].end_price)

    def test_segment_records_actual_reverse_evidence_before_confirmation(self) -> None:
        strokes = [
            _stroke(0, 10, 12),
            _stroke(1, 12, 11),
            _stroke(2, 11, 13),
            _stroke(3, 13, 11.5),
            _stroke(4, 11.5, 12.5),
            _stroke(5, 12.5, 11.4),
            _stroke(6, 11.4, 12.4),
            _stroke(7, 12.4, 9.8),
        ]

        segments = detect_segments(strokes)

        self.assertEqual(len(segments), 2)
        confirmed, running = segments
        self.assertEqual(confirmed.stroke_ids, [0, 1, 2, 3, 4])
        self.assertEqual((confirmed.high, confirmed.low), (13, 10))
        self.assertEqual(confirmed.evidence.formation_stroke_ids, [0, 1, 2])
        self.assertEqual(confirmed.evidence.candidate_stroke_ids, [5, 6, 7])
        self.assertEqual((confirmed.evidence.candidate_zd, confirmed.evidence.candidate_zg), (11.4, 12.4))
        self.assertEqual((confirmed.evidence.guard_side, confirmed.evidence.guard_price), ("low", 10))
        self.assertEqual(confirmed.evidence.candidate_extreme, 9.8)
        self.assertEqual((confirmed.evidence.break_stroke_id, confirmed.evidence.break_time), (7, "8"))
        self.assertEqual(running.start_index, confirmed.end_index)
        self.assertEqual(running.start_time, confirmed.end_time)
        self.assertEqual(running.start_price, confirmed.end_price)

    def test_603703_five_minute_fixture_preserves_structure_invariants(self) -> None:
        fixture = Path(__file__).resolve().parents[2] / "analysis" / "fixtures" / "603703_5m_20260617_20260710_baseline.json"
        payload = json.loads(fixture.read_text(encoding="utf-8"))
        raw_klines = [KLine(**item) for item in payload["raw_klines"]]

        result = analyze_klines(raw_klines)
        segments = result["segments"]
        confirmed = [segment for segment in segments if segment["status"] == "CONFIRMED"]
        running = [segment for segment in segments if segment["status"] == "IS_RUNNING"]

        self.assertEqual(len(raw_klines), 816)
        self.assertEqual(raw_klines[0].time, "2026-06-17 09:35:00")
        self.assertEqual(raw_klines[-1].time, "2026-07-10 15:00:00")
        self.assertEqual(len(running), 1)
        self.assertEqual(segments[-1]["status"], "IS_RUNNING")
        for segment in confirmed:
            evidence = segment["evidence"]
            self.assertIsNotNone(evidence)
            self.assertEqual(len(evidence["formation_stroke_ids"]), 3)
            self.assertIsNotNone(evidence["formation_zd"])
            self.assertIsNotNone(evidence["formation_zg"])
            self.assertIsNotNone(evidence["break_stroke_id"])
            self.assertIsNotNone(evidence["break_time"])
        for previous, current in zip(segments, segments[1:]):
            self.assertEqual(previous["status"], "CONFIRMED")
            self.assertEqual(current["start_index"], previous["end_index"])
            self.assertEqual(current["start_time"], previous["end_time"])
            self.assertEqual(current["start_price"], previous["end_price"])
        if not confirmed:
            self.assertEqual(result["centers"], [])
            self.assertEqual(result["divergences"], [])
            self.assertFalse(any(signal["status"] == "confirmed" for signal in result["signals"]))

    def test_center_uses_confirmed_segment_ranges(self) -> None:
        segments = [
            Segment(0, 0, 2, "0", "2", 10, 13, "up", 13, 10, [0]),
            Segment(1, 2, 4, "2", "4", 13, 11, "down", 13, 11, [1]),
            Segment(2, 4, 6, "4", "6", 11, 12, "up", 12, 11, [2]),
            Segment(3, 6, 8, "6", "8", 12, 11.5, "down", 12, 11.5, [3]),
        ]

        centers = detect_centers(segments)

        self.assertEqual(len(centers), 1)
        self.assertEqual(centers[0].segment_ids, [0, 1, 2, 3])
        self.assertEqual((centers[0].zd, centers[0].zg), (11, 12))


if __name__ == "__main__":
    unittest.main()
