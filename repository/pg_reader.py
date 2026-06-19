"""PGReader: read-only access to the pgvector index (mcp-server side).

Mirrors the MinioStorage/MinioReader split: the processor owns writes
(wiki-processor/storage/pg_store.py), this side only queries. Every public
method may raise — callers (services/query_service.py) wrap each call and fall back
to the cached-wiki path, so a PG outage degrades silently to today's
behavior. A small circuit breaker (PG_RETRY_SECONDS cooldown) keeps a dead
PG from adding a connection-timeout to every request.
"""

import logging
import os
import time

from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)


def _to_vector_literal(vec: list[float]) -> str:
    return "[" + ",".join(repr(float(c)) for c in vec) + "]"


class PGReader:
    def __init__(self, dsn: str, min_size: int = 1, max_size: int = 10,
                 retry_seconds: float = 30.0):
        self._pool = AsyncConnectionPool(
            conninfo=dsn,
            min_size=min_size,
            max_size=max_size,
            open=False,
            timeout=5,
            kwargs={"connect_timeout": 5},
            check=AsyncConnectionPool.check_connection,
        )
        self._retry_seconds = retry_seconds
        self._down_until = 0.0
        self._opened = False

    async def aopen(self):
        if not self._opened:
            # wait=False: mcp-server must boot (and serve the fallback path)
            # even when PG is down.
            await self._pool.open(wait=False)
            self._opened = True

    async def aclose(self):
        if self._opened:
            await self._pool.close()
            self._opened = False

    # -- circuit breaker ------------------------------------------------

    def in_cooldown(self) -> bool:
        return time.monotonic() < self._down_until

    def _mark_down(self, error: Exception):
        self._down_until = time.monotonic() + self._retry_seconds
        logger.warning(
            f"PG reader marked down for {self._retry_seconds}s "
            f"(falling back to wiki.json reads): {error}"
        )

    async def _fetch(self, query: str, params: tuple = ()):
        """Run one read query; any failure trips the breaker and re-raises."""
        await self.aopen()
        try:
            async with self._pool.connection() as conn:
                cur = await conn.execute(query, params)
                return await cur.fetchall()
        except Exception as e:
            self._mark_down(e)
            raise

    # -- queries ---------------------------------------------------------

    async def semantic_search(self, query_vec: list[float], top_k: int = 10) -> list[dict]:
        literal = _to_vector_literal(query_vec)
        rows = await self._fetch(
            """
            SELECT module, api_key, description, source_app,
                   1 - (embedding <=> %s::vector) AS score
            FROM api_entries
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (literal, literal, top_k),
        )
        return [
            {"module": m, "api_key": k, "description": d,
             "source_app": s, "score": round(float(score), 4)}
            for m, k, d, s, score in rows
        ]

    async def hybrid_search_apis(
        self, query_vec: list[float], query_text: str, top_k: int = 10,
        rrf_k: int = 60, min_cosine: float = 0.5,
    ) -> list[dict]:
        """Hybrid retrieval over api_entries: vector ∪ trigram fused by RRF —
        same recipe as knowledge, reusing the existing api_entries vector +
        trigram indexes. Keyword alone missed paraphrased endpoint queries
        ('undo deleted rows' vs a /recover endpoint); the vector arm catches
        those, the keyword arm keeps exact path/identifier hits.

        Vector arm gated by `min_cosine` so an unrelated query falls back to
        keyword-only matches (which may be empty) rather than nearest-neighbour
        noise."""
        literal = _to_vector_literal(query_vec)
        vec_rows = await self._fetch(
            """
            SELECT module, api_key, description, source_app
            FROM api_entries
            WHERE embedding IS NOT NULL
              AND 1 - (embedding <=> %s::vector) >= %s
            ORDER BY embedding <=> %s::vector
            LIMIT 20
            """,
            (literal, min_cosine, literal),
        )
        kw_rows = await self._fetch(
            """
            SELECT module, api_key, description, source_app
            FROM api_entries
            WHERE embed_text ILIKE %s
            LIMIT 20
            """,
            (f"%{query_text.strip()}%",),
        )
        scores: dict = {}
        meta: dict = {}
        for ranking in (vec_rows, kw_rows):
            for rank, (module, api_key, desc, src) in enumerate(ranking):
                key = (module, api_key)
                scores[key] = scores.get(key, 0.0) + 1.0 / (rrf_k + rank)
                meta[key] = (desc, src)
        ordered = sorted(scores, key=lambda k: scores[k], reverse=True)[:top_k]
        return [
            {"module": m, "api_key": k, "description": meta[(m, k)][0],
             "source_app": meta[(m, k)][1], "score": round(scores[(m, k)], 4)}
            for (m, k) in ordered
        ]

    async def keyword_search(self, query: str, limit: int = 100) -> list[dict]:
        """Indexed replacement for the O(n) wiki scan.

        embed_text concatenates module | api_key | endpoint | description |
        params, so one trigram-indexed ILIKE covers the same haystack as the
        old full-detail substring scan."""
        pattern = f"%{query.strip()}%"
        rows = await self._fetch(
            """
            SELECT module, api_key, description
            FROM api_entries
            WHERE embed_text ILIKE %s
            ORDER BY module, api_key
            LIMIT %s
            """,
            (pattern, limit),
        )
        return [{"module": m, "api_key": k, "description": d} for m, k, d in rows]

    async def hybrid_search_knowledge(
        self, query_vec: list[float], query_text: str, top_k: int = 10,
        rrf_k: int = 60, min_cosine: float = 0.5,
    ) -> list[dict]:
        """Hybrid retrieval over knowledge_entries: fuse vector (semantic) and
        trigram (keyword) rankings with Reciprocal Rank Fusion.

        Evidence (2026 RAG benchmarks) shows fusion beats either signal alone —
        vector catches paraphrases, keyword catches exact terms/identifiers; RRF
        is rank-only so it sidesteps score-scale incompatibility.

        The vector arm drops candidates below `min_cosine` so an unrelated query
        ("how to bake bread") returns nothing instead of the nearest neighbour —
        the floor (0.5) was measured to sit between relevant (>0.61) and
        irrelevant (<0.46) similarities for this corpus.
        """
        literal = _to_vector_literal(query_vec)
        vec_rows = await self._fetch(
            """
            SELECT doc_id, title, source_app, detail
            FROM knowledge_entries
            WHERE embedding IS NOT NULL
              AND 1 - (embedding <=> %s::vector) >= %s
            ORDER BY embedding <=> %s::vector
            LIMIT 20
            """,
            (literal, min_cosine, literal),
        )
        kw_rows = await self._fetch(
            """
            SELECT doc_id, title, source_app, detail
            FROM knowledge_entries
            WHERE embed_text ILIKE %s
            LIMIT 20
            """,
            (f"%{query_text.strip()}%",),
        )

        scores: dict[str, float] = {}
        meta: dict[str, tuple] = {}
        for ranking in (vec_rows, kw_rows):
            for rank, (doc_id, title, source_app, detail) in enumerate(ranking):
                scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (rrf_k + rank)
                meta[doc_id] = (title, source_app, detail)

        ordered = sorted(scores, key=lambda d: scores[d], reverse=True)[:top_k]
        out = []
        for doc_id in ordered:
            title, source_app, detail = meta[doc_id]
            summary = detail.get("summary", "") if isinstance(detail, dict) else ""
            out.append({"doc_id": doc_id, "title": title, "summary": summary,
                        "source_app": source_app, "score": round(scores[doc_id], 4)})
        return out

    async def list_apis(self, module: str = "") -> dict[str, list[str]]:
        if module.strip():
            rows = await self._fetch(
                "SELECT module, api_key FROM api_entries WHERE module = %s "
                "ORDER BY api_key",
                (module.strip(),),
            )
        else:
            rows = await self._fetch(
                "SELECT module, api_key FROM api_entries ORDER BY module, api_key"
            )
        out: dict[str, list[str]] = {}
        for mod, api_key in rows:
            out.setdefault(mod, []).append(api_key)
        return out

    async def get_api_detail(self, module: str, api_key: str) -> dict | None:
        rows = await self._fetch(
            "SELECT detail FROM api_entries WHERE module = %s AND api_key = %s",
            (module, api_key),
        )
        return rows[0][0] if rows else None

    async def stats(self) -> dict:
        counts = await self._fetch(
            "SELECT count(*), count(embedding), max(updated_at) FROM api_entries"
        )
        total, embedded, last_updated = counts[0]
        state = await self._fetch(
            "SELECT value FROM index_state WHERE key = 'last_sync'"
        )
        return {
            "entries": total,
            "embedded": embedded,
            "last_updated_at": last_updated.isoformat() if last_updated else None,
            "last_sync": state[0][0] if state else None,
        }


def pg_reader_from_env() -> PGReader | None:
    """Build the reader from PG_DSN, or None when the layer is disabled."""
    dsn = os.getenv("PG_DSN", "").strip()
    if not dsn:
        return None
    return PGReader(
        dsn,
        min_size=int(os.getenv("PG_POOL_MIN", "1")),
        max_size=int(os.getenv("PG_POOL_MAX", "10")),
        retry_seconds=float(os.getenv("PG_RETRY_SECONDS", "30")),
    )
