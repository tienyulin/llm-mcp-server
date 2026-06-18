# Why a native MCP server (Streamable HTTP)

## The gap

The project is named for MCP and its premise is "LLMs consume the wiki," but the
service only ever spoke **REST**. An MCP **stdio** server existed once and was
deliberately removed (commit `0f25439`, *"simplify mcp-server to HTTP API only,
remove stdio version"*) because stdio can't be team-deployed — every user would
run their own local process. So agents couldn't connect to the shared wiki the
way the name promises; they needed a bespoke REST client.

## What changed in MCP

The choice in 2024 was binary: **stdio** (local, not deployable) *or* nothing.
The MCP spec (2025-03-26) added the **Streamable HTTP** transport — a single HTTP
endpoint that supports multiple concurrent clients, horizontal scaling, and OAuth,
and is the recommended transport for remote servers. That dissolves the original
tradeoff: one HTTP server that a team deploys **and** agents connect to natively.

## Decision

Re-add MCP as a **thin tool layer over the existing `QueryService`** — the same
logic REST uses — mounted on the existing FastAPI app at `/mcp` (live endpoint
`POST /mcp/`). No second service, no new infra, no new dependency (`mcp` was
already declared). REST stays for the web/team surface and the
`/cache/invalidate` callback; MCP serves agents.

**Stateless** (`stateless_http=True`): each request is self-contained, so the
read-only server scales horizontally behind a load balancer with no session
affinity — aligned with the MCP 2026 stateless-operation roadmap.

## Alternatives considered (and rejected)

- **Keep REST-only + the `/skill` export.** `/skill` packages the wiki into a
  *static* Anthropic Skill. Fine for distribution, but stale between rebuilds; MCP
  gives live queries against the current wiki. Keep both — different jobs.
- **Re-add stdio.** Same deployability problem that got it removed. Streamable
  HTTP strictly dominates for a shared, team-deployed wiki.
- **Bigger architectural changes** (replace the single `wiki.json`+CAS source of
  truth; swap pgvector for vectorless retrieval). Considered and declined: both are
  sound for the stated scale, and changing them adds complexity for little gain.
  The MCP gap is the high-value, low-complexity, on-mission win.

## Wiring notes (non-obvious, learned by testing)

- Official SDK (`mcp>=1.3.0`) exposes `FastMCP(...).streamable_http_app()` →
  Starlette app (this is **not** the `http_app()` of the separate FastMCP v2).
- Starlette does **not** auto-run a mounted sub-app's lifespan. The MCP session
  manager must be started by hoisting `mcp_app.router.lifespan_context(mcp_app)`
  into the parent FastAPI lifespan, else: *"Task group is not initialized."*
- The session manager is **once-per-instance**; tests that enter the lifespan
  repeatedly must build a fresh `create_app()` each time.
- Set `streamable_http_path="/"` so mounting at `/mcp` yields exactly `/mcp/`
  (otherwise the inner route nests to `/mcp/mcp`).
- DNS-rebinding protection rejects unknown `Host` headers (HTTP 421). Configure
  `MCP_ALLOWED_HOSTS` in production.

## How to verify

```bash
# 1. bring up infra + wiki-processor + mcp-server, push an app to :8001/process
# 2. handshake + call a tool over HTTP:
curl -s -X POST localhost:8002/mcp/ \
  -H 'Accept: application/json, text/event-stream' -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"cli","version":"0"}}}'
# → serverInfo.name == "llm-wiki"
# tools/list → 8 tools; tools/call get_api_detail → entry with sources[] + provenance
```
Automated: `tests/test_mcp_server.py` (initialize → tools/list → tools/call).
