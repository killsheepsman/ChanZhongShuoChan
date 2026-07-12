from __future__ import annotations

import unittest

from app.chanlun.models import KLine
from app.services.stock_data import filter_klines_to_range


def _kline(index: int, time: str) -> KLine:
    return KLine(
        index=index,
        time=time,
        open=10.0,
        high=10.5,
        low=9.5,
        close=10.2,
    )


class StockDataRangeTests(unittest.TestCase):
    def test_minute_klines_are_clipped_to_the_inclusive_request_range(self) -> None:
        source = [
            _kline(8, "2026-06-26 14:55:00"),
            _kline(10, "2026-06-27 09:35:00"),
            _kline(11, "2026-06-30 15:00:00"),
            _kline(13, "2026-07-01 09:35:00"),
        ]

        clipped = filter_klines_to_range(source, "20260627", "20260630")

        self.assertEqual([item.time for item in clipped], ["2026-06-27 09:35:00", "2026-06-30 15:00:00"])
        self.assertEqual([item.index for item in clipped], [0, 1])

    def test_range_filter_sorts_source_rows_before_reindexing(self) -> None:
        source = [
            _kline(7, "2026-06-30 15:00:00"),
            _kline(3, "2026-06-27 09:35:00"),
        ]

        clipped = filter_klines_to_range(source, "2026-06-27", "2026-06-30")

        self.assertEqual([item.time for item in clipped], ["2026-06-27 09:35:00", "2026-06-30 15:00:00"])
        self.assertEqual([item.index for item in clipped], [0, 1])

    def test_end_date_is_inclusive_for_the_last_minute_bar(self) -> None:
        source = [
            _kline(0, "2026-06-30 15:00:00"),
            _kline(1, "2026-07-01 09:35:00"),
        ]

        clipped = filter_klines_to_range(source, "20260630", "20260630")

        self.assertEqual([item.time for item in clipped], ["2026-06-30 15:00:00"])


if __name__ == "__main__":
    unittest.main()
