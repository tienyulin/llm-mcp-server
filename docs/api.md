# mcp-server API

Read-only query API over the wiki. Base URL: `http://localhost:8002`.
All reads are PG-first (keyword via `pg_trgm`, semantic via pgvector cosine) and
fall back to scanning MinIO `wiki.json` when PG is unavailable.

## `GET /list_apis?module=<optional>`
`{"modules": {"<module>": ["GET /x/items", ...]}}` — all modules/endpoints.

## `GET /search_apis?query=<q>`
Keyword search. `{"results":[{module,api_key,description}], "count":N, "mode":"pg_keyword"|"wiki_scan"}`.

## `GET /semantic_search?query=<q>&top_k=10`
Vector similarity (cosine). Embeds the query, ranks `api_entries` by
`1 - (embedding <=> query)`.
`{"results":[{module,api_key,description,source_app,score}], "mode":"semantic"|"keyword_fallback"}`.

## `GET /get_api_detail?module=<m>&api_key=<METHOD /path>`
`{"detail":{method,path,description,source_app,source_version, ...}}` or not-found.

## `GET /wiki_info`
`{"modules":N,"total_endpoints":M,"vector_index":{available,semantic_search,entries,embedded,...}}`.

## `POST /cache/invalidate`
`{"source_app":"my-app"}` → drops cached entries for that app (called by wiki-processor after a write).

## `GET /health`
`{"status":"ok"}`

How semantic search resolves (query → embed → pgvector cosine → rank), with a
fully worked real example, is in the platform doc
`docs/examples/real-semantic-walkthrough.md` and `docs/architecture/vector-search.md`.
