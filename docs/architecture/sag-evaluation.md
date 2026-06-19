# Evaluation: SAG (query-time dynamic hyperedges) vs. our design

Paper: [SAG: SQL-Retrieval Augmented Generation with Query-Time Dynamic
Hyperedges](https://arxiv.org/abs/2606.15971). Evaluated as a candidate
improvement. **Verdict: do not adopt wholesale; borrow one idea later.**

## What SAG does

Each chunk → one *event* + LLM-extracted *indexing entities* (11 types). Tables:
events, entities, event–entity junction. At query time it SQL-joins events that
share entities into *local hyperedges*, expands an entity frontier ≤H hops, ranks,
returns chunks. Append-only, no pre-built global graph. Beats HippoRAG 2 on
multi-hop QA (MuSiQue R@2 64.1 vs 49.5; HotpotQA 91.6 vs 78.4).

## Why it wins *in its setting* — and why that setting isn't ours

SAG targets **non-agentic, single-shot RAG** over **large multi-hop corpora**
(HotpotQA/MuSiQue, "hundreds of millions of items"). Its gains come from baking
multi-hop traversal into one retrieval call, and from avoiding the rebuild cost of
static knowledge graphs (GraphRAG/HippoRAG).

Our system differs on both axes:

1. **We're agentic.** The MCP agent does multi-hop by *chaining tool calls* — it
   already substitutes for SAG's query-time frontier expansion.
2. **Small corpus.** SAG's incremental/scale wins over pre-built graphs are
   marginal here; our `rebuild_concepts` is cheap.
3. **Simple-but-powerful constraint.** Full SAG = MySQL + Elasticsearch + LLM
   11-type entity extraction + a query-time join/rerank engine. That's a large
   surface for our goals.

## Live evidence: the agent already does SAG-style multi-hop

Setup: 3 knowledge docs forming a 2-hop chain + the flashback-api service. The
runbook says "use the database recovery capability … roll back to a point in
time" — it **never names** flashback or `/recover`. Query: *"production incident,
a table lost rows — runbook steps + the exact internal API."*

The agent answered correctly. Its own trace:

```
search_knowledge(...)  → runbook + oracle-flashback docs
get_knowledge(runbook) → "recovery capability" (abstract, dead end alone)
get_knowledge(oracle)  → FLASHBACK TABLE (SQL, not an API)
list_concepts()        → concept "recover" spans [flashback-api, oracle-kb, runbook-kb]
get_concept("recover") → related: flashback-api::POST /recover  ← THE JOIN
get_api_detail(...)    → POST /recover confirmed
```

The bridge from runbook prose to the live endpoint was **our `concepts` layer** —
a concept that links events across domains *is* a hyperedge, and the agent
traversed it. `search_apis("flashback")` returned `[]`; the concept hyperedge,
not keyword search, carried the multi-hop.

**Conclusion:** what SAG bakes into retrieval, our (concept hyperedge + agentic
tool-chaining) already delivers for our scale — with far less machinery.

## The one idea worth borrowing (later, optional)

Our concept links are **token-substring** based (an entry joins concept `recover`
only if its text literally contains "recover"). That is brittle: a doc that says
only "roll back"/"undo" would *not* link, even though hybrid *search* now finds it
via embeddings. SAG's lesson: derive the link from **meaning**, not string match.

Cheap, in-keeping upgrade (no new infra — we already have embeddings + pgvector):
build concept/entity links from **embedding proximity** (or a light LLM tag pass)
instead of substring, so hyperedges are synonym-robust. This is the SAG insight
distilled to our scale; everything else in SAG is redundant with our agent loop.

**Measured proof of the brittleness.** Ingested a doc (`syn-kb:undo-guide`) phrased
purely in synonyms — "roll back", "undo", "revert" — never "recover":

| layer | finds `syn-kb` for a recovery query? |
|---|---|
| concept link (`get_concept "recover"`) | **No** — not linked (substring miss) |
| hybrid `search_knowledge("recover lost data")` | **Yes** — mode hybrid, returned it |

The search layer is already synonym-robust (hybrid embeddings); only the
*concept-link* layer is substring-brittle. That — and only that — is where SAG's
"link by meaning" would harden what the agent relies on for multi-hop.

## Recommendation

- **Reject** full SAG (query-time SQL hyperedge engine, 11-type entity store,
  ES+MySQL): redundant with agentic tool-chaining, over-scoped for our corpus.
- **Backlog** one item: make concept linking semantic (embedding-based) rather
  than substring, to harden the cross-domain hyperedges the agent relies on.
- Keep `concepts` + hybrid knowledge search + agentic MCP as the architecture.
