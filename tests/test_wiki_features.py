"""Unit tests for the wiki feature surfaces added on top of API browsing:
concepts (item 2), per-app overview (item 5), skill packaging (item 4),
knowledge graph (item 7). All pure over a wiki dict — no MinIO needed.
"""

# pytest convention: the `service` fixture is injected as a same-named param.
# pylint: disable=redefined-outer-name

from unittest.mock import MagicMock

import pytest

from services.wiki_service import WikiService


@pytest.fixture
def service() -> WikiService:
    """A WikiService over a stub reader (feature methods are pure over the wiki dict)."""
    return WikiService(MagicMock())


WIKI = {
    "schema_version": 2,
    "apis": {
        "flashback-api": {
            "POST /recover": {
                "method": "POST",
                "path": "/recover",
                "description": "start recovery",
                "sources": ["flashback.md"],
                "source_app": "flashback-api",
            },
            "GET /recover/{id}": {
                "method": "GET",
                "path": "/recover/{id}",
                "description": "poll recovery",
                "sources": ["flashback.md"],
                "source_app": "flashback-api",
            },
        },
        "inventory-api": {
            "GET /items": {
                "method": "GET",
                "path": "/items",
                "description": "list items",
                "sources": ["inventory.md"],
                "source_app": "inventory-api",
            },
        },
    },
    "concepts": {
        "recover": {
            "description": "recovery endpoints",
            "related": ["flashback-api::POST /recover", "flashback-api::GET /recover/{id}"],
            "apps": ["flashback-api"],
        },
    },
    "overviews": {
        "flashback-api": {
            "text": "flashback-api: 2 endpoints.",
            "updated_at": "2026-06-18T00:00:00",
        },
    },
    "knowledge": {
        "oracle-kb:oracle-flashback": {
            "title": "Oracle Flashback",
            "source_app": "oracle-kb",
            "summary": "Oracle Flashback recovers data after accidental data loss.",
            "topics": ["Flashback Table"],
            "key_points": ["Recovers dropped rows"],
            "sources": ["oracle-flashback.md"],
            "source_version": "v1",
            "doc_type": "how-to",
            "tags": ["recovery"],
        },
        "fastapi-kb:howto": {
            "title": "FastAPI how-to",
            "source_app": "fastapi-kb",
            "summary": "How to build an endpoint.",
            "topics": [],
            "key_points": [],
            "doc_type": "tutorial",
            "tags": ["fastapi"],
        },
    },
}


def test_knowledge_type_filter():
    """list_knowledge/search_knowledge filter by Diataxis doc_type and surface tags."""
    svc = WikiService(None)  # type: ignore[arg-type]  # feature methods ignore the reader
    # list_knowledge filtered by Diataxis type
    assert set(svc.list_knowledge(WIKI, type="how-to")) == {"oracle-kb:oracle-flashback"}
    assert set(svc.list_knowledge(WIKI, type="tutorial")) == {"fastapi-kb:howto"}
    # entry summary view surfaces doc_type + tags
    assert svc.list_knowledge(WIKI)["oracle-kb:oracle-flashback"]["doc_type"] == "how-to"
    assert svc.list_knowledge(WIKI)["oracle-kb:oracle-flashback"]["tags"] == ["recovery"]
    # search_knowledge type filter
    hits = svc.search_knowledge("endpoint", WIKI, type="tutorial")
    assert [h["doc_id"] for h in hits] == ["fastapi-kb:howto"]
    assert not svc.search_knowledge("endpoint", WIKI, type="how-to")


