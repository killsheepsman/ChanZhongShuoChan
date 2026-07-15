from __future__ import annotations

import unittest

from app.services.watch_assistant import build_watch_decision


def analysis(*, signals=None, trend_close=20.0, hist=-0.2, previous_hist=-0.3, divergences=None):
    klines = [
        {"index": index, "time": f"2026-07-{index + 1:02d}", "open": 10 + index / 3,
         "high": 11 + index / 3, "low": 9 + index / 3, "close": trend_close - (34 - index) * 0.1,
         "volume": 100 + index, "amount": 0}
        for index in range(35)
    ]
    return {
        "raw_klines": klines,
        "klines": klines,
        "segments": [{"direction": "down", "status": "IS_RUNNING"}],
        "centers": [{"zg": trend_close + 1}],
        "signals": signals or [],
        "divergences": divergences or [],
        "macd": [{"hist": previous_hist}, {"hist": hist}],
    }


class WatchAssistantTests(unittest.TestCase):
    def test_p0_allows_reduced_condition_order(self):
        daily = analysis(signals=[{"side": "buy", "type": 1, "status": "confirmed", "index": 30, "price": 18, "time": "d", "reason": "日线背驰"}])
        minute = analysis(signals=[{"side": "buy", "type": 2, "status": "confirmed", "index": 32, "price": 19, "time": "m", "reason": "二买回踩"}])
        result = build_watch_decision("603703", daily, minute)
        self.assertEqual(result["priority"], "P0")
        self.assertEqual(result["action"], "BUY")
        self.assertTrue(result["order_allowed"])
        self.assertEqual(result["position_percent"], 21)

    def test_no_signal_prohibits_order(self):
        result = build_watch_decision("603703", analysis(), analysis())
        self.assertEqual(result["priority"], "P4")
        self.assertFalse(result["order_allowed"])
        self.assertEqual(result["position_percent"], 0)

    def test_missing_level_prohibits_order(self):
        empty = {"raw_klines": [], "klines": [], "signals": [], "macd": []}
        result = build_watch_decision("603703", empty, analysis())
        self.assertEqual(result["action"], "NO_TRADE")
        self.assertIn("日线", result["conclusion"])


if __name__ == "__main__":
    unittest.main()
