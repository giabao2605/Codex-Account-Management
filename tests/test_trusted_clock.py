import tempfile
import threading
import unittest
from email.utils import formatdate
from pathlib import Path

from app.local_web_service import LocalWebService
from app.trusted_clock import TrustedClock


class _ClockSource:
    def __init__(self, wall: float = 1_000.0, monotonic: float = 10.0):
        self.wall = wall
        self.monotonic = monotonic

    def wall_time(self) -> float:
        return self.wall

    def monotonic_time(self) -> float:
        return self.monotonic


class _Response:
    def __init__(self, epoch: float | None, final_url: str = "https://source"):
        self.headers = (
            {"Date": formatdate(epoch, usegmt=True)}
            if epoch is not None
            else {}
        )
        self.final_url = final_url

    def geturl(self) -> str:
        return self.final_url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class TrustedClockTests(unittest.TestCase):
    def test_sync_uses_median_and_rejects_outlier(self) -> None:
        source = _ClockSource()
        dates = iter((1_120.0, 1_122.0, 6_000.0))
        clock = TrustedClock(
            sources=("https://one", "https://two", "https://three"),
            wall_time=source.wall_time,
            monotonic=source.monotonic_time,
            opener=lambda request, timeout: _Response(next(dates)),
        )

        self.assertTrue(clock.sync())
        self.assertAlmostEqual(clock.now(), 1_121.0)
        self.assertEqual(clock.status()["status"], "synced")
        self.assertEqual(clock.status()["source_count"], 2)
        self.assertAlmostEqual(clock.status()["offset_seconds"], 121.0)

    def test_monotonic_anchor_ignores_later_wall_clock_jump(self) -> None:
        source = _ClockSource()
        dates = iter((1_120.0, 1_120.0, 1_120.0))
        clock = TrustedClock(
            sources=("https://one", "https://two", "https://three"),
            wall_time=source.wall_time,
            monotonic=source.monotonic_time,
            opener=lambda request, timeout: _Response(next(dates)),
        )
        clock.sync()

        source.wall += 500.0
        source.monotonic += 7.0

        self.assertAlmostEqual(clock.now(), 1_127.0)

    def test_failed_refresh_keeps_last_good_anchor(self) -> None:
        source = _ClockSource()
        dates = iter((1_120.0, 1_120.0, 1_120.0))
        clock = TrustedClock(
            sources=("https://one", "https://two", "https://three"),
            wall_time=source.wall_time,
            monotonic=source.monotonic_time,
            opener=lambda request, timeout: _Response(next(dates)),
        )
        self.assertTrue(clock.sync())
        source.monotonic += 3.0

        def fail(request, timeout):
            raise OSError("offline")

        clock._opener = fail
        self.assertFalse(clock.sync())

        self.assertAlmostEqual(clock.now(), 1_123.0)
        self.assertEqual(clock.status()["status"], "degraded")
        self.assertEqual(clock.status()["source_count"], 0)
        self.assertIsNotNone(clock.status()["last_synced_at"])

    def test_rejects_non_https_sources(self) -> None:
        with self.assertRaises(ValueError):
            TrustedClock(sources=("http://not-trusted",))

    def test_rejects_source_redirected_to_plain_http(self) -> None:
        source = _ClockSource()
        clock = TrustedClock(
            sources=("https://trusted",),
            wall_time=source.wall_time,
            monotonic=source.monotonic_time,
            opener=lambda request, timeout: _Response(
                1_120.0,
                final_url="http://downgraded",
            ),
        )

        self.assertFalse(clock.sync())
        self.assertIsNone(clock.status()["last_synced_at"])

    def test_start_performs_initial_sync(self) -> None:
        completed = threading.Event()

        def open_date(request, timeout):
            completed.set()
            return _Response(1_120.0)

        clock = TrustedClock(
            sources=("https://one",),
            opener=open_date,
            refresh_interval_seconds=3_600,
            maximum_offset_seconds=2_000_000_000,
        )
        clock.start()
        try:
            self.assertTrue(completed.wait(timeout=1))
        finally:
            clock.close()

    def test_start_waits_for_initial_sync_before_returning(self) -> None:
        opened = threading.Event()
        release = threading.Event()
        returned = threading.Event()

        def open_date(request, timeout):
            opened.set()
            release.wait(timeout=1)
            return _Response(1_120.0)

        clock = TrustedClock(
            sources=("https://one",),
            opener=open_date,
            refresh_interval_seconds=3_600,
            maximum_offset_seconds=2_000_000_000,
        )
        starter = threading.Thread(
            target=lambda: (clock.start(), returned.set())
        )
        starter.start()
        try:
            self.assertTrue(opened.wait(timeout=1))
            self.assertFalse(returned.is_set())
            release.set()
            self.assertTrue(returned.wait(timeout=1))
            self.assertIsNotNone(clock.status()["last_synced_at"])
        finally:
            release.set()
            starter.join(timeout=1)
            clock.close()

    def test_single_source_is_usable_but_marked_degraded(self) -> None:
        source = _ClockSource()
        clock = TrustedClock(
            sources=("https://one",),
            wall_time=source.wall_time,
            monotonic=source.monotonic_time,
            opener=lambda request, timeout: _Response(1_120.0),
        )

        self.assertTrue(clock.sync())
        self.assertAlmostEqual(clock.now(), 1_120.0)
        self.assertEqual(clock.status()["status"], "degraded")
        self.assertEqual(clock.status()["source_count"], 1)

    def test_rejects_slow_source_using_monotonic_rtt(self) -> None:
        source = _ClockSource()

        def slow_open(request, timeout):
            source.wall += 3.0
            source.monotonic += 3.0
            return _Response(1_123.0)

        clock = TrustedClock(
            sources=("https://slow",),
            wall_time=source.wall_time,
            monotonic=source.monotonic_time,
            opener=slow_open,
            maximum_rtt_seconds=2.0,
        )

        self.assertFalse(clock.sync())
        self.assertEqual(clock.status()["status"], "degraded")

    def test_rejects_sample_when_system_clock_changes_during_request(self) -> None:
        source = _ClockSource()

        def jumping_open(request, timeout):
            source.wall += 240.0
            source.monotonic += 0.1
            return _Response(1_000.0)

        clock = TrustedClock(
            sources=("https://jump",),
            wall_time=source.wall_time,
            monotonic=source.monotonic_time,
            opener=jumping_open,
        )

        self.assertFalse(clock.sync())


