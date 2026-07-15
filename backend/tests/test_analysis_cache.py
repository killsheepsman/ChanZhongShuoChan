from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.chanlun import analyze_klines
from app.chanlun.analyzer import continue_analysis
from app.chanlun.models import KLine
from app.services import analysis_cache


class AnalysisCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_path = analysis_cache.DB_PATH
        analysis_cache.DB_PATH = Path(self.temp_dir.name) / "analysis_cache.sqlite3"

    def tearDown(self) -> None:
        analysis_cache.DB_PATH = self.original_path
        self.temp_dir.cleanup()

    def test_incremental_result_matches_full_rebuild(self) -> None:
        raw = self._fixture_klines()
        rebuilt = analyze_klines(raw)
        for split in (50, 100, 200, 300, 400, 500, 600, 700, 800):
            cached = analyze_klines(raw[:split])
            incremental, metadata = continue_analysis(cached, raw)

            self.assertEqual(metadata["mode"], "incremental")
            self.assertEqual(metadata["new_kline_count"], len(raw) - split)
            for key in ("klines", "fractals", "strokes", "segments", "centers", "center_expansions", "signals", "macd"):
                self.assertEqual(incremental[key], rebuilt[key], f"{key} at split {split}")

    def test_multiple_incremental_batches_match_full_rebuild(self) -> None:
        raw = self._fixture_klines()
        result = analyze_klines(raw[:100])
        for end in (250, 500, 700, len(raw)):
            result, metadata = continue_analysis(result, raw[:end])
            self.assertEqual(metadata["mode"], "incremental")

        rebuilt = analyze_klines(raw)
        for key in ("klines", "fractals", "strokes", "segments", "centers", "center_expansions", "signals", "macd"):
            self.assertEqual(result[key], rebuilt[key], key)

    def test_persistent_cache_rebuild_hit_and_incremental_modes(self) -> None:
        raw = self._fixture_klines()
        first = analysis_cache.analyze_with_cache(
            symbol="603703", period="5", adjust="qfq", start_date="20260617", end_date="20260707", klines=raw[:600]
        )
        second = analysis_cache.analyze_with_cache(
            symbol="603703", period="5", adjust="qfq", start_date="20260617", end_date="20260707", klines=raw[:600]
        )
        third = analysis_cache.analyze_with_cache(
            symbol="603703", period="5", adjust="qfq", start_date="20260617", end_date="20260710", klines=raw
        )

        self.assertEqual(first["analysis_cache"]["mode"], "rebuild")
        self.assertEqual(second["analysis_cache"]["mode"], "hit")
        self.assertEqual(third["analysis_cache"]["mode"], "incremental")
        self.assertEqual(third["analysis_cache"]["new_kline_count"], len(raw) - 600)
        self.assertEqual(third["segments"], analyze_klines(raw)["segments"])

    @staticmethod
    def _fixture_klines() -> list[KLine]:
        fixture = Path(__file__).resolve().parents[2] / "analysis" / "fixtures" / "603703_5m_20260617_20260710_baseline.json"
        payload = json.loads(fixture.read_text(encoding="utf-8"))
        return [KLine(**item) for item in payload["raw_klines"]]


if __name__ == "__main__":
    unittest.main()
