"""
Unit tests for WikiService (browsing interface).

MinioReader is mocked — these tests exercise pure business logic only.
"""

from unittest.mock import MagicMock

import pytest

from services.wiki_service import WikiService

# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLE_FILES = {
    "overview.md": "---\ntitle: Overview\ntype: overview\n---\n\n# Overview",
    "llms.txt": "---\ntitle: Index\ntype: overview\n---\n\n# Index",
    "api/users.md": "---\ntitle: Users\ntype: api_module\n---\n\n# Users API",
    "api/orders.md": "---\ntitle: Orders\ntype: api_module\n---\n\n# Orders API",
    "architecture/system.md": "---\ntitle: System\ntype: architecture\n---\n\n# System",
}


@pytest.fixture
def service() -> WikiService:
    mock = MagicMock()
    mock.list_files.return_value = list(SAMPLE_FILES.keys())
    mock.get_file.side_effect = lambda path: SAMPLE_FILES.get(path)
    return WikiService(mock)


# ---------------------------------------------------------------------------
# list_directory tests
# ---------------------------------------------------------------------------


def test_list_directory_root(service: WikiService) -> None:
    items = service.list_directory("/")
    names = {i["name"] for i in items}
    # Should see files at root + subdirectories
    assert "overview.md" in names
    assert "llms.txt" in names
    assert "api" in names
    assert "architecture" in names


def test_list_directory_api(service: WikiService) -> None:
    items = service.list_directory("api/")
    names = {i["name"] for i in items}
    assert "users.md" in names
    assert "orders.md" in names
    # No cross-contamination from other dirs
    assert "system.md" not in names


def test_list_directory_types(service: WikiService) -> None:
    items = service.list_directory("/")
    types = {i["name"]: i["type"] for i in items}
    assert types["overview.md"] == "file"
    assert types["api"] == "directory"


def test_list_directory_empty(service: WikiService) -> None:
    service._minio.list_files.return_value = []
    items = service.list_directory("/")
    assert items == []


# ---------------------------------------------------------------------------
# read_file tests
# ---------------------------------------------------------------------------


def test_read_file_found(service: WikiService) -> None:
    content = service.read_file("overview.md")
    assert "# Overview" in content


def test_read_file_not_found(service: WikiService) -> None:
    service._minio.get_file.return_value = None
    with pytest.raises(FileNotFoundError):
        service.read_file("nonexistent.md")


def test_read_file_api_module(service: WikiService) -> None:
    content = service.read_file("api/users.md")
    assert "Users API" in content


# ---------------------------------------------------------------------------
# parse_frontmatter tests
# ---------------------------------------------------------------------------


def test_parse_frontmatter_valid(service: WikiService) -> None:
    markdown = "---\ntitle: Test\ntype: overview\n---\n\n# Body"
    fm, body = service.parse_frontmatter(markdown)
    assert fm["title"] == "Test"
    assert fm["type"] == "overview"
    assert "# Body" in body


def test_parse_frontmatter_no_frontmatter(service: WikiService) -> None:
    markdown = "# Just a body"
    fm, body = service.parse_frontmatter(markdown)
    assert fm == {}
    assert body == "# Just a body"


def test_parse_frontmatter_empty_frontmatter(service: WikiService) -> None:
    markdown = "---\n---\n\n# Body"
    fm, body = service.parse_frontmatter(markdown)
    assert fm == {}
    assert "# Body" in body
