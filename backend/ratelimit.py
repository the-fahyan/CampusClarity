"""In-memory fixed-window per-IP rate limiter (DESIGN.md §6.7, FR-19).

Known limitation (documented): state is per-process — ineffective across multiple
workers/instances (PRD §8.4). No persistence.
"""
from __future__ import annotations

import time


class RateLimiter:
    """Fixed window: `{ip: (window_start, count)}`, cleaned lazily on access."""

    def __init__(self, limit_per_minute: int, window_seconds: float = 60.0):
        self.limit = max(1, int(limit_per_minute))
        self.window = float(window_seconds)
        self._hits: dict[str, tuple[float, int]] = {}

    def allow(self, ip: str, now: float | None = None) -> bool:
        """Return True if the request is allowed; update the counter."""
        ts = time.monotonic() if now is None else now
        start, count = self._hits.get(ip, (ts, 0))
        if ts - start >= self.window:
            start, count = ts, 0
        count += 1
        self._hits[ip] = (start, count)
        return count <= self.limit

    def retry_after(self, ip: str, now: float | None = None) -> int:
        """Seconds until the current window for `ip` resets (for Retry-After)."""
        ts = time.monotonic() if now is None else now
        start, _ = self._hits.get(ip, (ts, 0))
        return max(1, int(self.window - (ts - start)) + 1)

    def reset(self) -> None:
        self._hits.clear()
