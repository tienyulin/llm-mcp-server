"""
Unit tests for WikiService (browsing interface).

MinioReader is mocked — these tests exercise pure business logic only.
"""

# pytest conventions: the `service` fixture is injected as a same-named param
# (redefined-outer-name) and tests white-box the mocked _minio reader (protected-access).
# pylint: disable=redefined-outer-name,protected-access

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
    """A WikiService over a stub reader serving SAMPLE_FILES."""
    mock = MagicMock()
    mock.list_files.return_value = list(SAMPLE_FILES.keys())
    mock.get_file.side_effect = SAMPLE_FILES.get
    return WikiService(mock)


# ---------------------------------------------------------------------------
# list_directory tests
# ---------------------------------------------------------------------------


def test_list_directory_root(service: WikiService) -> None:
    """Listing root surfaces both top-level files and subdirectories."""
    items = service.list_directory("/")
    names = {i["name"] for i in items}
    # Should see files at root + subdirectories
    assert "overview.md" in names
    assert "llms.txt" in names
    assert "api" in names
    assert "architecture" in names


def test_list_directory_api(service: WikiService) -> None:
    """Listing a subdir returns only its files, with no cross-dir leakage."""
    items = service.list_directory("api/")
    names = {i["name"] for i in items}
    assert "users.md" in names
    assert "orders.md" in names
    # No cross-contamination from other dirs
    assert "system.md" not in names


def test_list_directory_types(service: WikiService) -> None:
    """Entries are typed as 'file' or 'directory' correctly."""
    items = service.list_directory("/")
    types = {i["name"]: i["type"] for i in items}
    assert types["overview.md"] == "file"
    assert types["api"] == "directory"


def test_list_directory_empty(service: WikiService) -> None:
    """An empty object store yields an empty listing."""
    service._minio.list_files.return_value = []  # type: ignore[attr-defined]
    items = service.list_directory("/")
    assert items == []


# ---------------------------------------------------------------------------
# read_file tests
# ---------------------------------------------------------------------------


def test_read_file_found(service: WikiService) -> None:
    """read_file returns the stored content for an existing file."""
    content = service.read_file("overview.md")
    assert "# Overview" in content


def test_read_file_not_found(service: WikiService) -> None:
    """read_file raises FileNotFoundError when the object is missing."""
    service._minio.get_file.return_value = None  # type: ignore[attr-defined]
    with pytest.raises(FileNotFoundError):
        service.read_file("nonexistent.md")


def test_read_file_api_module(service: WikiService) -> None:
    """read_file resolves nested paths like api/users.md."""
    content = service.read_file("api/users.md")
    assert "Users API" in content


# ---------------------------------------------------------------------------
# parse_frontmatter tests
# ---------------------------------------------------------------------------


def test_parse_frontmatter_valid(service: WikiService) -> None:
    """Valid YAML frontmatter parses into a dict and the body is returned separately."""
    markdown = "---\ntitle: Test\ntype: overview\n---\n\n# Body"
    fm, body = service.parse_frontmatter(markdown)
    assert fm["title"] == "Test"
    assert fm["type"] == "overview"
    assert "# Body" in body


def test_parse_frontmatter_no_frontmatter(service: WikiService) -> None:
    """Markdown without frontmatter yields an empty dict and the original body."""
    markdown = "# Just a body"
    fm, body = service.parse_frontmatter(markdown)
    assert fm == {}
    assert body == "# Just a body"


def test_parse_frontmatter_empty_frontmatter(service: WikiService) -> None:
    """Empty frontmatter parses to an empty dict, keeping the body intact."""
    markdown = "---\n---\n\n# Body"
    fm, body = service.parse_frontmatter(markdown)
    assert fm == {}
    assert "# Body" in body
