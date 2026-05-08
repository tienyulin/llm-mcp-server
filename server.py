#!/usr/bin/env python3
"""
LLM Wiki MCP Server
Reads wiki.json from Minio and exposes API documentation as MCP tools.

Every list_tools / call_tool reads fresh from Minio — no cache, always latest.
"""

import json
import logging
import os
import re

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server
from minio import Minio
from minio.error import S3Error

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# Minio client
# ============================================================================

def get_minio_client() -> Minio:
    return Minio(
        os.getenv("MINIO_ENDPOINT", "minio:9000"),
        access_key=os.getenv("MINIO_ACCESS_KEY", "minioadmin"),
        secret_key=os.getenv("MINIO_SECRET_KEY", "minioadmin"),
        secure=os.getenv("MINIO_SECURE", "false").lower() == "true",
    )


def fetch_wiki() -> dict:
    """Read wiki.json from Minio. Always fetches latest."""
    minio = get_minio_client()
    bucket = os.getenv("MINIO_BUCKET", "wiki-data")
    try:
        obj = minio.get_object(bucket, "wiki.json")
        return json.loads(obj.read().decode())
    except S3Error as e:
        if e.code == "NoSuchKey":
            logger.warning("wiki.json not found — wiki may not be generated yet")
            return {"apis": {}, "metadata": {}}
        raise


# ============================================================================
# Tool helpers
# ============================================================================

def _tool_name(module: str, api_key: str) -> str:
    """Convert module + API key to a valid MCP tool name."""
    raw = f"{module}__{api_key}"
    return re.sub(r"[^a-zA-Z0-9_]", "_", raw)


def _all_apis(wiki: dict) -> list[dict]:
    """Flatten wiki into a list of API records."""
    apis = []
    for module, endpoints in wiki.get("apis", {}).items():
        for api_key, info in endpoints.items():
            apis.append({
                "module": module,
                "api_key": api_key,
                "tool_name": _tool_name(module, api_key),
                **info,
            })
    return apis


# ============================================================================
# MCP Server
# ============================================================================

app = Server("llm-wiki-mcp")


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    """Return one tool per API endpoint in the wiki."""
    wiki = fetch_wiki()
    tools = []

    # --- Built-in utility tools ---
    tools.append(types.Tool(
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
    ))

    tools.append(types.Tool(
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
    ))

    tools.append(types.Tool(
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
    ))

    logger.info(f"list_tools: wiki has {len(_all_apis(wiki))} endpoints")
    return tools


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    wiki = fetch_wiki()

    # ------------------------------------------------------------------ #
    # list_apis
    # ------------------------------------------------------------------ #
    if name == "list_apis":
        module_filter = arguments.get("module", "").strip().lower()
        result = {}
        for module, endpoints in wiki.get("apis", {}).items():
            if module_filter and module.lower() != module_filter:
                continue
            result[module] = list(endpoints.keys())

        if not result:
            text = f"No APIs found for module '{module_filter}'." if module_filter else "Wiki is empty."
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
        query = arguments.get("query", "").strip().lower()
        if not query:
            return [types.TextContent(type="text", text="Please provide a search query.")]

        hits = []
        for api in _all_apis(wiki):
            searchable = json.dumps(api).lower()
            if query in searchable:
                hits.append(api)

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

        endpoints = wiki.get("apis", {}).get(module, {})
        info = endpoints.get(api_key)

        if info is None:
            return [types.TextContent(
                type="text",
                text=f"API '{api_key}' not found in module '{module}'.",
            )]

        text = json.dumps({"module": module, "api": api_key, **info}, ensure_ascii=False, indent=2)
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
