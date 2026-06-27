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
    # The wiki is a single-language corpus (WIKI_QUERY_LANG). Cross-language
    # retrieval of short text is weak, but same-language retrieval is strong — so
    # the calling agent translates the user's question into the corpus language
    # before searching (it is already an LLM; this is free and avoids needing a
    # large multilingual embedding model or a server-side translator).
    lang = os.getenv("WIKI_QUERY_LANG", "中文 (Chinese)")
    _xlate = (
        f"本 wiki 全部以 {lang} 撰寫，檢索是單語的（同語言命中遠強）。"
        f"呼叫 search_apis / semantic_search / search_knowledge 前，"
        f"請先把使用者的問題翻成 {lang} 再查；結果為 {lang}，回給使用者時自行譯回。"
    )
    mcp = FastMCP(
        "llm-wiki",
        instructions=_xlate,
        stateless_http=True,
        transport_security=_transport_security(),
    )
    mcp.settings.streamable_http_path = "/"  # mounted at /mcp -> live path /mcp/

    def _q(desc: str) -> str:
        """Prefix a search tool's description with the translate-first reminder."""
        return f"⚠️ query 請先翻成 {lang}（單語語料）。\n{desc}"

    @mcp.tool(description=_q(
        "Search API endpoints across the wiki (path, description, app). "
        "Returns matching {module, api_key, description} entries."))
    async def search_apis(query: str) -> str:
        results, mode = await get_query_service().search_apis(query)
        return json.dumps({"results": results, "mode": mode}, ensure_ascii=False)

    @mcp.tool(description=_q(
        "Semantic (vector) search over API endpoints; falls back to keyword "
        "search when the vector index is unavailable."))
    async def semantic_search(query: str, top_k: int = 10) -> str:
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

    @mcp.tool(description=_q(
        "Search ingested KNOWLEDGE documents (how-tos, reference material — not "
        "API specs). Use this for conceptual/how-to questions. Hybrid "
        "(semantic + keyword) so paraphrases match. Optional `type` filters by "
        "Diataxis doc_type (tutorial/how-to/reference/explanation). "
        "Returns {doc_id, title, summary, source_app, doc_type, tags} matches."))
    async def search_knowledge(query: str, type: str = "") -> str:
        results, mode = await get_query_service().search_knowledge(query, type=type)
        return json.dumps({"results": results, "mode": mode}, ensure_ascii=False)

    @mcp.tool()
    async def get_knowledge(doc_id: str) -> str:
        """Full knowledge document: title, summary, topics, key_points, provenance."""
        entry = await get_query_service().get_knowledge(doc_id)
        return json.dumps(entry, ensure_ascii=False) if entry else f"No knowledge doc: {doc_id}"

    @mcp.tool()
    async def list_knowledge(type: str = "") -> str:
        """List ingested knowledge documents ({doc_id: {title, source_app, topics,
        doc_type, tags}}). Optional `type` filters by Diataxis doc_type."""
        return json.dumps(await get_query_service().list_knowledge(type=type), ensure_ascii=False)

    # Knowledge docs are read-only reference material → also exposed as MCP
    # *resources* (idiomatic: resources = what the client can read, tools = what
    # it can do). Clients that support resources can pull a doc directly as context.
    @mcp.resource("knowledge://{doc_id}")
    async def knowledge_resource(doc_id: str) -> str:
        entry = await get_query_service().get_knowledge(doc_id)
        return json.dumps(entry, ensure_ascii=False) if entry else f"No knowledge doc: {doc_id}"

    # Authoring contract: how a producer should write source docs for THIS wiki.
    # A connected agent can read this to self-serve (no skill install needed).
    @mcp.resource("authoring-contract://source-docs")
    async def authoring_contract() -> str:
        return _AUTHORING_CONTRACT

    return mcp


_AUTHORING_CONTRACT = """\
# 源頭文件標準（怎麼寫文件餵這個 wiki）

每個 app 一律寫一份 README；能產 OpenAPI 的 app 另附最新 openapi.json（pre-commit 保持同步）。

## 語言（重要）
全部文件用專案 canonical 語言寫（預設中文，見 WIKI_QUERY_LANG）—— README 摘要、endpoint 描述
（含 OpenAPI 的 `summary=`，寫在 code 裡）、知識文件都同一種語言。wiki 是單語語料，查詢端 agent
查詢前會把問題翻成這個語言；語料混語言會讓檢索對不上。

## README frontmatter（YAML）
- type（必填）：api | tutorial | how-to | reference | explanation
- source_app（必填）：小寫+連字號
- tags（選填）：受控詞彙，小寫+連字號
## body
- H1 標題；第一段＝一句話用途/摘要（會被 embed，影響語意搜尋）。
- 沒有 openapi.json 的 app：加 Endpoints 區，每行 `METHOD /path — 用途`。
- 有 openapi.json：endpoint 交給它（不用手抄），README 專注用途/概覽。

## 知識文件
用 Diátaxis 的 type：tutorial（帶著做）/ how-to（解決問題）/ reference（查閱）/ explanation（概念）。

完整標準與 pre-commit/CI 工具見平台 docs/guides/authoring-source-docs.md。
"""
