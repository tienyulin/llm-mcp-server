"""Cache-invalidation endpoint, called by wiki-processor after a wiki update."""

import logging

from fastapi import APIRouter, Depends

from core.cache import WikiCache
from http_api.deps import get_cache
from http_api.schemas import CacheInvalidateRequest, CacheInvalidateResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/cache/invalidate", response_model=CacheInvalidateResponse)
async def invalidate_cache(
    request: CacheInvalidateRequest | None = None,
    cache: WikiCache = Depends(get_cache),
):
    """
    Invalidate wiki cache (called by wiki-processor after updates).

    If source_app is provided, only invalidates entries related to that app.
    If source_app is None or not provided, clears entire cache.

    This endpoint is called by wiki-processor after successful wiki update.
    """
    source_app = request.source_app if request else None
    prev_size = len(cache)

    cache.invalidate_by_source(source_app)

    curr_size = len(cache)
    invalidated = prev_size - curr_size

    logger.info("Cache invalidated: %d entries removed (source_app=%s)", invalidated, source_app)

    return CacheInvalidateResponse(
        status="ok",
        message=f"Cache invalidated for {source_app or 'all'}",
        invalidated_entries=invalidated,
    )
