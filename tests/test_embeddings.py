"""Pins mock_embed to the exact same algorithm as wiki-processor's copy.

Query vectors (this service) and index vectors (wiki-processor) must live in
the same vector space — drift between the two copies would silently break
semantic search in every mock-mode test. The golden constants here are
identical to wiki-processor/tests/test_embeddings.py; change the two
implementations and the two golden tests together.
"""
import math

import pytest

from services.embeddings import QueryEmbedder, mock_embed


def test_mock_embed_golden_values():
    vec = mock_embed("inventory | GET /inventory/health | Inventory Health Check", 8)
    expected = [0.872872, 0.0, 0.0, 0.218218, 0.0, 0.0, 0.0, -0.436436]
    assert vec == pytest.approx(expected, abs=1e-6)


def test_mock_embed_deterministic_and_normalized():
    a = mock_embed("inventory health", 256)
    assert a == mock_embed("inventory health", 256)
    assert math.isclose(math.sqrt(sum(c * c for c in a)), 1.0, rel_tol=1e-9)


def test_query_embedder_mock_mode(monkeypatch):
    monkeypatch.setenv("MOCK_EMBEDDINGS", "true")
    monkeypatch.setenv("EMBEDDING_DIM", "64")
    embedder = QueryEmbedder()
    assert embedder.is_enabled()

    import asyncio
    vec = asyncio.run(embedder.aembed_query("inventory health"))
    assert vec == mock_embed("inventory health", 64)


def test_query_embedder_disabled_without_config(monkeypatch):
    monkeypatch.delenv("EMBEDDING_BASE_URL", raising=False)
    monkeypatch.setenv("MOCK_EMBEDDINGS", "false")
    assert QueryEmbedder().is_enabled() is False
