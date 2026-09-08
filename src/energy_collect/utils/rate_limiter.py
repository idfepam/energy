from __future__ import annotations

import threading
import time


class RateLimiter:
    """Token-bucket rate limiter for API requests."""

    def __init__(self, requests_per_minute: int = 350) -> None:
        self.interval = 60.0 / requests_per_minute
        self._lock = threading.Lock()
        self._last_request = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request
            if elapsed < self.interval:
                time.sleep(self.interval - elapsed)
            self._last_request = time.monotonic()
