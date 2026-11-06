"""
In-process rate limiting for POST /scan and POST /extract (security
hardening).

No Redis, no external limiter service (CLAUDE.md V1 constraint) — a plain
in-memory sliding window is enough for a single-process, single-owner app.
The goal isn't fairness across users (there's only one, by design), it's a
ceiling on how many Gmail/Claude API calls a leaked token can trigger per
minute. The automatic ~2-minute poll (app/scheduler.py) calls run_scan()/
run_extract() directly, bypassing these HTTP-layer limiters entirely — its
own interval is the relevant limit there, and it must never be throttled
by a limit sized for manual clicks.
"""

import time
from collections import deque

from fastapi import HTTPException


class RateLimiter:
    def __init__(self, max_calls: int, period_seconds: float) -> None:
        self.max_calls = max_calls
        self.period_seconds = period_seconds
        self._calls: deque[float] = deque()

    def check(self) -> None:
        now = time.monotonic()
        while self._calls and now - self._calls[0] > self.period_seconds:
            self._calls.popleft()
        if len(self._calls) >= self.max_calls:
            raise HTTPException(429, "Rate limit exceeded — try again shortly")
        self._calls.append(now)


# 5 manual triggers per minute is generous for a human clicking a button,
# and bounds the damage of a leaked token looping the endpoint.
_scan_limiter = RateLimiter(max_calls=5, period_seconds=60)
_extract_limiter = RateLimiter(max_calls=5, period_seconds=60)


def rate_limit_scan() -> None:
    _scan_limiter.check()


def rate_limit_extract() -> None:
    _extract_limiter.check()
