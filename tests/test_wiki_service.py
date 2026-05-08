"""
Unit tests for WikiService.

MinioReader is mocked — these tests exercise pure business logic only.
"""

from unittest.mock import MagicMock

import pytest

from services.wiki_service import WikiService

# ---------------------------------------------------------------------------
# Shared test fixture data
# ---------------------------------------------------------------------------

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
            "PUT /inventory/{id}": {
                "description": "Update inventory item",
                "method": "PUT",
                "path": "/inventory/{id}",
            },
        }
    },
    "metadata": {"version": "1.0"},
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def service() -> WikiService:
    """WikiService backed by a mock MinioReader returning SAMPLE_WIKI."""
    mock_reader = MagicMock()
    mock_reader.get_wiki.return_value = SAMPLE_WIKI
    return WikiService(mock_reader)


@pytest.fixture
def empty_service() -> WikiService:
    """WikiService backed by a mock MinioReader returning an empty wiki."""
    mock_reader = MagicMock()
    mock_reader.get_wiki.return_value = {"apis": {}, "metadata": {}}
    return WikiService(mock_reader)


# ---------------------------------------------------------------------------
# list_apis tests
# ---------------------------------------------------------------------------


def test_list_apis_all(service: WikiService) -> None:
    """No filter → all modules returned."""
    result = service.list_apis()
    assert set(result.keys()) == {"inventory"}
    assert "GET /inventory/{id}" in result["inventory"]
    assert "POST /inventory" in result["inventory"]
    assert "PUT /inventory/{id}" in result["inventory"]
    assert len(result["inventory"]) == 3


def test_list_apis_module_filter(service: WikiService) -> None:
    """Filter matching an existing module returns only that module."""
    result = service.list_apis("inventory")
    assert list(result.keys()) == ["inventory"]
    assert len(result["inventory"]) == 3


def test_list_apis_module_filter_case_insensitive(service: WikiService) -> None:
    """Module filter is case-insensitive."""
    result = service.list_apis("INVENTORY")
    assert "inventory" in result


def test_list_apis_module_filter_no_match(service: WikiService) -> None:
    """Filter for a non-existent module returns an empty dict."""
    result = service.list_apis("users")
    assert result == {}


def test_list_apis_empty_wiki(empty_service: WikiService) -> None:
    """Empty wiki → empty dict."""
    result = empty_service.list_apis()
    assert result == {}


# ---------------------------------------------------------------------------
# search_apis tests
# ---------------------------------------------------------------------------


def test_search_apis_found(service: WikiService) -> None:
    """Query matching a path returns at least one hit."""
    hits = service.search_apis("inventory")
    assert len(hits) > 0
    modules = {h["module"] for h in hits}
    assert "inventory" in modules


def test_search_apis_specific_path(service: WikiService) -> None:
    """Query for a unique path segment returns the correct endpoint."""
    hits = service.search_apis("Create inventory")
    assert len(hits) == 1
    assert hits[0]["api_key"] == "POST /inventory"


def test_search_apis_no_match(service: WikiService) -> None:
    """Query that matches nothing returns an empty list."""
    hits = service.search_apis("zzznomatch999")
    assert hits == []


def test_search_apis_case_insensitive(service: WikiService) -> None:
    """Search is case-insensitive."""
    hits_lower = service.search_apis("get inventory")
    hits_upper = service.search_apis("GET INVENTORY")
    assert len(hits_lower) == len(hits_upper)


# ---------------------------------------------------------------------------
# get_api_detail tests
# ---------------------------------------------------------------------------


def test_get_api_detail_found(service: WikiService) -> None:
    """Valid module + api_key returns a dict with expected fields."""
    detail = service.get_api_detail("inventory", "GET /inventory/{id}")
    assert detail is not None
    assert detail["module"] == "inventory"
    assert detail["api_key"] == "GET /inventory/{id}"
    assert detail["description"] == "Get inventory item"
    assert detail["method"] == "GET"
    assert detail["path"] == "/inventory/{id}"


def test_get_api_detail_not_found(service: WikiService) -> None:
    """Wrong api_key for a valid module returns None."""
    detail = service.get_api_detail("inventory", "DELETE /inventory/{id}")
    assert detail is None


def test_get_api_detail_wrong_module(service: WikiService) -> None:
    """Wrong module returns None even if the api_key would exist elsewhere."""
    detail = service.get_api_detail("users", "GET /inventory/{id}")
    assert detail is None


def test_get_api_detail_empty_wiki(empty_service: WikiService) -> None:
    """get_api_detail on empty wiki returns None."""
    detail = empty_service.get_api_detail("inventory", "GET /inventory/{id}")
    assert detail is None
