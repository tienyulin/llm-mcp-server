"""Tests for WikiCache invalidation semantics."""
import time

from core.cache import WikiCache


def test_invalidate_exact_segment_match():
    """app-1 must not invalidate app-10 (no substring matching)."""
    cache = WikiCache(ttl_seconds=3600)
    cache.set("wiki:app-1", {"a": 1})
    cache.set("wiki:app-10", {"b": 2})

    cache.invalidate_by_source("app-1")

    assert cache.get("wiki:app-1") is None
    assert cache.get("wiki:app-10") == {"b": 2}


def test_invalidate_drops_shared_wiki_entry():
    """The aggregated "wiki" entry contains every app's data, so any
    app-specific invalidation must drop it too."""
    cache = WikiCache(ttl_seconds=3600)
    cache.set("wiki", {"apis": {}})
    cache.set("wiki:app-2", {"b": 2})

    cache.invalidate_by_source("app-1")

    assert cache.get("wiki") is None
    assert cache.get("wiki:app-2") == {"b": 2}


def test_invalidate_without_source_clears_all():
    cache = WikiCache(ttl_seconds=3600)
    cache.set("wiki", {"apis": {}})
    cache.set("wiki:app-1", {"a": 1})

    cache.invalidate_by_source(None)

    assert cache.get("wiki") is None
    assert cache.get("wiki:app-1") is None


def test_ttl_expiry():
    cache = WikiCache(ttl_seconds=0.01)
    cache.set("wiki", {"apis": {}})
    assert cache.get("wiki") == {"apis": {}}

    time.sleep(0.02)
    assert cache.get("wiki") is None