def test_knowledge_tag_filter():
    """list_knowledge/search_knowledge filter by a single tag — the only way to
    tell apart components that share doc_type=reference (cronjob vs worker)."""
    svc = WikiService(None)  # type: ignore[arg-type]
    # on the module fixture, tags discriminate the two knowledge docs
    assert set(svc.list_knowledge(WIKI, tag="recovery")) == {"oracle-kb:oracle-flashback"}
    assert set(svc.list_knowledge(WIKI, tag="fastapi")) == {"fastapi-kb:howto"}
    assert not svc.list_knowledge(WIKI, tag="nonexistent")

    # the motivating case: two reference docs that differ ONLY by tag
    wiki = {
        "knowledge": {
            "billing-nightly:README": {
                "title": "Nightly Billing Job",
                "summary": "每晚對到期帳單扣款。",
                "doc_type": "reference",
                "tags": ["cronjob"],
            },
            "queue-worker:README": {
                "title": "Queue Worker",
                "summary": "消費 billing 事件並扣款。",
                "doc_type": "reference",
                "tags": ["worker"],
            },
        }
    }
    # type alone cannot separate them; tag does
    assert set(svc.list_knowledge(wiki, type="reference")) == {
        "billing-nightly:README",
        "queue-worker:README",
    }
    assert set(svc.list_knowledge(wiki, tag="cronjob")) == {"billing-nightly:README"}
    assert set(svc.list_knowledge(wiki, tag="worker")) == {"queue-worker:README"}
    # type + tag combine (AND)
    assert set(svc.list_knowledge(wiki, type="reference", tag="worker")) == {"queue-worker:README"}
    # search_knowledge honours the tag filter too
    hits = svc.search_knowledge("扣款", wiki, tag="cronjob")
    assert [h["doc_id"] for h in hits] == ["billing-nightly:README"]
    assert not svc.search_knowledge("扣款", wiki, tag="nonexistent")


def test_list_concepts(service):
    """list_concepts summarizes each concept's apps and related count."""
    out = service.list_concepts(WIKI)
    assert out["recover"]["apps"] == ["flashback-api"]
    assert out["recover"]["related_count"] == 2


def test_get_concept(service):
    """get_concept returns the full record for a known concept, None otherwise."""
    assert service.get_concept("recover", WIKI)["related"]
    assert service.get_concept("missing", WIKI) is None


def test_get_overview(service):
    """get_overview returns a known app's overview text, None for unknown apps."""
    assert "flashback" in service.get_overview("flashback-api", WIKI)["text"]
    assert service.get_overview("nope", WIKI) is None


def test_build_skill_templates_wiki(service):
    """build_skill emits a SKILL.md plus a concepts reference when concepts exist."""
    files = service.build_skill(WIKI, name="my-expert")
    skill = files["my-expert/SKILL.md"]
    assert skill.startswith("---\nname: my-expert\n")
    assert "POST /recover" in skill and "GET /items" in skill
    # concepts present → a references file is emitted
    assert "my-expert/references/concepts.md" in files
    assert "recover" in files["my-expert/references/concepts.md"]


def test_build_skill_no_concepts(service):
    """With no concepts, build_skill emits only SKILL.md (no references file)."""
    files = service.build_skill({"apis": {"a": {"GET /x": {"description": "d"}}}})
    assert any(p.endswith("SKILL.md") for p in files)
    assert not any("references" in p for p in files)


def test_list_knowledge(service):
    """list_knowledge surfaces each doc with its source_app."""
    out = service.list_knowledge(WIKI)
    assert "oracle-kb:oracle-flashback" in out
    assert out["oracle-kb:oracle-flashback"]["source_app"] == "oracle-kb"


def test_get_knowledge(service):
    """get_knowledge returns a known doc's full record, None otherwise."""
    assert service.get_knowledge("oracle-kb:oracle-flashback", WIKI)["title"] == "Oracle Flashback"
    assert service.get_knowledge("nope", WIKI) is None


def test_search_knowledge_finds_data_loss(service):
    """A summary-only term ('data loss') retrieves the Oracle doc; misses return nothing."""
    # 'data loss' appears in the summary → the Oracle doc is retrievable by it.
    hits = service.search_knowledge("data loss", WIKI)
    assert any(h["doc_id"] == "oracle-kb:oracle-flashback" for h in hits)
    assert not service.search_knowledge("kubernetes", WIKI)


def test_build_graph_nodes_and_edges(service):
    """build_graph emits endpoint+concept nodes and shared-source/concept edges."""
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
