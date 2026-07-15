from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.services import signal_store


class SignalStoreRangeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_path = signal_store.DB_PATH
        signal_store.DB_PATH = Path(self.temp_dir.name) / "signals.sqlite3"
        signal_store.init_signal_store()

    def tearDown(self) -> None:
        signal_store.DB_PATH = self.original_path
        self.temp_dir.cleanup()

    def test_query_matches_inclusive_date_range_descending_by_date(self) -> None:
        signals = [
            {"side": "buy", "type": 1, "time": "2026-07-01 10:00:00", "price": 10.0, "status": "confirmed", "confidence": 0.7},
            {"side": "buy", "type": 1, "time": "2026-07-03 10:00:00", "price": 11.0, "status": "confirmed", "confidence": 0.8},
            {"side": "buy", "type": 1, "time": "2026-07-05 10:00:00", "price": 12.0, "status": "confirmed", "confidence": 0.9},
        ]
        signal_store.upsert_stock_signals(
            symbol="603703", name="盛洋科技", period="5", adjust="qfq",
            start_date="20260701", end_date="20260705", source="test",
            last_kline_time="2026-07-05 15:00:00", signals=signals, updated_at="2026-07-05 16:00:00",
        )

        matches = signal_store.query_signal_matches(
            start_signal_date="20260702", end_signal_date="20260705", period="5", adjust="qfq",
            side="buy", signal_type=1, max_results=20,
        )

        self.assertEqual([item["time"] for item in matches], ["2026-07-05 10:00:00", "2026-07-03 10:00:00"])


if __name__ == "__main__":
    unittest.main()
