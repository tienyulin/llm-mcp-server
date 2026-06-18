#!/usr/bin/env python3
"""
LLM Wiki HTTP Server (Team deployment version)
FastAPI with async handlers for concurrent requests.

Exposes wiki.json from Minio as REST API.
Designed for team use with multiple concurrent users.
Supports application-level cache invalidation for multi-source wiki updates.

App factory only — query/fallback logic lives in services/query_service.py,
endpoints in http_api/routers/, shared resources on app.state.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from core.cache import WikiCache
from http_api.mcp_app import build_mcp
from http_api.rate_limit import TokenBucketRateLimiter
from http_api.routers import cache, health, query
from services.embeddings import query_embedder_from_env
from services.query_service import QueryService
from repository.minio_client import MinioReader
from repository.pg_reader import pg_reader_from_env

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    # Native MCP server (Streamable HTTP) over the SAME QueryService as REST.
    # Built before the app so its session-manager lifespan can be composed in.
    mcp = build_mcp(lambda: _query_service_from_state(app))
    mcp_app = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Init MinioReader (+ optional PG reader), then run the MCP session
        manager (its lifespan must be hoisted here — mounted sub-app lifespans
        are not auto-run by Starlette)."""
        app.state.wiki_reader = MinioReader()
        app.state.pg_reader = pg_reader_from_env()
        app.state.query_embedder = query_embedder_from_env()
        if app.state.pg_reader is None:
            logger.warning(
                "PG_DSN not set — reads served from wiki.json only (no semantic search)"
            )
        else:
            await app.state.pg_reader.aopen()
            logger.info(
                f"PG reader enabled (semantic search: "
                f"{'on' if app.state.query_embedder else 'off — embeddings not configured'})"
            )
        logger.info("MCP HTTP Server started (REST + native MCP at /mcp)")
        async with mcp_app.router.lifespan_context(mcp_app):
            yield
        if app.state.pg_reader is not None:
            await app.state.pg_reader.aclose()
        logger.info("MCP HTTP Server shutdown")

    app = FastAPI(
        title="LLM Wiki HTTP API",
        version="1.0.0",
        description="Team-friendly API for wiki queries (REST + native MCP)",
        lifespan=lifespan,
    )
    app.add_middleware(TokenBucketRateLimiter)  # no-op unless RATE_LIMIT_RPS > 0

    # Cache lives on the factory-time state (not lifespan) so tests that run
    # without the lifespan still find initialized state.
    app.state.wiki_cache = WikiCache(ttl_seconds=3600)
    app.state.wiki_reader = None
    app.state.pg_reader = None
    app.state.query_embedder = None

    app.include_router(health.router)
    app.include_router(query.router)
    app.include_router(cache.router)
    app.mount("/mcp", mcp_app)  # native MCP endpoint: POST /mcp/
    return app


def _query_service_from_state(app: FastAPI) -> QueryService:
    """Build a QueryService from the live reader singletons (shared with REST)."""
    s = app.state
    return QueryService(
        wiki_reader=s.wiki_reader,
        cache=s.wiki_cache,
        pg_reader=s.pg_reader,
        query_embedder=s.query_embedder,
    )


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
