"""In-memory TTL cache for wiki data."""

import logging
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

_WIKI_CACHE_KEY = "wiki"


class WikiCache:
    """Simple in-memory cache for wiki data with TTL support.

    Keys are colon-separated segments (e.g. "wiki", "wiki:app-inventory") so
    that per-app invalidation can match a segment exactly instead of doing
    substring matching ("app-1" must not invalidate "app-10").
    """

    def __init__(self, ttl_seconds: float = 3600):
        self.ttl = ttl_seconds
        self._cache: dict = {}
        self._timestamps: dict = {}

    def get(self, key: str) -> Any:
        """Get value if not expired."""
        if key not in self._cache:
            return None
        if time.time() - self._timestamps[key] > self.ttl:
            del self._cache[key]
            del self._timestamps[key]
            return None
        return self._cache[key]

    def set(self, key: str, value: Any):
        """Set value with current timestamp."""
        self._cache[key] = value
        self._timestamps[key] = time.time()

    def invalidate_by_source(self, source_app: Optional[str] = None):
        """Invalidate cache entries related to a source app.

        The shared "wiki" entry aggregates every app's data, so it is dropped
        on any app-specific invalidation as well.
        """
        if source_app:
            keys_to_delete = [
                k for k in self._cache.keys()
                if k == _WIKI_CACHE_KEY or source_app in str(k).split(":")
            ]
            for k in keys_to_delete:
                del self._cache[k]
                del self._timestamps[k]
            logger.info(f"Invalidated {len(keys_to_delete)} cache entries for {source_app}")
        else:
            # Clear all
            self._cache.clear()
            self._timestamps.clear()
            logger.info("Cleared entire cache")

    def clear(self):
        """Clear entire cache."""
        self._cache.clear()
        self._timestamps.clear()
