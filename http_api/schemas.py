"""Request/response models for the HTTP API."""

from typing import Optional

from pydantic import BaseModel


class ListApisRequest(BaseModel):
    """Request to list APIs, optionally filtered to one module."""

    module: str = ""


class ListApisResponse(BaseModel):
    """API keys grouped by module name."""

    modules: dict[str, list[str]]


class SearchApisRequest(BaseModel):
    """Keyword search request over API endpoints."""

    query: str


class SearchApisResponse(BaseModel):
    """Matching API records for a search query."""

    results: list[dict]


class ApiDetailResponse(BaseModel):
    """Full detail for one API endpoint, or None when not found."""

    detail: dict | None


class CacheInvalidateRequest(BaseModel):
    """Cache-invalidation request; source_app=None clears the whole cache."""

    source_app: Optional[str] = None  # e.g., "app-inventory". If None, clears all.


class CacheInvalidateResponse(BaseModel):
    """Result of a cache-invalidation call."""

    status: str
    message: str
    invalidated_entries: int
