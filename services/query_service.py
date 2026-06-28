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
import os
from typing import Optional

from core.cache import _WIKI_CACHE_KEY, WikiCache
from services.wiki_service import WikiService

logger = logging.getLogger(__name__)


class QueryService:
    """PG-first read facade with cached-wiki fallback for every read endpoint."""

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
            # Any PG failure degrades to the cached-wiki path; the reader's own
            # breaker has already tripped, so we just swallow and fall back.
            except Exception:  # pylint: disable=broad-exception-caught
                pass  # breaker tripped inside the reader; use fallback
        return None, False

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    async def list_apis(self, module: str = "") -> dict:
        """API keys grouped by module (PG-first, cached-wiki fallback)."""
        result, _ = await self._pg_first(lambda pg: pg.list_apis(module))
        if result is None:
            result = self._wiki_service.list_apis(module, wiki=await self._get_wiki())
        return result

    async def search_apis(self, query: str) -> tuple[list, str]:
        """Search API endpoints, returning (results, mode).

        Hybrid (vector+keyword RRF) when PG+embeddings are up — keyword alone
        missed paraphrased endpoint queries. Falls back to pg keyword, then the
        cached-wiki scan, so an unconfigured/down PG degrades cleanly."""
        pg = self._pg()
        if pg is not None and self._embedder is not None:
            try:
                qvec = await self._embedder.aembed_query(query)
                min_cos = float(os.getenv("API_SEARCH_MIN_COSINE", "0.5"))
                results = await pg.hybrid_search_apis(qvec, query, min_cosine=min_cos)
                if results:
                    return results, "hybrid"
            # Degrade to the keyword path on any embed/PG failure rather than 5xx.
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning("API hybrid search failed, falling back to keyword: %s", e)
        results, from_pg = await self._pg_first(lambda pg: pg.keyword_search(query))
        if from_pg:
            return results, "pg_keyword"
        results = self._wiki_service.search_apis(query, wiki=await self._get_wiki())
        return results, "wiki_scan"

    async def semantic_search(self, query: str, top_k: int) -> tuple[list, str]:
        """Vector search, returning (results, mode); keyword fallback when PG/embeddings down."""
        pg = self._pg()
        if pg is not None and self._embedder is not None:
            try:
                qvec = await self._embedder.aembed_query(query)
                results = await pg.semantic_search(qvec, top_k)
                if results:
                    return results, "semantic"
            # Degrade to the keyword path on any embed/PG failure rather than 5xx.
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning("Semantic search failed, falling back to keyword: %s", e)

        results = self._wiki_service.search_apis(query, wiki=await self._get_wiki())[:top_k]
        return results, "keyword_fallback"

    async def get_api_detail(self, module: str, api_key: str) -> Optional[dict]:
        """Full detail for one endpoint (PG-first, cached-wiki fallback)."""
        detail, from_pg = await self._pg_first(lambda pg: pg.get_api_detail(module, api_key))
        if not from_pg:
            detail = self._wiki_service.get_api_detail(module, api_key, wiki=await self._get_wiki())
        return detail

    async def list_concepts(self) -> dict:
        """Cross-app concepts (summary view) from the cached wiki."""
        return self._wiki_service.list_concepts(await self._get_wiki())

    async def get_concept(self, name: str) -> Optional[dict]:
        """Full concept record, or None when absent."""
        return self._wiki_service.get_concept(name, await self._get_wiki())

    async def get_overview(self, app: str) -> Optional[dict]:
        """Per-app overview record, or None when absent."""
        return self._wiki_service.get_overview(app, await self._get_wiki())

    # `type` is the public param name (Diataxis doc_type); renaming changes the API.
    async def list_knowledge(
        self, type: str = "", tag: str = ""  # pylint: disable=redefined-builtin
    ) -> dict:
        """Knowledge documents (summary view), optionally filtered by doc_type
        and/or a single tag (cronjob/worker/cli share doc_type=reference)."""
        return self._wiki_service.list_knowledge(await self._get_wiki(), type=type, tag=tag)

    async def get_knowledge(self, doc_id: str):
        """Full knowledge entry, or None when absent."""
        return self._wiki_service.get_knowledge(doc_id, await self._get_wiki())

    # `type` is the public param name (Diataxis doc_type); renaming changes the API.
    async def search_knowledge(  # pylint: disable=redefined-builtin
        self, query: str, type: str = "", tag: str = ""
    ) -> tuple[list, str]:
        """Hybrid (vector+keyword RRF) when PG + embeddings are available; else
        keyword scan over the cached wiki. Mirrors semantic_search's contract:
        a degraded-but-answerable query never errors. Results are enriched with
        doc_type/tags from the cached wiki (PG rows don't carry them); optional
        `type` filters by Diataxis doc_type and `tag` by a single tag."""
        pg = self._pg()
        results, mode = None, "keyword_fallback"
        if pg is not None and self._embedder is not None:
            try:
                qvec = await self._embedder.aembed_query(query)
                min_cos = float(os.getenv("MCP_KNOWLEDGE_MIN_COSINE", "0.5"))
                hits = await pg.hybrid_search_knowledge(qvec, query, min_cosine=min_cos)
                if hits:
                    results, mode = hits, "hybrid"
            # Degrade to the keyword path on any embed/PG failure rather than 5xx.
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.warning("Knowledge hybrid search failed, falling back to keyword: %s", e)
        if results is None:
            results = self._wiki_service.search_knowledge(
                query, await self._get_wiki(), type=type, tag=tag
            )
            return results, "keyword_fallback"
        # enrich + type/tag-filter against the cached wiki (PG rows lack doc_type/tags)
        knowledge = (await self._get_wiki()).get("knowledge", {})
        enriched = []
        for r in results:
            entry = knowledge.get(r.get("doc_id"), {})
            r = {**r, "doc_type": entry.get("doc_type"), "tags": entry.get("tags", [])}
            if type and r["doc_type"] != type:
                continue
            if tag and tag not in (r.get("tags") or []):
                continue
            enriched.append(r)
        return enriched, mode

    async def build_skill(self, name: str) -> dict:
        """Package the cached wiki into an Anthropic Skill folder ({path: content})."""
        return self._wiki_service.build_skill(await self._get_wiki(), name)

    async def build_graph(self) -> dict:
        """Knowledge graph (endpoint + concept nodes, weighted edges)."""
        return self._wiki_service.build_graph(await self._get_wiki())

    async def wiki_info(self) -> dict:
        """Wiki statistics plus vector-index availability/stats."""
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
            # Stats are a best-effort side panel — any PG failure just reports
            # the index as unavailable instead of failing the whole response.
            except Exception:  # pylint: disable=broad-exception-caught
                vector_index = {"available": False}

        return {
            "modules": total_modules,
            "total_endpoints": total_endpoints,
            "metadata": wiki.get("metadata", {}),
            "vector_index": vector_index,
        }
