"""Native MCP server (Streamable HTTP) mounted at /mcp.

Boots the real app (TestClient context runs the lifespan → starts the MCP
session manager) and drives the JSON-RPC handshake: initialize → tools/list →
tools/call, asserting a tool answers from the same wiki the REST path serves.
"""
import json

import pytest
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

from http_api.main import create_app

SAMPLE_WIKI = {
    "schema_version": 2,
    "apis": {
        "inventory": {
            "GET /inventory/{id}": {"method": "GET", "path": "/inventory/{id}",
                                    "description": "Get inventory item",
                                    "sources": ["inv.md"], "source_app": "inventory"},
        },
    },
    "concepts": {},
    "overviews": {},
    "knowledge": {
        "oracle-kb:oracle-flashback": {
            "title": "Oracle Flashback", "source_app": "oracle-kb",
            "summary": "Oracle Flashback recovers data after accidental data loss.",
            "topics": ["Flashback Table"], "key_points": ["Recovers dropped rows"],
            "sources": ["oracle-flashback.md"], "source_version": "v1"},
    },
    "metadata": {"version": "1.0"},
}

_HDRS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def _rpc(result_text: str) -> dict:
    """Parse a streamable-HTTP response body (SSE `data:` line or raw JSON)."""
    for line in result_text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[5:])
    return json.loads(result_text)


@pytest.fixture
def client_with_wiki():
    app = create_app()
    with TestClient(app) as c:
        reader = MagicMock()
        reader.get_wiki.return_value = SAMPLE_WIKI
        app.state.wiki_reader = reader
        app.state.wiki_cache.clear()
        yield c


def _init(c):
    r = c.post("/mcp/", headers=_HDRS, json={
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                   "clientInfo": {"name": "test", "version": "0"}}})
    assert r.status_code == 200, r.text
    return r


def test_mcp_initialize(client_with_wiki):
    body = _rpc(_init(client_with_wiki).text)
    assert body["result"]["serverInfo"]["name"] == "llm-wiki"


def test_mcp_tools_list(client_with_wiki):
    _init(client_with_wiki)
    r = client_with_wiki.post("/mcp/", headers=_HDRS, json={
        "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    names = {t["name"] for t in _rpc(r.text)["result"]["tools"]}
    # core query surface exposed as MCP tools
    assert {"search_apis", "semantic_search", "list_apis", "get_api_detail",
            "list_concepts", "get_concept", "get_overview", "wiki_info",
            "search_knowledge", "get_knowledge", "list_knowledge"} <= names


def test_mcp_tool_call_search(client_with_wiki):
    _init(client_with_wiki)
    r = client_with_wiki.post("/mcp/", headers=_HDRS, json={
        "jsonrpc": "2.0", "id": 3, "method": "tools/call",
        "params": {"name": "search_apis", "arguments": {"query": "inventory"}}})
    result = _rpc(r.text)["result"]
    assert result["isError"] is False
    payload = json.loads(result["content"][0]["text"])
    assert any(e["module"] == "inventory" for e in payload["results"])


def test_mcp_tool_call_search_knowledge(client_with_wiki):
    """Cross-domain entry point: 'data loss' retrieves the Oracle flashback doc."""
    _init(client_with_wiki)
    r = client_with_wiki.post("/mcp/", headers=_HDRS, json={
        "jsonrpc": "2.0", "id": 5, "method": "tools/call",
        "params": {"name": "search_knowledge", "arguments": {"query": "data loss"}}})
    payload = json.loads(_rpc(r.text)["result"]["content"][0]["text"])
    assert any(h["doc_id"] == "oracle-kb:oracle-flashback" for h in payload["results"])


def test_mcp_tool_call_detail_has_sources(client_with_wiki):
    _init(client_with_wiki)
    r = client_with_wiki.post("/mcp/", headers=_HDRS, json={
        "jsonrpc": "2.0", "id": 4, "method": "tools/call",
        "params": {"name": "get_api_detail",
                   "arguments": {"module": "inventory", "api_key": "GET /inventory/{id}"}}})
    detail = json.loads(_rpc(r.text)["result"]["content"][0]["text"])
    assert detail["sources"] == ["inv.md"]
    assert detail["source_app"] == "inventory"
