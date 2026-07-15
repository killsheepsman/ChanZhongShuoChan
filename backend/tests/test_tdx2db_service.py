from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from app.chanlun.models import KLine
from app.services import tdx2db_service


class ImmediateThread:
    def __init__(self, *, target, args, daemon: bool) -> None:
        self.target = target
        self.args = args
        self.daemon = daemon

    def start(self) -> None:
        self.target(*self.args)


class CompletedProcess:
    def poll(self):
        return 0

    def wait(self) -> int:
        return 0


class Tdx2DbServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.original_paths = {
            "DATA_DIR": tdx2db_service.DATA_DIR,
            "CONFIG_PATH": tdx2db_service.CONFIG_PATH,
            "TDX_DB_PATH": tdx2db_service.TDX_DB_PATH,
            "LOG_PATH": tdx2db_service.LOG_PATH,
        }
        tdx2db_service.DATA_DIR = root / "data"
        tdx2db_service.CONFIG_PATH = tdx2db_service.DATA_DIR / "tdx2db_config.json"
        tdx2db_service.TDX_DB_PATH = tdx2db_service.DATA_DIR / "chanlun_tdx.db"
        tdx2db_service.LOG_PATH = root / "logs" / "tdx2db-sync.log"
        tdx2db_service._SYNC_PROCESS = None
        tdx2db_service._SYNC_THREAD = None
        tdx2db_service._SYNC_CANCEL_EVENT.clear()
        tdx2db_service._SYNC_STATE.update(
            {"status": "idle", "message": "test", "started_at": None, "finished_at": None, "exit_code": None}
        )
        tdx2db_service.init_tdx2db_paths()
        self._create_database()

    def tearDown(self) -> None:
        for name, value in self.original_paths.items():
            setattr(tdx2db_service, name, value)
        tdx2db_service._SYNC_PROCESS = None
        tdx2db_service._SYNC_THREAD = None
        tdx2db_service._SYNC_CANCEL_EVENT.clear()
        self.temp_dir.cleanup()

    def _create_database(self) -> None:
        conn = sqlite3.connect(tdx2db_service.TDX_DB_PATH)
        try:
            conn.executescript(
                """
                CREATE TABLE daily_data (
                    code TEXT, date TEXT, open REAL, high REAL, low REAL, close REAL, volume REAL, amount REAL
                );
                CREATE TABLE minute5_data (
                    id INTEGER PRIMARY KEY,
                    code TEXT NOT NULL,
                    market INTEGER NOT NULL,
                    datetime TEXT NOT NULL,
                    date TEXT NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    amount REAL NOT NULL,
                    UNIQUE(code, datetime)
                );
                CREATE TABLE stock_info (code TEXT, name TEXT);
                """
            )
            conn.executemany(
                "INSERT INTO daily_data VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    ("603703", "2026-07-09 00:00:00", 10, 11, 9, 10.5, 1000, 10000),
                    ("603703", "2026-07-10 00:00:00", 10.5, 11.5, 10, 11, 1200, 13000),
                ],
            )
            conn.executemany(
                "INSERT INTO minute5_data (code, market, datetime, date, open, high, low, close, volume, amount) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    ("603703", 1, "2026-07-10 09:35:00", "2026-07-10", 10, 10.2, 9.9, 10.1, 100, 1000),
                    ("603703", 1, "2026-07-10 09:40:00", "2026-07-10", 10.1, 10.3, 10, 10.2, 120, 1200),
                ],
            )
            conn.executemany(
                "INSERT INTO stock_info VALUES (?, ?)",
                [("sh603703", "Shengyang"), ("sz000001", "Ping An")],
            )
            conn.commit()
        finally:
            conn.close()

    def test_reads_daily_and_minute_data_in_requested_range(self) -> None:
        daily = tdx2db_service.load_tdx2db_klines("603703", "daily", "20260709", "20260710")
        minute = tdx2db_service.load_tdx2db_klines("603703", "5", "20260710", "20260710")

        self.assertEqual([item.time for item in daily], ["2026-07-09 00:00:00", "2026-07-10 00:00:00"])
        self.assertEqual([item.index for item in minute], [0, 1])
        self.assertEqual([item.time for item in minute], ["2026-07-10 09:35:00", "2026-07-10 09:40:00"])
        self.assertEqual(tdx2db_service.load_tdx2db_klines("603703", "1", "20260710", "20260710"), [])

    def test_backfill_upsert_adds_older_rows_and_replaces_duplicate_times(self) -> None:
        written = tdx2db_service._upsert_minute5_rows(
            [
                ("603703", 1, "2024-09-03 09:35:00", "2024-09-03", 9.2, 9.38, 9.19, 9.36, 406300, 3775623),
                ("603703", 1, "2026-07-10 09:35:00", "2026-07-10", 10, 10.4, 9.8, 10.3, 999, 9999),
            ]
        )

        self.assertEqual(written, 2)
        conn = sqlite3.connect(tdx2db_service.TDX_DB_PATH)
        try:
            rows = conn.execute(
                "SELECT datetime, close, volume FROM minute5_data WHERE code = ? ORDER BY datetime",
                ("603703",),
            ).fetchall()
        finally:
            conn.close()
        self.assertEqual(rows[0], ("2024-09-03 09:35:00", 9.36, 406300.0))
        self.assertEqual(rows[-1], ("2026-07-10 09:40:00", 10.2, 120.0))
        self.assertEqual(rows[1], ("2026-07-10 09:35:00", 10.3, 999.0))

    def test_session_resampling_never_crosses_the_lunch_break(self) -> None:
        morning = [datetime(2026, 7, 10, 9, 35) + timedelta(minutes=5 * index) for index in range(24)]
        afternoon = [datetime(2026, 7, 10, 13, 5) + timedelta(minutes=5 * index) for index in range(24)]
        raw = [
            KLine(
                index=index,
                time=stamp.strftime("%Y-%m-%d %H:%M:%S"),
                open=10 + index,
                high=10.5 + index,
                low=9.5 + index,
                close=10.2 + index,
                volume=1,
                amount=10,
            )
            for index, stamp in enumerate(morning + afternoon)
        ]

        bars = tdx2db_service._resample_session_klines(raw, 6)

        self.assertEqual(len(bars), 8)
        self.assertEqual([bar.time for bar in bars[:5]], [
            "2026-07-10 10:00:00",
            "2026-07-10 10:30:00",
            "2026-07-10 11:00:00",
            "2026-07-10 11:30:00",
            "2026-07-10 13:30:00",
        ])
        self.assertEqual([bar.volume for bar in bars], [6] * 8)
        self.assertEqual(bars[3].close, raw[23].close)
        self.assertEqual(bars[4].open, raw[24].open)

    def test_stock_names_accept_tdx_exchange_prefixes(self) -> None:
        self.assertEqual(tdx2db_service.load_tdx2db_stock_name("603703"), "Shengyang")
        self.assertEqual(
            tdx2db_service.load_tdx2db_stocks(),
            [("000001", "Ping An"), ("603703", "Shengyang")],
        )

    def test_sync_uses_incremental_sqlite_command(self) -> None:
        tdx_path = Path(self.temp_dir.name) / "new_tdx64"
        (tdx_path / "vipdoc").mkdir(parents=True)
        tdx2db_service.configure_tdx2db(str(tdx_path))
        calls: list[tuple[list[str], dict]] = []

        def fake_popen(command, **kwargs):
            calls.append((command, kwargs))
            return CompletedProcess()

        with patch("app.services.tdx2db_service._tdx2db_executable", return_value="tdx2db.exe"), patch(
            "app.services.tdx2db_service.subprocess.Popen", side_effect=fake_popen
        ), patch("app.services.tdx2db_service.threading.Thread", ImmediateThread):
            status = tdx2db_service.start_tdx2db_sync()

        self.assertEqual(len(calls), 1)
        command, kwargs = calls[0]
        self.assertEqual(
            command,
            [
                "tdx2db.exe", "--tdx-path", str(tdx_path), "--db-type", "sqlite",
                "--db-name", "chanlun_tdx", "--no-tqdm", "sync",
            ],
        )
        self.assertEqual(kwargs["cwd"], str(tdx2db_service.DATA_DIR))
        self.assertEqual(status["sync"]["status"], "completed")


if __name__ == "__main__":
    unittest.main()
