"""Native MCP server (Streamable HTTP), mounted on the existing FastAPI app.

The project is an MCP wiki, but the service only ever spoke REST — an MCP
stdio server existed once and was dropped (commit 0f25439) because stdio can't
be team-deployed. Streamable HTTP (MCP spec 2025-03-26) removes that tradeoff:
one HTTP server that teams deploy AND agents connect to natively. So we re-add
MCP as a thin tool layer over the SAME QueryService the REST endpoints use —
no second source of logic, no new service, no new infra.

Stateless (`stateless_http=True`): every request is self-contained, so the
read-only server scales horizontally behind a load balancer with no session
affinity (aligned with the MCP 2026 stateless-operation roadmap).

Mounted at `/mcp` in main.py; the live endpoint is `POST /mcp/`.
"""

import json
import logging
import os
from typing import Callable

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from services.query_service import QueryService

logger = logging.getLogger(__name__)


def _transport_security() -> TransportSecuritySettings:
    """DNS-rebinding protection on when MCP_ALLOWED_HOSTS is set; off otherwise
    (dev default, mirroring the keyless/mock-by-default posture). Set
    MCP_ALLOWED_HOSTS / MCP_ALLOWED_ORIGINS (comma-separated) in production."""
    hosts = [h for h in os.getenv("MCP_ALLOWED_HOSTS", "").split(",") if h]
    origins = [o for o in os.getenv("MCP_ALLOWED_ORIGINS", "").split(",") if o]
    if hosts or origins:
        return TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=hosts or ["*"],
            allowed_origins=origins or ["*"],
        )
    logger.warning("MCP: DNS-rebinding protection OFF (set MCP_ALLOWED_HOSTS in prod)")
    return TransportSecuritySettings(enable_dns_rebinding_protection=False)


def build_mcp(get_query_service: Callable[[], QueryService]) -> FastMCP:
    """Build the MCP server. `get_query_service` returns a QueryService bound to
    the live reader singletons (called per tool invocation, so it always sees
    the current app.state and the freshest cached wiki)."""
    mcp = FastMCP(
        "llm-wiki",
        stateless_http=True,
        transport_security=_transport_security(),
    )
    mcp.settings.streamable_http_path = "/"  # mounted at /mcp -> live path /mcp/

    @mcp.tool()
    async def search_apis(query: str) -> str:
        """Keyword-search API endpoints across the wiki (path, description, app).
        Returns matching {module, api_key, description} entries."""
        results, mode = await get_query_service().search_apis(query)
        return json.dumps({"results": results, "mode": mode}, ensure_ascii=False)

    @mcp.tool()
    async def semantic_search(query: str, top_k: int = 10) -> str:
        """Semantic (vector) search over API endpoints; falls back to keyword
        search when the vector index is unavailable."""
        results, mode = await get_query_service().semantic_search(query, max(1, min(top_k, 50)))
        return json.dumps({"results": results, "mode": mode}, ensure_ascii=False)

    @mcp.tool()
    async def list_apis(module: str = "") -> str:
        """List API endpoints grouped by module. Empty `module` lists all."""
        return json.dumps(await get_query_service().list_apis(module), ensure_ascii=False)

    @mcp.tool()
    async def get_api_detail(module: str, api_key: str) -> str:
        """Full detail for one endpoint (method, path, description, sources,
        provenance). `api_key` is like 'GET /items/{id}'."""
        detail = await get_query_service().get_api_detail(module, api_key)
        return json.dumps(detail, ensure_ascii=False) if detail else f"Not found: {module} {api_key}"

    @mcp.tool()
    async def list_concepts() -> str:
        """List cross-app concepts (capabilities shared across services)."""
        return json.dumps(await get_query_service().list_concepts(), ensure_ascii=False)

    @mcp.tool()
    async def get_concept(name: str) -> str:
        """A concept's description, the endpoints implementing it, and the apps
        it spans."""
        concept = await get_query_service().get_concept(name)
        return json.dumps(concept, ensure_ascii=False) if concept else f"No concept: {name}"

    @mcp.tool()
    async def get_overview(app: str) -> str:
        """The synthesized overview of one application's API surface."""
        ov = await get_query_service().get_overview(app)
        return json.dumps(ov, ensure_ascii=False) if ov else f"No overview: {app}"

    @mcp.tool()
    async def wiki_info() -> str:
        """Wiki statistics: module/endpoint counts and vector-index status."""
        return json.dumps(await get_query_service().wiki_info(), ensure_ascii=False)

    @mcp.tool()
    async def search_knowledge(query: str) -> str:
        """Search ingested KNOWLEDGE documents (Oracle, FastAPI how-tos, reference
        material — not API specs) by keyword. Use this for conceptual/how-to
        questions ('how do I…', 'what is…', 'how to recover from data loss').
        Hybrid (semantic + keyword) when the vector index is available, so
        paraphrases match too (e.g. 'undo a delete' finds a flashback doc).
        Returns {doc_id, title, summary, source_app} matches."""
        results, mode = await get_query_service().search_knowledge(query)
        return json.dumps({"results": results, "mode": mode}, ensure_ascii=False)

    @mcp.tool()
    async def get_knowledge(doc_id: str) -> str:
        """Full knowledge document: title, summary, topics, key_points, provenance."""
        entry = await get_query_service().get_knowledge(doc_id)
        return json.dumps(entry, ensure_ascii=False) if entry else f"No knowledge doc: {doc_id}"

    @mcp.tool()
    async def list_knowledge() -> str:
        """List ingested knowledge documents ({doc_id: {title, source_app, topics}})."""
        return json.dumps(await get_query_service().list_knowledge(), ensure_ascii=False)

    # Knowledge docs are read-only reference material → also exposed as MCP
    # *resources* (idiomatic: resources = what the client can read, tools = what
    # it can do). Clients that support resources can pull a doc directly as context.
    @mcp.resource("knowledge://{doc_id}")
    async def knowledge_resource(doc_id: str) -> str:
        entry = await get_query_service().get_knowledge(doc_id)
        return json.dumps(entry, ensure_ascii=False) if entry else f"No knowledge doc: {doc_id}"

    return mcp
