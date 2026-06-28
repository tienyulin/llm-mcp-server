"""Tests for HTTP API server (wiki-scan path, no PG)."""

# pytest conventions: fixtures injected as same-named params (redefined-outer-name)
# and request-only fixtures whose value is unused (unused-argument).
# pylint: disable=redefined-outer-name,unused-argument

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from http_api.main import app

SAMPLE_WIKI = {
    "apis": {
        "inventory": {
            "GET /inventory/{id}": {
                "description": "Get inventory item",
                "method": "GET",
                "path": "/inventory/{id}",
            },
            "POST /inventory": {
                "description": "Create inventory item",
                "method": "POST",
                "path": "/inventory",
            },
        },
        "orders": {
            "GET /orders": {"description": "List orders", "method": "GET", "path": "/orders"},
        },
    },
    "metadata": {"version": "1.0"},
}


@pytest.fixture(autouse=True)
def _clear_wiki_cache():
    """The read path caches the wiki; clear it so each test sees its own reader."""
    app.state.wiki_cache.clear()
    yield
    app.state.wiki_cache.clear()


@pytest.fixture
def client():
    """A TestClient bound to the shared app instance."""
    return TestClient(app)


@pytest.fixture
def mock_reader():
    """Install a stub MinioReader on app.state for the duration of a test."""
    reader = MagicMock()
    reader.get_wiki.return_value = SAMPLE_WIKI
    app.state.wiki_reader = reader
    yield reader
    app.state.wiki_reader = None


def _use_reader(reader):
    """Install a reader on app.state and return it (for inline test setup)."""
    app.state.wiki_reader = reader
    return reader


def test_health(client):
    """Test /health endpoint."""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_list_apis_all(client, mock_reader):
    """Test listing all APIs."""
    resp = client.get("/list_apis")
    assert resp.status_code == 200
    data = resp.json()
    assert "inventory" in data["modules"]
    assert "orders" in data["modules"]


def test_list_apis_filtered(client, mock_reader):
    """Test filtering APIs by module."""
    resp = client.get("/list_apis?module=inventory")
    assert resp.status_code == 200
    data = resp.json()
    assert "inventory" in data["modules"]
    assert len(data["modules"]["inventory"]) == 2


def test_list_apis_empty_wiki(client):
    """Test with empty wiki."""
    reader = MagicMock()
    reader.get_wiki.return_value = {"apis": {}, "metadata": {}}
    _use_reader(reader)
    try:
        resp = client.get("/list_apis")
        assert resp.status_code == 404
    finally:
        app.state.wiki_reader = None


def test_search_apis_found(client, mock_reader):
    """Test searching for APIs."""
    resp = client.get("/search_apis?query=inventory")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] > 0
    assert len(data["results"]) > 0


def test_search_apis_no_match(client, mock_reader):
    """Test search with no matches."""
    resp = client.get("/search_apis?query=nonexistent")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 0


def test_search_apis_empty_query(client, mock_reader):
    """Test search with empty query."""
    resp = client.get("/search_apis?query=")
    assert resp.status_code == 400


def test_get_api_detail_found(client, mock_reader):
    """Test getting API detail."""
    # Query params: module=inventory, api_key="GET /inventory/{id}"
    resp = client.get("/get_api_detail?module=inventory&api_key=GET%20/inventory/{id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["detail"] is not None


def test_get_api_detail_not_found(client, mock_reader):
    """Test getting non-existent API."""
    resp = client.get("/get_api_detail?module=inventory&api_key=NONEXISTENT")
    assert resp.status_code == 404


def test_wiki_info(client, mock_reader):
    """Test /wiki_info endpoint."""
    resp = client.get("/wiki_info")
    assert resp.status_code == 200
    data = resp.json()
    assert data["modules"] == 2
    assert data["total_endpoints"] == 3
