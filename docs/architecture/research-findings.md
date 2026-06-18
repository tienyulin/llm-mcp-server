# Architecture research findings (round 2)

Whole-architecture pass: web research + live tests + self-challenge. For
reviewers (incl. other models) to verify.

## Headline change: the wiki only held APIs

The processor extracted **API endpoints only**. The Karpathy llm-wiki premise
(and our own name/goal) is *general* knowledge: an LLM compiles prose sources
into summaries/concepts an agent reasons over. We'd narrowed it to API specs, so
the wiki couldn't answer "how do I write a FastAPI endpoint?" or "how does Oracle
Flashback recover lost data?".

**Fix (simple, additive):** a `knowledge` doc type. Prose docs → structured
`{title, summary, topics, key_points}` in `wiki.knowledge`; APIs unchanged.
`doc_type` auto-detects (endpoints → api, else knowledge). A knowledge doc that
mentions a concept token links to that concept — bridging knowledge ⇄ API.

**Live cross-domain proof.** Ingested real Oracle-Flashback + FastAPI-how-to
knowledge docs + the flashback-api service. Via Claude over MCP, asked *"I had
accidental data loss (wrong DELETE) — how do I recover, and is there an internal
API?"* The model returned: technique = Oracle Flashback (cited
`oracle-kb:oracle-flashback`), internal API = `flashback-api POST /recover`
(cited `flashback-api.md`). Abstract knowledge → concrete service, unprompted.

## Tested, not assumed

### CAS-at-scale (the highest-risk processor question)
Concurrent `/process` bursts against the live single replica:

| mode | N | success | wall p50 |
|---|---|---|---|
| distinct apps | 50 | 50/50 | 29 ms |
| **same app (max contention)** | 50 | **50/50** | 474 ms |

Single replica never exhausts the 5-retry CAS budget — the in-process write-lock
serializes phase 2 (one winner per round). Cost under same-app contention is
**latency, not failures**. **Verdict: the single-`wiki.json` + CAS source of truth
is sound at this scale; do not change it.** Watch-item: many-*replica* same-app
bursts (cross-process CAS) weren't tested here — that's where the retry budget,
not the lock, is the backstop.

### MCP wiring
Re-verified the native MCP server (added last round) still green and reachable;
added knowledge tools + a `knowledge://{doc_id}` resource. Research confirmed the
tools-vs-resources split (resources = read-only reference, tools = actions); we
do both — tools for retrieval (reliable in Claude Code), resources for direct
grounding.

## Considered and declined (keep it simple)

- **Replace single-blob+CAS** with per-app objects / DB-as-truth — CAS is fine at
  scale (tested); change adds complexity for no measured gain.
- **Vectorless (PageIndex-style) instead of pgvector** — pgvector already works and
  degrades gracefully; the corpus is small + structured. No change.
- **Two-step extraction** — kept; it measurably reduces single-pass hallucination
  per the source repos (nashsu/llm_wiki, VectifyAI/OpenKB).

## Top follow-up (not in this PR)

**Index knowledge in pgvector.** Knowledge is keyword-searchable only. In the live
run, `search_knowledge` missed the model's first phrasing and it recovered via
`list_knowledge`. Embedding knowledge entries (reusing the existing embeddings +
PG path) would make "wrong DELETE" semantically match the flashback doc. Highest-
value next step.

## How to verify

```bash
# stack up; ingest a knowledge doc + an api service; rebuild concepts
curl -s "localhost:8002/search_knowledge?query=data%20loss"      # → oracle flashback doc
curl -s "localhost:8002/get_concept?name=recover"                # → links knowledge + flashback-api
# via Claude:
claude mcp add --transport http llm-wiki http://localhost:8002/mcp/
claude -p "I had accidental data loss — how to recover, any internal API?" \
  --allowedTools mcp__llm-wiki__search_knowledge mcp__llm-wiki__get_knowledge \
                 mcp__llm-wiki__search_apis mcp__llm-wiki__get_api_detail
```
