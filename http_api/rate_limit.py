"""Per-client-IP token-bucket rate limiting middleware.

Deliberately dependency-free to match the project's minimal style. Enabled by
setting RATE_LIMIT_RPS > 0 (requests/second per client IP, burst = 2x rps);
disabled by default. /health is exempt so orchestrator probes never starve.
"""

import os
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

_EXEMPT_PATHS = {"/health"}


# A Starlette middleware's public surface is the single `dispatch` hook, so the
# one-public-method count is intrinsic to the base class, not a design smell.
class TokenBucketRateLimiter(BaseHTTPMiddleware):  # pylint: disable=too-few-public-methods
    """Token-bucket limiter (per client IP) implemented as a Starlette middleware."""

    def __init__(self, app, rps: float | None = None):
        super().__init__(app)
        self.rps = rps if rps is not None else float(os.getenv("RATE_LIMIT_RPS", "0"))
        self.burst = self.rps * 2
        self._buckets: dict[str, tuple[float, float]] = {}  # ip -> (tokens, last_ts)

    def _allow(self, client_ip: str) -> bool:
        now = time.monotonic()
        tokens, last = self._buckets.get(client_ip, (self.burst, now))
        tokens = min(self.burst, tokens + (now - last) * self.rps)
        if tokens < 1:
            self._buckets[client_ip] = (tokens, now)
            return False
        self._buckets[client_ip] = (tokens - 1, now)
        return True

    async def dispatch(self, request: Request, call_next):
        if self.rps <= 0 or request.url.path in _EXEMPT_PATHS:
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        if not self._allow(client_ip):
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
                headers={"Retry-After": "1"},
            )
        return await call_next(request)
