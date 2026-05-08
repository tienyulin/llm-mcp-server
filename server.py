#!/usr/bin/env python3
"""
LLM Wiki MCP Server
Reads wiki.json from Minio and exposes API documentation as MCP tools.

Every list_tools / call_tool reads fresh from Minio — no cache, always latest.
"""

import json
import logging

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from services.wiki_service import WikiService
from storage.minio_client import MinioReader

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Server("llm-wiki-mcp")


def _make_service() -> WikiService:
    """Instantiate WikiService with a fresh MinioReader (no cache by design)."""
    return WikiService(MinioReader())


# ============================================================================
# MCP Tool definitions
# ============================================================================

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    """Return the fixed set of wiki utility tools."""
    service = _make_service()
    wiki_data = service._reader.get_wiki()
    all_apis = service._all_apis(wiki_data)
    logger.info(f"list_tools: wiki has {len(all_apis)} endpoints")

    return [
        types.Tool(
            name="list_apis",
            description="List all API endpoints in the wiki, grouped by module.",
            inputSchema={
                "type": "object",
                "properties": {
                    "module": {
                        "type": "string",
                        "description": "Filter by module name (optional). Leave empty for all.",
                    },
                },
            },
        ),
        types.Tool(
            name="search_apis",
            description="Search API endpoints by keyword (path, description, or parameter name).",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search keyword",
                    },
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="get_api_detail",
            description="Get full details of a specific API endpoint.",
            inputSchema={
                "type": "object",
                "properties": {
                    "module": {
                        "type": "string",
                        "description": "Module name (e.g. 'inventory')",
                    },
                    "api_key": {
                        "type": "string",
                        "description": "API key as it appears in the wiki (e.g. 'GET /inventory/{id}')",
                    },
                },
                "required": ["module", "api_key"],
            },
        ),
    ]


# ============================================================================
# MCP Tool handlers
# ============================================================================

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    service = _make_service()

    # ------------------------------------------------------------------ #
    # list_apis
    # ------------------------------------------------------------------ #
    if name == "list_apis":
        module_filter = arguments.get("module", "")
        result = service.list_apis(module_filter)

        if not result:
            text = (
                f"No APIs found for module '{module_filter}'."
                if module_filter.strip()
                else "Wiki is empty."
            )
        else:
            lines = []
            for module, keys in result.items():
                lines.append(f"## {module}")
                for k in keys:
                    lines.append(f"  - {k}")
            text = "\n".join(lines)

        return [types.TextContent(type="text", text=text)]

    # ------------------------------------------------------------------ #
    # search_apis
    # ------------------------------------------------------------------ #
    if name == "search_apis":
        query = arguments.get("query", "").strip()
        if not query:
            return [types.TextContent(type="text", text="Please provide a search query.")]

        hits = service.search_apis(query)

        if not hits:
            text = f"No APIs found matching '{query}'."
        else:
            lines = [f"Found {len(hits)} result(s) for '{query}':\n"]
            for h in hits:
                lines.append(f"**[{h['module']}] {h['api_key']}**")
                if h.get("description"):
                    lines.append(f"  {h['description']}")
                lines.append("")
            text = "\n".join(lines)

        return [types.TextContent(type="text", text=text)]

    # ------------------------------------------------------------------ #
    # get_api_detail
    # ------------------------------------------------------------------ #
    if name == "get_api_detail":
        module = arguments.get("module", "")
        api_key = arguments.get("api_key", "")

        detail = service.get_api_detail(module, api_key)

        if detail is None:
            return [types.TextContent(
                type="text",
                text=f"API '{api_key}' not found in module '{module}'.",
            )]

        text = json.dumps(detail, ensure_ascii=False, indent=2)
        return [types.TextContent(type="text", text=text)]

    return [types.TextContent(type="text", text=f"Unknown tool: {name}")]


# ============================================================================
# Entry point
# ============================================================================

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
