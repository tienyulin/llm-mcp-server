"""PG-first read path with fallback (hermetic).

Contract: when the PG reader works, reads come from it; on any reader error
or empty result the endpoint serves the cached-wiki path exactly as before
PG existed; a failing reader trips a cooldown so a dead PG doesn't tax every
request.
"""

# pytest conventions: stub methods accept protocol args they ignore (unused-argument)
# and the _client helper defers an import to keep env ordering (import-outside-toplevel).
# pylint: disable=unused-argument,import-outside-toplevel

import asyncio
import os
from contextlib import contextmanager

from fastapi.testclient import TestClient

from http_api.main import create_app
from repository.pg_reader import PGReader

_FAKE_WIKI = {
    "apis": {
        "inventory": {
            "GET /inventory/health": {
                "description": "Inventory health check",
                "source_app": "app-inventory",
            }
        }
    },
    "metadata": {"updated_at": "2026-06-11T00:00:00"},
}


class StubReader:
    """Looks like PGReader; canned answers or canned failure."""

    def __init__(self, fail=False):
        self.fail = fail

    def in_cooldown(self):
        """Never in cooldown — the stub fails per-call via `fail`, not via a breaker."""
        return False

    def _maybe_fail(self):
        if self.fail:
            raise ConnectionError("pg is down")

    async def semantic_search(self, qvec, top_k):
        """Canned single-hit vector result (or raise when configured to fail)."""
        self._maybe_fail()
        return [
            {
                "module": "inventory",
                "api_key": "GET /inventory/health",
                "description": "Inventory health check",
                "source_app": "app-inventory",
                "score": 0.91,
            }
        ]

    async def keyword_search(self, query, limit=100):
        """Canned single-hit keyword result (or raise when configured to fail)."""
        self._maybe_fail()
        return [
            {
                "module": "inventory",
                "api_key": "GET /inventory/health",
                "description": "Inventory health check",
            }
        ]

    async def list_apis(self, module=""):
        """Canned module listing (or raise when configured to fail)."""
        self._maybe_fail()
        return {"inventory": ["GET /inventory/health"]}

    async def get_api_detail(self, module, api_key):
        """Canned PG detail marked 'from-pg' (or raise when configured to fail)."""
        self._maybe_fail()
        return {"description": "from-pg"}

    async def stats(self):
        """Canned index stats (or raise when configured to fail)."""
        self._maybe_fail()
        return {
            "entries": 1,
            "embedded": 1,
            "last_updated_at": "2026-06-11T00:00:00",
            "last_sync": None,
        }


@contextmanager
def _client(reader, embedder="mock", wiki=None):
    """Fresh app per call (the mounted MCP session manager runs once per app
    instance), with app.state patched after lifespan startup."""
    wiki = _FAKE_WIKI if wiki is None else wiki
    app = create_app()
    with TestClient(app) as client:
        try:
            app.state.pg_reader = reader
            if embedder == "mock":
                os.environ["MOCK_EMBEDDINGS"] = "true"
                from services.embeddings import QueryEmbedder

                app.state.query_embedder = QueryEmbedder()
            else:
                app.state.query_embedder = embedder
            app.state.wiki_cache.clear()
            app.state.wiki_cache.set("wiki", wiki)
            yield client
        finally:
            # Null the stub before lifespan shutdown so aclose() isn't called on it.
            app.state.pg_reader = None
            app.state.query_embedder = None


def test_semantic_search_served_from_pg():
    """A working PG reader serves semantic_search (mode=semantic) verbatim."""
    with _client(StubReader()) as client:
        resp = client.get("/semantic_search", params={"query": "inventory health"})
    body = resp.json()
    assert resp.status_code == 200
    assert body["mode"] == "semantic"
    assert body["results"][0]["api_key"] == "GET /inventory/health"
    assert body["results"][0]["score"] == 0.91


