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
```
- `http_api/` — FastAPI app + routers (query, cache, health) + rate limiting
- `services/` — query service, wiki service, embeddings (query side), cache
- `repository/` — `minio_client.py` (reader), `pg_reader.py` (read-only, circuit-broken)
- `core/` — config + DI

## Quickstart (standalone)
```bash
cp .env.example .env
docker compose up -d --build   # brings up minio + pg + mcp-server
curl localhost:8002/health
```
> mcp-server only **reads**. It returns empty until a `wiki-processor` populates
> MinIO + PG. For data, run the full [platform stack](https://github.com/tienyulin/llm-wiki-mcp).

## Develop in a Dev Container
This repo ships a [`.devcontainer/`](.devcontainer/). In VS Code / Cursor:
**Reopen in Container** — builds this service + its deps (minio, pg), mounts the
source live at `/app`, isolated Python env (won't clash with the other services).
Inside: `python -m pytest`, or `python http_api/main.py` (:8002). For data,
populate via a running wiki-processor or the full platform.

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
- [API reference](docs/api.md)
- Cross-cutting (platform): `docs/architecture/vector-search.md`,
  `docs/examples/real-semantic-walkthrough.md`, `docs/architecture/service-layering.md`
