"""Tests for HTTP API server."""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from . import main as main_module
from .main import app

SAMPLE_WIKI = {
    "apis": {
        "inventory": {
            "GET /inventory/{id}": {"description": "Get inventory item", "method": "GET", "path": "/inventory/{id}"},
            "POST /inventory": {"description": "Create inventory item", "method": "POST", "path": "/inventory"},
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
    main_module.wiki_cache.clear()
    yield
    main_module.wiki_cache.clear()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_reader():
    reader = MagicMock()
    reader.get_wiki.return_value = SAMPLE_WIKI
    return reader


def test_health(client):
    """Test /health endpoint."""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_list_apis_all(client, mock_reader):
    """Test listing all APIs."""
    with patch("http_api.main.wiki_reader", mock_reader):
        resp = client.get("/list_apis")
        assert resp.status_code == 200
        data = resp.json()
        assert "inventory" in data["modules"]
        assert "orders" in data["modules"]


def test_list_apis_filtered(client, mock_reader):
    """Test filtering APIs by module."""
    with patch("http_api.main.wiki_reader", mock_reader):
        resp = client.get("/list_apis?module=inventory")
        assert resp.status_code == 200
        data = resp.json()
        assert "inventory" in data["modules"]
        assert len(data["modules"]["inventory"]) == 2


def test_list_apis_empty_wiki(client):
    """Test with empty wiki."""
    reader = MagicMock()
    reader.get_wiki.return_value = {"apis": {}, "metadata": {}}
    with patch("http_api.main.wiki_reader", reader):
        resp = client.get("/list_apis")
        assert resp.status_code == 404


def test_search_apis_found(client, mock_reader):
    """Test searching for APIs."""
    with patch("http_api.main.wiki_reader", mock_reader):
        resp = client.get("/search_apis?query=inventory")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] > 0
        assert len(data["results"]) > 0


def test_search_apis_no_match(client, mock_reader):
    """Test search with no matches."""
    with patch("http_api.main.wiki_reader", mock_reader):
        resp = client.get("/search_apis?query=nonexistent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0


def test_search_apis_empty_query(client, mock_reader):
    """Test search with empty query."""
    with patch("http_api.main.wiki_reader", mock_reader):
        resp = client.get("/search_apis?query=")
        assert resp.status_code == 400


def test_get_api_detail_found(client, mock_reader):
    """Test getting API detail."""
    with patch("http_api.main.wiki_reader", mock_reader):
        # Query params: module=inventory, api_key="GET /inventory/{id}"
        resp = client.get("/get_api_detail?module=inventory&api_key=GET%20/inventory/{id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["detail"] is not None


def test_get_api_detail_not_found(client, mock_reader):
    """Test getting non-existent API."""
    with patch("http_api.main.wiki_reader", mock_reader):
        resp = client.get("/get_api_detail?module=inventory&api_key=NONEXISTENT")
        assert resp.status_code == 404


def test_wiki_info(client, mock_reader):
    """Test /wiki_info endpoint."""
    with patch("http_api.main.wiki_reader", mock_reader):
        resp = client.get("/wiki_info")
        assert resp.status_code == 200
        data = resp.json()
        assert data["modules"] == 2
        assert data["total_endpoints"] == 3
