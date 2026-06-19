# Hybrid knowledge search (evidence)

Fixes the keyword-only knowledge retrieval flagged in the prior round: paraphrases
("undo a wrong DELETE") missed the Oracle flashback doc because no words overlapped.

## Why hybrid, not "just add vector search"

2026 RAG benchmarks: **pure vector ≈ pure keyword** alone (WANDS NDCG 0.695 vs
0.698) — adding vector by itself would *not* reliably beat the existing keyword
search. The win is the **fusion**: hybrid 79% vs BM25 58% retrieval accuracy;
RRF +7.4% NDCG over either alone.
Sources: [Digital Applied](https://www.digitalapplied.com/blog/hybrid-search-bm25-vector-reranking-reference-2026),
[buildmvpfast](https://www.buildmvpfast.com/blog/hybrid-search-rag-vector-keyword-reranking-2026).

So we fuse vector + keyword with **Reciprocal Rank Fusion** (rank-only → no
score-scale incompatibility).

## Design

- `knowledge_entries` table (separate from `api_entries` → API path provably
  unchanged): vector HNSW + trigram GIN indexes. Same embeddings pipeline as APIs.
- Processor embeds each knowledge entry's distilled text (title|summary|topics|
  key_points) on ingest — one focused "chunk" per short doc.
- `pg_reader.hybrid_search_knowledge`: top-20 vector ∪ top-20 trigram, fused by RRF.
- `search_knowledge` is hybrid when PG+embeddings are up, else keyword fallback —
  same graceful-degradation contract as `semantic_search`.

## Relevance floor (measured, not guessed)

Vector search always returns a nearest neighbour, so an unrelated query returned a
doc. Measured cosine (bge-small-en-v1.5) on this corpus:

| queries | cosine |
|---|---|
| relevant paraphrases (5) | 0.615 – 0.695 |
| irrelevant (bake bread / weather / shoes) | 0.365 – 0.452 |

Clean gap → floor **0.5** (env `MCP_KNOWLEDGE_MIN_COSINE`). Below it the vector arm
is dropped; an irrelevant query returns nothing.

## Result (live, real embeddings)

Local bge-small embedding server, real ingest. Recall of the flashback doc:

| query | keyword | hybrid |
|---|---|---|
| data loss | ✓ | ✓ |
| point in time recovery | ✗ | ✓ |
| undo a wrong DELETE | ✗ | ✓ |
| restore lost rows | ✗ | ✓ |
| revert accidental changes | ✗ | ✓ |
| roll back a mistaken update | ✗ | ✓ |
| **recall** | **1/6** | **6/6** |
| how to bake bread (negative) | ✗ | ✗ (correctly empty) |

Via Claude over MCP, *"a teammate fat-fingered a DELETE and rows are gone"* →
`search_knowledge` **mode hybrid** → Oracle flashback doc + `flashback-api POST
/recover`, cited. Zero keyword overlap.

## How to reproduce

```bash
# real local embeddings (no key): fastembed bge-small on the shared network
# point the stack at it: EMBEDDING_BASE_URL=http://embed-srv:8088 EMBEDDING_DIM=384 MOCK_EMBEDDINGS=false
# ingest a knowledge doc + an api service, then:
curl -s "localhost:8002/search_knowledge?query=undo%20a%20wrong%20DELETE"   # mode: hybrid, hits flashback
curl -s "localhost:8002/search_knowledge?query=how%20to%20bake%20bread"     # mode: keyword_fallback, empty
```

## Follow-up

The same hybrid+floor applies to **API** search (`search_apis` is keyword-only;
the live run missed "restore deleted" for endpoints). Extending RRF hybrid to
`api_entries` is the next step.
