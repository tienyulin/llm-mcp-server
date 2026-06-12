"""Request-scoped dependency providers backed by app.state.

Resources (wiki_reader, pg_reader, query_embedder) are created in the
lifespan; the cache is created at factory time so tests that run without
the lifespan still find initialized state. QueryService assembly per
request is cheap — WikiService is a thin wrapper over the reader.
"""

from fastapi import Request

from core.cache import WikiCache
from services.query_service import QueryService


def get_query_service(request: Request) -> QueryService:
    s = request.app.state
    return QueryService(
        wiki_reader=s.wiki_reader,
        cache=s.wiki_cache,
        pg_reader=s.pg_reader,
        query_embedder=s.query_embedder,
    )


def get_cache(request: Request) -> WikiCache:
    return request.app.state.wiki_cache
