"""PG-first reads with cached-wiki fallback.

Single home for the fallback contract previously duplicated across the
query endpoints: PG is an optional accelerator — every read falls back to
the cached-wiki path on any error or empty result, so an unconfigured,
down, or not-yet-indexed PG degrades to exactly the pre-PG behavior.
The processor syncs PG before POSTing /cache/invalidate, so when the
fallback cache is dropped PG is already fresh — reads never go backward.
"""

import asyncio
import logging
from typing import Optional

from core.cache import _WIKI_CACHE_KEY, WikiCache
from services.wiki_service import WikiService

logger = logging.getLogger(__name__)


class QueryService:
    def __init__(self, wiki_reader, cache: WikiCache, pg_reader=None, query_embedder=None):
        self._wiki_reader = wiki_reader
        self._cache = cache
        self._pg_reader = pg_reader
        self._embedder = query_embedder
        self._wiki_service = WikiService(wiki_reader)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _pg(self):
        """The PG reader when it is configured and not in failure cooldown."""
        if self._pg_reader is None or self._pg_reader.in_cooldown():
            return None
        return self._pg_reader

    async def _get_wiki(self) -> dict:
        """Fetch the wiki through the TTL cache; invalidated via /cache/invalidate.

        The MinIO read runs in a worker thread — minio-py is synchronous and
        would otherwise block the event loop."""
        wiki = self._cache.get(_WIKI_CACHE_KEY)
        if wiki is None:
            wiki = await asyncio.to_thread(self._wiki_reader.get_wiki)
            self._cache.set(_WIKI_CACHE_KEY, wiki)
        return wiki

    async def _pg_first(self, pg_call):
        """Try PG; return (result, True) on a truthy result, else (None, False).

        Falsy-result semantics matter: get_api_detail must fall back only on
        None, and a truthy PG dict short-circuits the wiki path entirely."""
        pg = self._pg()
        if pg is not None:
            try:
                result = await pg_call(pg)
                if result:
                    return result, True
            except Exception:
                pass  # breaker tripped inside the reader; use fallback
        return None, False

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def list_apis(self, module: str = "") -> dict:
        result, _ = await self._pg_first(lambda pg: pg.list_apis(module))
        if result is None:
            result = self._wiki_service.list_apis(module, wiki=await self._get_wiki())
        return result

    async def search_apis(self, query: str) -> tuple[list, str]:
        results, from_pg = await self._pg_first(lambda pg: pg.keyword_search(query))
        if from_pg:
            return results, "pg_keyword"
        results = self._wiki_service.search_apis(query, wiki=await self._get_wiki())
        return results, "wiki_scan"

    async def semantic_search(self, query: str, top_k: int) -> tuple[list, str]:
        pg = self._pg()
        if pg is not None and self._embedder is not None:
            try:
                qvec = await self._embedder.aembed_query(query)
                results = await pg.semantic_search(qvec, top_k)
                if results:
                    return results, "semantic"
            except Exception as e:
                logger.warning(f"Semantic search failed, falling back to keyword: {e}")

        results = self._wiki_service.search_apis(query, wiki=await self._get_wiki())[:top_k]
        return results, "keyword_fallback"

    async def get_api_detail(self, module: str, api_key: str) -> Optional[dict]:
        detail, from_pg = await self._pg_first(lambda pg: pg.get_api_detail(module, api_key))
        if not from_pg:
            detail = self._wiki_service.get_api_detail(
                module, api_key, wiki=await self._get_wiki()
            )
        return detail

    async def list_concepts(self) -> dict:
        return self._wiki_service.list_concepts(await self._get_wiki())

    async def get_concept(self, name: str) -> Optional[dict]:
        return self._wiki_service.get_concept(name, await self._get_wiki())

    async def get_overview(self, app: str) -> Optional[dict]:
        return self._wiki_service.get_overview(app, await self._get_wiki())

    async def list_knowledge(self) -> dict:
        return self._wiki_service.list_knowledge(await self._get_wiki())

    async def get_knowledge(self, doc_id: str):
        return self._wiki_service.get_knowledge(doc_id, await self._get_wiki())

    async def search_knowledge(self, query: str) -> list:
        return self._wiki_service.search_knowledge(query, await self._get_wiki())

    async def build_skill(self, name: str) -> dict:
        return self._wiki_service.build_skill(await self._get_wiki(), name)

    async def build_graph(self) -> dict:
        return self._wiki_service.build_graph(await self._get_wiki())

    async def wiki_info(self) -> dict:
        wiki = await self._get_wiki()

        total_endpoints = sum(len(apis) for apis in wiki.get("apis", {}).values())
        total_modules = len(wiki.get("apis", {}))

        vector_index = {"available": False}
        pg = self._pg()
        if pg is not None:
            try:
                stats = await pg.stats()
                vector_index = {
                    "available": True,
                    "semantic_search": self._embedder is not None,
                    **stats,
                }
            except Exception:
                vector_index = {"available": False}

        return {
            "modules": total_modules,
            "total_endpoints": total_endpoints,
            "metadata": wiki.get("metadata", {}),
            "vector_index": vector_index,
        }
