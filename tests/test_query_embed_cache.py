"""P4: query-embedding LRU cache. Every hybrid/semantic search embeds the query
in the hot path; under concurrent load that serialized on the embedder and
capped throughput (260->57 q/s). Repeated queries now skip the embed call.

(This repo runs async via asyncio.run() — no pytest-asyncio auto mode.)"""

# pytest convention: tests white-box the embedder's internal cache state.
# pylint: disable=protected-access

import asyncio
import os
from unittest.mock import AsyncMock, patch

from services.embeddings import QueryEmbedder


def _embedder():
    """Build a QueryEmbedder pinned to the real (non-mock) HTTP path, dim=4."""
    os.environ["MOCK_EMBEDDINGS"] = "false"
    e = QueryEmbedder()
    e.mock_mode = False
    e.base_url = "http://embed"
    e.dim = 4
    return e


def _fake_response(vec):
    """A stub httpx response whose JSON carries one embedding vector."""
    r = AsyncMock()
    r.raise_for_status = lambda: None
    r.json = lambda: {"data": [{"embedding": vec}]}
    return r


def test_second_identical_query_hits_cache():
    """A repeated query is served from cache, so the endpoint is hit only once."""
    e = _embedder()
    with patch("httpx.AsyncClient") as mock_client_cls:
        client = mock_client_cls.return_value.__aenter__.return_value
        client.post = AsyncMock(return_value=_fake_response([0.1, 0.2, 0.3, 0.4]))

        async def run():
            v1 = await e.aembed_query("same")
            v2 = await e.aembed_query("same")
            return v1, v2, client.post.await_count

        v1, v2, calls = asyncio.run(run())
        assert v1 == v2 == [0.1, 0.2, 0.3, 0.4]
        assert calls == 1  # second served from cache


def test_different_queries_each_embed():
    """Distinct queries miss the cache and each hit the endpoint once."""
    e = _embedder()
    with patch("httpx.AsyncClient") as mock_client_cls:
        client = mock_client_cls.return_value.__aenter__.return_value
        client.post = AsyncMock(return_value=_fake_response([1.0, 2.0, 3.0, 4.0]))

        async def run():
            await e.aembed_query("a")
            await e.aembed_query("b")
            return client.post.await_count

        assert asyncio.run(run()) == 2


def test_lru_eviction():
    """Exceeding the cache cap evicts the least-recently-used entry."""
    e = _embedder()
    e._cache_max = 2
    with patch("httpx.AsyncClient") as mock_client_cls:
        client = mock_client_cls.return_value.__aenter__.return_value
        client.post = AsyncMock(return_value=_fake_response([0.0, 0.0, 0.0, 0.0]))

        async def run():
            await e.aembed_query("a")
            await e.aembed_query("b")
            await e.aembed_query("c")  # evicts "a"

        asyncio.run(run())
        assert "a" not in e._cache and "b" in e._cache and "c" in e._cache
