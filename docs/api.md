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

## `GET /list_concepts`
Cross-app concepts (built by wiki-processor's `/admin/rebuild-concepts`).
`{"concepts":{"<name>":{description,apps:[...],related_count}}}` — empty until built.

## `GET /get_concept?name=<name>`
`{"concept":{description,related:["<module>::<api_key>", ...],apps:[...]}}` or 404.

## `GET /get_overview?app=<app>`
Per-app overview synthesized at ingest. `{"overview":{text,updated_at}}` or 404.

## `GET /skill?name=<skill-name>`
Packages the wiki into an Anthropic Skill folder.
`{"files":{"<name>/SKILL.md":"...","<name>/references/concepts.md":"..."}}`.

## `GET /graph`
Knowledge graph. `{"nodes":[{id,type,module?}],"edges":[{source,target,weight,kind}]}`.
Edges: `shared_source` (4.0, endpoints sharing a source file), `concept` (3.0, concept→endpoint).

## `POST /cache/invalidate`
`{"source_app":"my-app"}` → drops cached entries for that app (called by wiki-processor after a write).

## `GET /health`
`{"status":"ok"}`

## Native MCP — `POST /mcp/`
A real [Model Context Protocol](https://modelcontextprotocol.io) server (Streamable
HTTP transport) mounted on the same app, so Claude / agents connect natively — no
custom REST client. Stateless (`stateless_http=True`): horizontally scalable, no
session affinity. Tools are thin wrappers over the same `QueryService` as REST:
`search_apis`, `semantic_search`, `list_apis`, `get_api_detail`, `list_concepts`,
`get_concept`, `get_overview`, `wiki_info`.

Connect (Claude Code): `claude mcp add --transport http llm-wiki http://localhost:8002/mcp/`

Production: set `MCP_ALLOWED_HOSTS` (comma-separated) to enable DNS-rebinding
protection; unset = protection off (dev default). See
[architecture/mcp-transport.md](architecture/mcp-transport.md) for the design rationale.

How semantic search resolves (query → embed → pgvector cosine → rank), with a
fully worked real example, is in the platform doc
`docs/examples/real-semantic-walkthrough.md` and `docs/architecture/vector-search.md`.
