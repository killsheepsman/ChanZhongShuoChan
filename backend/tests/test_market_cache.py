from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.chanlun.models import KLine
from app.services import market_cache, stock_data


def kline(index: int, time: str, close: float = 10.2) -> KLine:
    return KLine(
        index=index,
        time=time,
        open=10.0,
        high=10.5,
        low=9.5,
        close=close,
        volume=1000.0 + index,
        amount=10000.0 + index,
    )


class MarketCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_path = market_cache.DB_PATH
        market_cache.DB_PATH = Path(self.temp_dir.name) / "market_cache.sqlite3"
        market_cache.init_market_cache()

    def tearDown(self) -> None:
        market_cache.DB_PATH = self.original_path
        self.temp_dir.cleanup()

    def test_upsert_loads_sorted_range_and_replaces_duplicate_time(self) -> None:
        market_cache.upsert_cached_klines(
            symbol="600000",
            period="5",
            adjust="qfq",
            klines=[
                kline(2, "2026-07-02 09:35:00", 10.4),
                kline(1, "2026-07-01 09:35:00", 10.2),
            ],
            source="test-source",
            requested_start="20260701",
            requested_end="20260702",
        )
        market_cache.upsert_cached_klines(
            symbol="600000",
            period="5",
            adjust="qfq",
            klines=[kline(9, "2026-07-01 09:35:00", 11.1)],
            source="test-source-update",
            requested_start="20260701",
            requested_end="20260702",
        )

        loaded = market_cache.load_cached_klines("600000", "5", "qfq", "20260701", "20260701")
        self.assertEqual([item.time for item in loaded], ["2026-07-01 09:35:00"])
        self.assertEqual([item.index for item in loaded], [0])
        self.assertEqual(loaded[0].close, 11.1)
        self.assertEqual(loaded[0].volume, 1009.0)

        state = market_cache.get_cache_state("600000", "5", "qfq")
        self.assertEqual(state["first_kline_time"], "2026-07-01 09:35:00")
        self.assertEqual(state["last_kline_time"], "2026-07-02 09:35:00")


    def test_cache_aware_loader_reuses_saved_range_without_a_second_network_call(self) -> None:
        remote = stock_data.KLineFetchResult(
            [kline(0, "2026-07-01 09:35:00")],
            "test-source",
            True,
            "remote success",
            "2026-07-01 09:35:00",
            "2026-07-01 09:35:00",
        )
        with patch("app.services.stock_data.load_tdx2db_klines", return_value=[]), patch("app.services.stock_data.fetch_akshare_klines", return_value=remote) as fetch:
            first = stock_data.fetch_cached_or_akshare_klines("000001", "5", "20260701", "20260701", "qfq", allow_external=True)
            self.assertTrue(first.ok)
            self.assertTrue(first.cache_updated)
            self.assertEqual(fetch.call_count, 1)

        with patch("app.services.stock_data.load_tdx2db_klines", return_value=[]), patch("app.services.stock_data.fetch_akshare_klines", side_effect=AssertionError("network should not be called")):
            second = stock_data.fetch_cached_or_akshare_klines("000001", "5", "20260701", "20260701", "qfq")
        self.assertTrue(second.ok)
        self.assertTrue(second.from_cache)
        self.assertEqual(second.source, "local-cache")
        self.assertEqual([item.time for item in second.klines], ["2026-07-01 09:35:00"])

    def test_local_only_mode_never_requests_an_external_provider(self) -> None:
        with patch("app.services.stock_data.load_tdx2db_klines", return_value=[]), patch(
            "app.services.stock_data.fetch_akshare_klines", side_effect=AssertionError("network should not be called")
        ):
            result = stock_data.fetch_cached_or_akshare_klines(
                "603703", "5", "20260701", "20260701", "qfq", allow_external=False
            )

        self.assertFalse(result.ok)
        self.assertEqual(result.source, "local-only")
        self.assertEqual(result.klines, [])


if __name__ == "__main__":
    unittest.main()
