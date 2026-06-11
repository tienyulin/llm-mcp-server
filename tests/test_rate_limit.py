"""Tests for the token-bucket rate limiting middleware."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from http_api.rate_limit import TokenBucketRateLimiter


def make_app(rps: float) -> TestClient:
    app = FastAPI()
    app.add_middleware(TokenBucketRateLimiter, rps=rps)

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return TestClient(app)


def test_disabled_by_default_allows_everything():
    client = make_app(rps=0)
    for _ in range(50):
        assert client.get("/ping").status_code == 200


def test_burst_then_429():
    client = make_app(rps=5)  # burst = 10
    statuses = [client.get("/ping").status_code for _ in range(15)]
    assert statuses[:10] == [200] * 10
    assert 429 in statuses[10:]

    limited = next(r for r in [client.get("/ping") for _ in range(3)]
                   if r.status_code == 429)
    assert limited.headers.get("Retry-After") == "1"


def test_health_is_exempt():
    client = make_app(rps=1)  # burst = 2
    # exhaust the bucket on /ping
    for _ in range(5):
        client.get("/ping")
    # /health is never limited
    for _ in range(20):
        assert client.get("/health").status_code == 200


def test_tokens_refill_over_time(monkeypatch):
    import http_api.rate_limit as rl

    fake_now = [1000.0]
    monkeypatch.setattr(rl.time, "monotonic", lambda: fake_now[0])

    client = make_app(rps=5)  # burst = 10
    for _ in range(10):
        assert client.get("/ping").status_code == 200
    assert client.get("/ping").status_code == 429

    fake_now[0] += 1.0  # +1s -> 5 tokens refilled
    assert client.get("/ping").status_code == 200
