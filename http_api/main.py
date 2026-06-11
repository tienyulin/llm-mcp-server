#!/usr/bin/env python3
"""
LLM Wiki HTTP Server (Team deployment version)
FastAPI with async handlers for concurrent requests.

Exposes wiki.json from Minio as REST API.
Designed for team use with multiple concurrent users.
Supports application-level cache invalidation for multi-source wiki updates.
"""

import logging
import time
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from services.wiki_service import WikiService
from storage.minio_client import MinioReader

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================================
# In-Memory Cache Management
# ============================================================================

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


wiki_cache = WikiCache(ttl_seconds=3600)


# ============================================================================
# Request/Response Models
# ============================================================================

class ListApisRequest(BaseModel):
    module: str = ""


class ListApisResponse(BaseModel):
    modules: dict[str, list[str]]


class SearchApisRequest(BaseModel):
    query: str


class SearchApisResponse(BaseModel):
    results: list[dict]


class ApiDetailResponse(BaseModel):
    detail: dict | None


class CacheInvalidateRequest(BaseModel):
    source_app: Optional[str] = None  # e.g., "app-inventory". If None, clears all.


class CacheInvalidateResponse(BaseModel):
    status: str
    message: str
    invalidated_entries: int


# ============================================================================
# Lifespan (initialize once)
# ============================================================================

wiki_reader = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize MinioReader on startup."""
    global wiki_reader
    wiki_reader = MinioReader()
    logger.info("MCP HTTP Server started")
    yield
    logger.info("MCP HTTP Server shutdown")


app = FastAPI(
    title="LLM Wiki HTTP API",
    version="1.0.0",
    description="Team-friendly API for wiki queries",
    lifespan=lifespan,
)


# ============================================================================
# Routes (all async for concurrent handling)
# ============================================================================

def _get_wiki() -> dict:
    """Fetch the wiki through the TTL cache; invalidated via /cache/invalidate."""
    wiki = wiki_cache.get(_WIKI_CACHE_KEY)
    if wiki is None:
        wiki = wiki_reader.get_wiki()
        wiki_cache.set(_WIKI_CACHE_KEY, wiki)
    return wiki


@app.get("/health")
async def health():
    """Health check."""
    return {"status": "ok"}


@app.get("/list_apis")
async def list_apis(module: str = ""):
    """
    List all API endpoints.

    Args:
        module: Optional module name to filter

    Returns:
        Dict mapping module names to list of API keys
    """
    service = WikiService(wiki_reader)
    result = service.list_apis(module, wiki=_get_wiki())

    if not result:
        msg = f"No APIs found for module '{module}'" if module.strip() else "Wiki is empty"
        raise HTTPException(status_code=404, detail=msg)

    return {"modules": result}


@app.get("/search_apis")
async def search_apis(query: str):
    """
    Search API endpoints by keyword.

    Args:
        query: Search keyword (searches path, description, parameters)

    Returns:
        List of matching API records
    """
    if not query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    service = WikiService(wiki_reader)
    results = service.search_apis(query, wiki=_get_wiki())

    return {"results": results, "count": len(results)}


@app.get("/get_api_detail")
async def get_api_detail(module: str, api_key: str):
    """
    Get full details of a specific API endpoint.

    Args:
        module: Module name (e.g., 'inventory')
        api_key: API key (e.g., 'GET /inventory/{id}')

    Returns:
        Full API details or 404 if not found
    """
    service = WikiService(wiki_reader)
    detail = service.get_api_detail(module, api_key, wiki=_get_wiki())

    if detail is None:
        raise HTTPException(
            status_code=404,
            detail=f"API '{api_key}' not found in module '{module}'",
        )

    return {"detail": detail}


@app.get("/wiki_info")
async def wiki_info():
    """Get wiki statistics."""
    wiki = _get_wiki()

    total_endpoints = sum(len(apis) for apis in wiki.get("apis", {}).values())
    total_modules = len(wiki.get("apis", {}))

    return {
        "modules": total_modules,
        "total_endpoints": total_endpoints,
        "metadata": wiki.get("metadata", {}),
    }


@app.post("/cache/invalidate", response_model=CacheInvalidateResponse)
async def invalidate_cache(request: CacheInvalidateRequest = None):
    """
    Invalidate wiki cache (called by wiki-processor after updates).

    If source_app is provided, only invalidates entries related to that app.
    If source_app is None or not provided, clears entire cache.

    This endpoint is called by wiki-processor after successful wiki update.
    """
    source_app = request.source_app if request else None
    prev_size = len(wiki_cache._cache)

    wiki_cache.invalidate_by_source(source_app)

    curr_size = len(wiki_cache._cache)
    invalidated = prev_size - curr_size

    logger.info(f"Cache invalidated: {invalidated} entries removed (source_app={source_app})")

    return CacheInvalidateResponse(
        status="ok",
        message=f"Cache invalidated for {source_app or 'all'}",
        invalidated_entries=invalidated,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
