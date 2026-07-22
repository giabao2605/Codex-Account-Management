from __future__ import annotations

import os
import statistics
import threading
import time
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Callable, Mapping, Protocol
from urllib.parse import urlsplit


DEFAULT_TIME_SOURCES = (
    "https://www.cloudflare.com/",
    "https://www.google.com/",
    "https://www.microsoft.com/",
)
TIME_SOURCES_ENV = "OTP_TIME_SOURCES"


class _Response(Protocol):
    headers: Mapping[str, str]

    def geturl(self) -> str: ...

    def __enter__(self) -> "_Response": ...

    def __exit__(self, exc_type, exc_value, traceback) -> bool: ...


OpenUrl = Callable[..., _Response]


def configured_time_sources() -> tuple[str, ...]:
    raw_sources = os.environ.get(TIME_SOURCES_ENV, "")
    if not raw_sources.strip():
        return DEFAULT_TIME_SOURCES
    sources = tuple(
        value.strip()
        for value in raw_sources.split(",")
        if value.strip()
    )
    return sources or DEFAULT_TIME_SOURCES


class TrustedClock:
    """HTTPS-synchronized wall clock anchored to a monotonic timer."""

    def __init__(
        self,
        *,
        sources: tuple[str, ...] | None = None,
        timeout_seconds: float = 2.0,
        refresh_interval_seconds: float = 300.0,
        maximum_rtt_seconds: float = 2.0,
        maximum_offset_seconds: float = 86_400.0,
        wall_time: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
        opener: OpenUrl = urllib.request.urlopen,
    ) -> None:
        selected_sources = sources or configured_time_sources()
        if not selected_sources:
            raise ValueError("At least one HTTPS time source is required.")
        if any(
            urlsplit(source).scheme.casefold() != "https"
            or not urlsplit(source).netloc
            or urlsplit(source).username is not None
            or urlsplit(source).password is not None
            for source in selected_sources
        ):
            raise ValueError("Time sources must be HTTPS URLs without credentials.")
        if (
            timeout_seconds <= 0
            or refresh_interval_seconds <= 0
            or maximum_rtt_seconds <= 0
            or maximum_offset_seconds <= 0
        ):
            raise ValueError("Clock timeouts and refresh intervals must be positive.")

        self.sources = tuple(selected_sources)
        self.timeout_seconds = timeout_seconds
        self.refresh_interval_seconds = refresh_interval_seconds
        self.maximum_rtt_seconds = maximum_rtt_seconds
        self.maximum_offset_seconds = maximum_offset_seconds
        self._wall_time = wall_time
        self._monotonic = monotonic
        self._opener = opener
        self._lock = threading.RLock()
        self._sync_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._initial_sync_complete = threading.Event()
        self._worker: threading.Thread | None = None
        self._anchor_epoch: float | None = None
        self._anchor_monotonic: float | None = None
        self._offset_seconds: float | None = None
        self._last_synced_at: str | None = None
        self._source_count = 0
        self._status = "syncing"

    def start(self) -> None:
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                worker = self._worker
            else:
                self._stop_event.clear()
                self._initial_sync_complete.clear()
                worker = threading.Thread(
                    target=self._run,
                    name="trusted-clock-sync",
                    daemon=True,
                )
                self._worker = worker
                worker.start()
        self._initial_sync_complete.wait(
            timeout=(self.timeout_seconds * len(self.sources)) + 0.5
        )

    def close(self) -> None:
        self._stop_event.set()
        with self._lock:
            worker = self._worker
            self._worker = None
        if worker is not None and worker is not threading.current_thread():
            worker.join(
                timeout=(self.timeout_seconds * len(self.sources)) + 0.5
            )

    def now(self) -> float:
        with self._lock:
            anchor_epoch = self._anchor_epoch
            anchor_monotonic = self._anchor_monotonic
        if anchor_epoch is None or anchor_monotonic is None:
            return self._wall_time()
        return anchor_epoch + (self._monotonic() - anchor_monotonic)

    def status(self) -> dict[str, str | float | int | None]:
        with self._lock:
            return {
                "status": self._status,
                "offset_seconds": self._offset_seconds,
                "last_synced_at": self._last_synced_at,
                "source_count": self._source_count,
            }

    def sync(self) -> bool:
        if not self._sync_lock.acquire(blocking=False):
            return False
        try:
            with self._lock:
                if self._anchor_epoch is None:
                    self._status = "syncing"
            offsets = [
                sample
                for source in self.sources
                if (sample := self._sample_offset(source)) is not None
            ]
            accepted = self._without_outliers(offsets)
            if not accepted:
                with self._lock:
                    self._status = "degraded"
                    self._source_count = 0
                return False

            offset = statistics.median(accepted)
            anchor_monotonic = self._monotonic()
            anchor_epoch = self._wall_time() + offset
            last_synced_at = datetime.fromtimestamp(
                anchor_epoch,
                tz=timezone.utc,
            ).isoformat(timespec="seconds")
            with self._lock:
                self._anchor_epoch = anchor_epoch
                self._anchor_monotonic = anchor_monotonic
                self._offset_seconds = round(offset, 3)
                self._last_synced_at = last_synced_at
                self._source_count = len(accepted)
                self._status = (
                    "synced" if len(accepted) >= 2 else "degraded"
                )
            return True
        finally:
            self._sync_lock.release()

    def _run(self) -> None:
        try:
            self.sync()
        finally:
            self._initial_sync_complete.set()
        while not self._stop_event.is_set():
            if self._stop_event.wait(self.refresh_interval_seconds):
                return
            self.sync()

    def _sample_offset(self, source: str) -> float | None:
        wall_start = self._wall_time()
        monotonic_start = self._monotonic()
        request = urllib.request.Request(
            source,
            headers={
                "Cache-Control": "no-cache",
                "User-Agent": "OTP-Codex-TrustedClock/1",
            },
            method="HEAD",
        )
        try:
            with self._opener(request, timeout=self.timeout_seconds) as response:
                final_url = response.geturl()
                date_header = response.headers.get("Date")
        except (OSError, TimeoutError, ValueError):
            return None
        final_parts = urlsplit(final_url)
        if (
            final_parts.scheme.casefold() != "https"
            or not final_parts.netloc
            or final_parts.username is not None
            or final_parts.password is not None
        ):
            return None
        wall_end = self._wall_time()
        rtt = self._monotonic() - monotonic_start
        wall_elapsed = wall_end - wall_start
        if (
            not date_header
            or rtt < 0
            or rtt > self.maximum_rtt_seconds
            or abs(wall_elapsed - rtt) > 0.5
        ):
            return None
        try:
            server_time = parsedate_to_datetime(date_header)
            if server_time.tzinfo is None:
                server_time = server_time.replace(tzinfo=timezone.utc)
            server_epoch = server_time.timestamp()
        except (OverflowError, TypeError, ValueError):
            return None
        offset = server_epoch - ((wall_start + wall_end) / 2.0)
        if abs(offset) > self.maximum_offset_seconds:
            return None
        return offset

    @staticmethod
    def _without_outliers(samples: list[float]) -> list[float]:
        if len(samples) < 3:
            return samples
        median = statistics.median(samples)
        median_deviation = statistics.median(
            abs(sample - median) for sample in samples
        )
        threshold = max(2.0, median_deviation * 3.0)
        return [
            sample
            for sample in samples
            if abs(sample - median) <= threshold
        ]


_default_clock = TrustedClock()


def get_default_trusted_clock() -> TrustedClock:
    return _default_clock
