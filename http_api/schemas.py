"""Request/response models for the HTTP API."""

from typing import Optional

from pydantic import BaseModel


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
