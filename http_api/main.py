#!/usr/bin/env python3
"""
LLM Wiki HTTP Server (Team deployment version)
FastAPI with async handlers for concurrent requests.

Exposes wiki.json from Minio as REST API.
Designed for team use with multiple concurrent users.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from services.wiki_service import WikiService
from storage.minio_client import MinioReader

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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
    result = service.list_apis(module)

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
    results = service.search_apis(query)

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
    detail = service.get_api_detail(module, api_key)

    if detail is None:
        raise HTTPException(
            status_code=404,
            detail=f"API '{api_key}' not found in module '{module}'",
        )

    return {"detail": detail}


@app.get("/wiki_info")
async def wiki_info():
    """Get wiki statistics."""
    service = WikiService(wiki_reader)
    wiki = wiki_reader.get_wiki()

    total_endpoints = sum(len(apis) for apis in wiki.get("apis", {}).values())
    total_modules = len(wiki.get("apis", {}))

    return {
        "modules": total_modules,
        "total_endpoints": total_endpoints,
        "metadata": wiki.get("metadata", {}),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
