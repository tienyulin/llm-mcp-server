# mcp-server — architecture

Read-only query service. Layered: `http_api/` (routers) → `services/`
(query logic + pure wiki functions) → `repository/` (MinIO + PG readers).
Every read is PG-first with cached-wiki fallback.

## Internal layering

```mermaid
flowchart TD
    subgraph http["http_api/ (FastAPI)"]
        QR["routers/query.py<br/>list_apis · search_apis · semantic_search<br/>get_api_detail · wiki_info<br/>list_concepts · get_concept · get_overview · skill · graph"]
        CR["routers/cache.py<br/>POST /cache/invalidate"]
        HR["routers/health.py"]
        RL["rate_limit.py (token bucket)"]
    end
    QS["services/query_service.py<br/>PG-first + fallback orchestration"]
    WS["services/wiki_service.py<br/>pure fns: search, concepts,<br/>overview, build_skill, build_graph"]
    CACHE["core/cache.py (TTL wiki cache)"]
    PGR["repository/pg_reader.py<br/>read-only, circuit-broken"]
    MIN["repository/minio_client.py<br/>MinioReader → wiki.json"]

    QR --> QS
    CR --> CACHE
    QS --> CACHE
    QS --> PGR
    QS --> WS
    WS --> CACHE
    CACHE --> MIN
```

## Read path (PG-first, always answerable)

```mermaid
flowchart TD
    Q["query in"] --> PG{"PG configured<br/>+ not in cooldown?"}
    PG -->|yes| TRY["PG: keyword / semantic / detail"]
    TRY -->|truthy result| RET["return (mode: pg_keyword / semantic)"]
    TRY -->|error / empty| FB
    PG -->|no| FB

    FB["fallback: cached wiki.json"] --> CHK{"in TTL cache?"}
    CHK -->|no| LOAD["read MinIO (worker thread)<br/>+ cache"]
    CHK -->|yes| SCAN
    LOAD --> SCAN["WikiService scan / pure fn"]
    SCAN --> RET2["return (mode: wiki_scan / keyword_fallback)"]
```

Concepts, overviews, skill, and graph read **only** the cached `wiki.json` (no PG
path) — wiki-processor produces `concepts`/`overviews`; mcp-server just serves
them. See [`docs/api.md`](../api.md) for endpoint shapes.
