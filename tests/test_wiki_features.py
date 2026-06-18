"""Unit tests for the wiki feature surfaces added on top of API browsing:
concepts (item 2), per-app overview (item 5), skill packaging (item 4),
knowledge graph (item 7). All pure over a wiki dict — no MinIO needed.
"""
from unittest.mock import MagicMock

import pytest

from services.wiki_service import WikiService


@pytest.fixture
def service() -> WikiService:
    return WikiService(MagicMock())


WIKI = {
    "schema_version": 2,
    "apis": {
        "flashback-api": {
            "POST /recover": {"method": "POST", "path": "/recover",
                              "description": "start recovery", "sources": ["flashback.md"],
                              "source_app": "flashback-api"},
            "GET /recover/{id}": {"method": "GET", "path": "/recover/{id}",
                                  "description": "poll recovery", "sources": ["flashback.md"],
                                  "source_app": "flashback-api"},
        },
        "inventory-api": {
            "GET /items": {"method": "GET", "path": "/items", "description": "list items",
                           "sources": ["inventory.md"], "source_app": "inventory-api"},
        },
    },
    "concepts": {
        "recover": {"description": "recovery endpoints",
                    "related": ["flashback-api::POST /recover", "flashback-api::GET /recover/{id}"],
                    "apps": ["flashback-api"]},
    },
    "overviews": {
        "flashback-api": {"text": "flashback-api: 2 endpoints.", "updated_at": "2026-06-18T00:00:00"},
    },
    "knowledge": {
        "oracle-kb:oracle-flashback": {
            "title": "Oracle Flashback", "source_app": "oracle-kb",
            "summary": "Oracle Flashback recovers data after accidental data loss.",
            "topics": ["Flashback Table"], "key_points": ["Recovers dropped rows"],
            "sources": ["oracle-flashback.md"], "source_version": "v1"},
    },
}


def test_list_concepts(service):
    out = service.list_concepts(WIKI)
    assert out["recover"]["apps"] == ["flashback-api"]
    assert out["recover"]["related_count"] == 2


def test_get_concept(service):
    assert service.get_concept("recover", WIKI)["related"]
    assert service.get_concept("missing", WIKI) is None


def test_get_overview(service):
    assert "flashback" in service.get_overview("flashback-api", WIKI)["text"]
    assert service.get_overview("nope", WIKI) is None


def test_build_skill_templates_wiki(service):
    files = service.build_skill(WIKI, name="my-expert")
    skill = files["my-expert/SKILL.md"]
    assert skill.startswith("---\nname: my-expert\n")
    assert "POST /recover" in skill and "GET /items" in skill
    # concepts present → a references file is emitted
    assert "my-expert/references/concepts.md" in files
    assert "recover" in files["my-expert/references/concepts.md"]


def test_build_skill_no_concepts(service):
    files = service.build_skill({"apis": {"a": {"GET /x": {"description": "d"}}}})
    assert any(p.endswith("SKILL.md") for p in files)
    assert not any("references" in p for p in files)


def test_list_knowledge(service):
    out = service.list_knowledge(WIKI)
    assert "oracle-kb:oracle-flashback" in out
    assert out["oracle-kb:oracle-flashback"]["source_app"] == "oracle-kb"


def test_get_knowledge(service):
    assert service.get_knowledge("oracle-kb:oracle-flashback", WIKI)["title"] == "Oracle Flashback"
    assert service.get_knowledge("nope", WIKI) is None


def test_search_knowledge_finds_data_loss(service):
    # 'data loss' appears in the summary → the Oracle doc is retrievable by it.
    hits = service.search_knowledge("data loss", WIKI)
    assert any(h["doc_id"] == "oracle-kb:oracle-flashback" for h in hits)
    assert service.search_knowledge("kubernetes", WIKI) == []


def test_build_graph_nodes_and_edges(service):
    g = service.build_graph(WIKI)
    ids = {n["id"] for n in g["nodes"]}
    assert "flashback-api::POST /recover" in ids
    assert "concept::recover" in ids

    kinds = {e["kind"] for e in g["edges"]}
    # two flashback endpoints share flashback.md -> shared_source edge
    assert "shared_source" in kinds
    # concept membership edges exist
    assert "concept" in kinds

    shared = [e for e in g["edges"] if e["kind"] == "shared_source"]
    assert all(e["weight"] == 4.0 for e in shared)
    assert any(e["via"] == "flashback.md" for e in shared)
