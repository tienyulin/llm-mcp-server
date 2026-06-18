# mcp-server

Read-only query service for the LLM Wiki platform. Serves keyword, semantic, and
structured lookups over the wiki that `wiki-processor` builds. PG-first
(keyword via `pg_trgm`, semantic via pgvector cosine) with automatic fallback to
scanning MinIO `wiki.json` when the index is unavailable. In-memory TTL cache with
per-app invalidation.

Part of the [llm-wiki-mcp platform](https://github.com/tienyulin/llm-wiki-mcp);
deployable on its own.

## Architecture
```
GET /search_apis · /semantic_search · /list_apis · /get_api_detail · /wiki_info
        └─> PG/pgvector (fast path)  ──fallback──>  MinIO wiki.json
GET /list_concepts · /get_concept · /get_overview · /skill · /graph
        └─> MinIO wiki.json (concepts/overviews built by wiki-processor)
```
- `http_api/` — FastAPI app + routers (query, cache, health) + rate limiting
- `services/` — query service, wiki service, embeddings (query side), cache
- `repository/` — `minio_client.py` (reader), `pg_reader.py` (read-only, circuit-broken)
- `core/` — config + DI

## Quickstart
Uses the **shared infra** ([llm-wiki-infra](https://github.com/tienyulin/llm-wiki-infra))
so it reads the same MinIO + Postgres that wiki-processor writes:
```bash
# 1) shared infra (once)
(cd ../llm-wiki-infra && docker compose up -d)
# 2) this service
cp .env.example .env
docker compose up -d --build
curl localhost:8002/health
```
> mcp-server only **reads**. It returns empty until a `wiki-processor` (on the
> same shared infra) populates MinIO + PG.

## Develop in a Dev Container
This repo ships a [`.devcontainer/`](.devcontainer/). **Start the shared infra
first** (`cd ../llm-wiki-infra && docker compose up -d`), then in VS Code /
Cursor: **Reopen in Container** — builds this service, mounts source live at
`/app`, isolated Python env, attached to the shared `llm-wiki-net`. Inside:
`python -m pytest`, or `python http_api/main.py` (:8002). For data, run a
wiki-processor on the same infra.

## Query examples
```bash
curl 'localhost:8002/list_apis'
curl 'localhost:8002/search_apis?query=billing'
curl 'localhost:8002/semantic_search?query=charge%20a%20credit%20card&top_k=3'
curl 'localhost:8002/wiki_info'
```

## Configuration
See [`.env.example`](.env.example). The `EMBEDDING_*` vars **must match the
processor's** (same model + dim) so query vectors live in the index's space.

## Tests
```bash
python -m pytest            # hermetic (Minio SDK stubbed); real-PG tests auto-skip
```

## Docs
- [Architecture diagrams](docs/architecture/diagram.md) — layering + PG-first read path
- [API reference](docs/api.md)
- Cross-cutting (platform): `docs/architecture/vector-search.md`,
  `docs/examples/real-semantic-walkthrough.md`, `docs/architecture/service-layering.md`