def test_semantic_search_falls_back_without_pg():
    """With no PG reader, semantic_search degrades to the keyword fallback."""
    with _client(None) as client:
        resp = client.get("/semantic_search", params={"query": "inventory"})
    body = resp.json()
    assert resp.status_code == 200
    assert body["mode"] == "keyword_fallback"
    assert body["results"][0]["api_key"] == "GET /inventory/health"


def test_semantic_search_falls_back_on_pg_error():
    """A failing PG reader still yields a 200 via the keyword fallback."""
    with _client(StubReader(fail=True)) as client:
        resp = client.get("/semantic_search", params={"query": "inventory"})
    assert resp.json()["mode"] == "keyword_fallback"
    assert resp.status_code == 200


def test_semantic_search_falls_back_without_embedder():
    """No embedder configured forces the keyword fallback even with PG up."""
    with _client(StubReader(), embedder=None) as client:
        resp = client.get("/semantic_search", params={"query": "inventory"})
    assert resp.json()["mode"] == "keyword_fallback"


def test_search_apis_pg_first_then_fallback():
    """search_apis uses PG keyword first, then the wiki scan when PG fails."""
    with _client(StubReader()) as client:
        assert client.get("/search_apis", params={"query": "health"}).json()["mode"] == "pg_keyword"
    with _client(StubReader(fail=True)) as client:
        body = client.get("/search_apis", params={"query": "health"}).json()
    assert body["mode"] == "wiki_scan"
    assert body["count"] == 1  # same answer, slower path


def test_list_apis_and_detail_fall_back_on_error():
    """list_apis and get_api_detail fall back to wiki data when PG errors."""
    with _client(StubReader(fail=True)) as client:
        modules = client.get("/list_apis").json()["modules"]
        detail = client.get(
            "/get_api_detail", params={"module": "inventory", "api_key": "GET /inventory/health"}
        ).json()["detail"]
    assert modules == {"inventory": ["GET /inventory/health"]}
    assert detail["description"] == "Inventory health check"  # wiki copy, not "from-pg"


def test_get_api_detail_served_from_pg():
    """A working PG reader's detail short-circuits the wiki copy."""
    with _client(StubReader()) as client:
        detail = client.get(
            "/get_api_detail", params={"module": "inventory", "api_key": "GET /inventory/health"}
        ).json()["detail"]
    assert detail == {"description": "from-pg"}


def test_wiki_info_reports_vector_index():
    """wiki_info reports the vector index available with PG, absent without it."""
    with _client(StubReader()) as client:
        body = client.get("/wiki_info").json()
    assert body["vector_index"]["available"] is True
    assert body["vector_index"]["entries"] == 1
    with _client(None) as client:
        body = client.get("/wiki_info").json()
    assert body["vector_index"] == {"available": False}


def test_empty_pg_results_fall_back_to_wiki():
    """A configured-but-unindexed PG must not hide existing wiki data."""

    class EmptyReader(StubReader):
        """A configured PG reader that returns empty results (unindexed)."""

        async def list_apis(self, module=""):
            """Return no modules to simulate an empty/unindexed PG."""
            return {}

        async def keyword_search(self, query, limit=100):
            """Return no keyword hits to simulate an empty/unindexed PG."""
            return []

    with _client(EmptyReader()) as client:
        modules = client.get("/list_apis").json()["modules"]
        search = client.get("/search_apis", params={"query": "health"}).json()
    assert modules == {"inventory": ["GET /inventory/health"]}
    assert search["mode"] == "wiki_scan" and search["count"] == 1


def test_circuit_breaker_trips_on_dead_pg():
    """Real PGReader against a closed port: first call fails and starts the
    cooldown; _pg() then bypasses PG entirely until it expires."""
    reader = PGReader("postgresql://u:p@localhost:9/db", retry_seconds=60)

    async def run():
        try:
            await reader.keyword_search("x")
            raise AssertionError("expected connection failure")
        # Any connection-layer failure is acceptable here — the point is only
        # that some failure tripped the breaker; the exact psycopg type varies.
        except Exception:  # pylint: disable=broad-exception-caught
            pass
        assert reader.in_cooldown()
        await reader.aclose()

    asyncio.run(run())