class _FakeTrustedClock:
    def __init__(self, epoch: float):
        self.epoch = epoch
        self.started = False
        self.closed = False

    def start(self) -> None:
        self.started = True

    def close(self) -> None:
        self.closed = True

    def now(self) -> float:
        return self.epoch

    def status(self) -> dict:
        return {
            "status": "synced",
            "offset_seconds": 120.0,
            "last_synced_at": "2026-07-22T10:00:00+00:00",
            "source_count": 3,
        }


class _UnsyncedTrustedClock(_FakeTrustedClock):
    def status(self) -> dict:
        return {
            "status": "degraded",
            "offset_seconds": None,
            "last_synced_at": None,
            "source_count": 0,
        }


class TrustedClockServiceTests(unittest.TestCase):
    def test_service_uses_same_epoch_for_totp_and_countdown(self) -> None:
        fake_clock = _FakeTrustedClock(1_000.0)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = LocalWebService(
                data_file=root / "accounts.json",
                profiles_dir=root / "profiles",
                enable_codex=False,
                trusted_clock=fake_clock,
            )
            service.start()
            try:
                service.import_accounts(
                    "user@example.com|password|JBSWY3DPEHPK3PXP"
                )
                state = service.state()
                account = service._accounts[0]
                row = state["accounts"][0]

                self.assertEqual(row["otp"], account.totp.at(1_000))
                self.assertEqual(row["otp_remaining_seconds"], 20)
                self.assertEqual(state["time_sync"], fake_clock.status())
                self.assertTrue(fake_clock.started)
            finally:
                service.close()
            self.assertTrue(fake_clock.closed)

    def test_service_withholds_otp_until_first_trusted_sync(self) -> None:
        fake_clock = _UnsyncedTrustedClock(1_000.0)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = LocalWebService(
                data_file=root / "accounts.json",
                profiles_dir=root / "profiles",
                enable_codex=False,
                trusted_clock=fake_clock,
            )
            service.start()
            try:
                service.import_accounts(
                    "user@example.com|password|JBSWY3DPEHPK3PXP"
                )
                row = service.state()["accounts"][0]

                self.assertIsNone(row["otp"])
                self.assertIsNone(row["otp_remaining_seconds"])
            finally:
                service.close()


if __name__ == "__main__":
    unittest.main()
