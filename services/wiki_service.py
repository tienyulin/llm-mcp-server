"""
WikiService: file browsing interface for the Karpathy-style wiki.
"""

import logging

import yaml

from repository.minio_client import MinioReader

logger = logging.getLogger(__name__)


class WikiService:
    """Provides directory listing and file reading over the wiki stored in Minio."""

    def __init__(self, minio_client: MinioReader) -> None:
        self._minio = minio_client

    def list_directory(self, path: str = "/") -> list[dict]:
        """List files and subdirectories at the given path."""
        prefix = "" if path in ("/", "") else path.rstrip("/") + "/"

        all_keys = self._minio.list_files(prefix)

        seen_dirs: set[str] = set()
        items: list[dict] = []

        for key in all_keys:
            if key.endswith(".json"):
                continue
            # Strip the prefix to get the relative path
            relative = key[len(prefix) :]
            if not relative:
                continue

            parts = relative.split("/")
            if len(parts) > 1:
                # It's inside a subdirectory
                dir_name = parts[0]
                if dir_name not in seen_dirs:
                    seen_dirs.add(dir_name)
                    dir_path = prefix + dir_name + "/"
                    items.append({"type": "directory", "name": dir_name, "path": dir_path})
            else:
                # Direct file
                items.append({"type": "file", "name": parts[0], "path": key})

        return items

    def read_file(self, path: str) -> str:
        """Read complete file content from Minio."""
        content = self._minio.get_file(path)
        if content is None:
            raise FileNotFoundError(f"File not found: {path}")
        return content

    def list_apis(self, module: str = "", wiki: dict | None = None) -> dict[str, list[str]]:
        """List API keys grouped by module.

        Args:
            module: Optional module name filter. Empty string lists all modules.
            wiki: Pre-fetched wiki dict (e.g. from cache); fetched from Minio if omitted.

        Returns:
            {module: [api_key, ...]} — empty dict when the wiki has no matching APIs.
        """
        wiki = wiki if wiki is not None else self._minio.get_wiki()
        apis = wiki.get("apis", {})

        module = module.strip()
        if module:
            if module not in apis:
                return {}
            return {module: sorted(apis[module].keys())}

        return {name: sorted(endpoints.keys()) for name, endpoints in apis.items()}

    def search_apis(self, query: str, wiki: dict | None = None) -> list[dict]:
        """Search APIs by keyword across module name, API key, and detail fields."""
        wiki = wiki if wiki is not None else self._minio.get_wiki()
        q = query.strip().lower()

        results: list[dict] = []
        for module, endpoints in wiki.get("apis", {}).items():
            for api_key, detail in endpoints.items():
                haystack = f"{module} {api_key} {detail}".lower()
                if q in haystack:
                    results.append(
                        {
                            "module": module,
                            "api_key": api_key,
                            "description": (
                                detail.get("description", "") if isinstance(detail, dict) else ""
                            ),
                        }
                    )
        return results

    def get_api_detail(self, module: str, api_key: str, wiki: dict | None = None) -> dict | None:
        """Get full details for one API. Returns None when not found."""
        wiki = wiki if wiki is not None else self._minio.get_wiki()
        return wiki.get("apis", {}).get(module, {}).get(api_key)

    # ------------------------------------------------------------------
    # Concepts (item 2), overviews (item 5), skill (item 4), graph (item 7).
    # All pure over a wiki dict — fed the cached wiki by QueryService.
    # ------------------------------------------------------------------

    def list_concepts(self, wiki: dict) -> dict[str, dict]:
        """{concept: {description, apps, related_count}} — summary view."""
        out = {}
        for name, c in wiki.get("concepts", {}).items():
            if not isinstance(c, dict):
                continue
            out[name] = {
                "description": c.get("description", ""),
                "apps": c.get("apps", []),
                "related_count": len(c.get("related", [])),
            }
        return out

    def get_concept(self, name: str, wiki: dict) -> dict | None:
        """Full concept record (description, related, apps) or None."""
        c = wiki.get("concepts", {}).get(name)
        return c if isinstance(c, dict) else None

    def get_overview(self, app: str, wiki: dict) -> dict | None:
        """Per-app overview record {text, updated_at} or None."""
        o = wiki.get("overviews", {}).get(app)
        return o if isinstance(o, dict) else None

    def build_skill(self, wiki: dict, name: str = "wiki-expert") -> dict:
        """Package the wiki into an Anthropic Skill folder (item 4).

        Deterministic templating from wiki data — no LLM. Returns
        {file_path: content}; the caller writes or zips it.
        """
        apis = wiki.get("apis", {})
        concepts = wiki.get("concepts", {})
        files = {f"{name}/SKILL.md": self._skill_md(name, apis)}
        if concepts:
            files[f"{name}/references/concepts.md"] = self._skill_concepts_md(concepts)
        return files

    @staticmethod
    def _skill_md(name: str, apis: dict) -> str:
        """Render the SKILL.md frontmatter + per-service endpoint listing."""
        total = sum(len(e) for e in apis.values() if isinstance(e, dict))
        modules = sorted(apis)
        front = (
            "---\n"
            f"name: {name}\n"
            f"description: Answers questions about {total} API endpoint(s) across "
            f"{len(modules)} service(s): {', '.join(modules) or 'none'}. Use when a "
            "question concerns these services' APIs.\n"
            "---\n\n"
        )
        body = [f"# {name}\n", "## Services\n"]
        for module in modules:
            body.append(f"### {module}")
            for api_key, detail in sorted(apis[module].items()):
                desc = detail.get("description", "") if isinstance(detail, dict) else ""
                body.append(f"- `{api_key}` — {desc}")
            body.append("")
        return front + "\n".join(body)

    @staticmethod
    def _skill_concepts_md(concepts: dict) -> str:
        """Render the cross-cutting-concepts reference doc."""
        ref = ["# Cross-cutting concepts\n"]
        for cname, c in sorted(concepts.items()):
            if not isinstance(c, dict):
                continue
            ref.append(f"## {cname}")
            ref.append(c.get("description", ""))
            for r in c.get("related", []):
                ref.append(f"- {r}")
            ref.append("")
        return "\n".join(ref)

    # ---- Knowledge documents (prose/reference, not API specs) ----

    # `type` is the public param name (Diataxis doc_type); renaming changes the API.
    def list_knowledge(  # pylint: disable=redefined-builtin
        self, wiki: dict, type: str = "", tag: str = ""
    ) -> dict[str, dict]:
        """{doc_id: {title, source_app, topics, doc_type, tags}} — summary view.
        Optional `type` filters by Diataxis doc_type (tutorial/how-to/...);
        `tag` filters by a single tag (e.g. cronjob/worker/cli, which all share
        doc_type=reference and are only told apart by their tags)."""
        out = {}
        for doc_id, e in wiki.get("knowledge", {}).items():
            if not isinstance(e, dict):
                continue
            if type and e.get("doc_type") != type:
                continue
            if tag and tag not in (e.get("tags") or []):
                continue
            out[doc_id] = {
                "title": e.get("title", doc_id),
                "source_app": e.get("source_app", ""),
                "topics": e.get("topics", []),
                "doc_type": e.get("doc_type"),
                "tags": e.get("tags", []),
            }
        return out

    def get_knowledge(self, doc_id: str, wiki: dict) -> dict | None:
        """Full knowledge entry (title, summary, topics, key_points, provenance)."""
        e = wiki.get("knowledge", {}).get(doc_id)
        return e if isinstance(e, dict) else None

    # `type` is the public param name (Diataxis doc_type); renaming changes the API.
    def search_knowledge(  # pylint: disable=redefined-builtin
        self, query: str, wiki: dict, type: str = "", tag: str = ""
    ) -> list[dict]:
        """Keyword search across knowledge docs (title/summary/topics/key_points).
        Returns {doc_id, title, summary, source_app, doc_type, tags}. Optional
        `type` filters by Diataxis doc_type; `tag` filters by a single tag."""
        q = query.strip().lower()
        results = []
        for doc_id, e in wiki.get("knowledge", {}).items():
            if not isinstance(e, dict):
                continue
            if type and e.get("doc_type") != type:
                continue
            if tag and tag not in (e.get("tags") or []):
                continue
            hay = " ".join(
                [
                    doc_id,
                    e.get("title", ""),
                    e.get("summary", ""),
                    " ".join(e.get("topics", [])),
                    " ".join(e.get("key_points", [])),
                ]
            ).lower()
            if q in hay:
                results.append(
                    {
                        "doc_id": doc_id,
                        "title": e.get("title", doc_id),
                        "summary": e.get("summary", ""),
                        "source_app": e.get("source_app", ""),
                        "doc_type": e.get("doc_type"),
                        "tags": e.get("tags", []),
                    }
                )
        return results

    def build_graph(self, wiki: dict) -> dict:
        """Knowledge graph: API + concept nodes, weighted edges (item 7).

        Edges: concept→endpoint membership (weight 3.0, the 'direct link'
        signal) and endpoint↔endpoint shared-source overlap (weight 4.0).
        # ponytail: shared-source + concept membership only; add Adamic-Adar
        # (1.5) and Louvain communities if the graph needs richer clustering.
        """
        nodes, by_source = self._endpoint_nodes(wiki.get("apis", {}))
        edges = self._shared_source_edges(by_source)
        concept_nodes, concept_edges = self._concept_nodes_edges(wiki.get("concepts", {}))
        return {"nodes": nodes + concept_nodes, "edges": edges + concept_edges}

    @staticmethod
    def _endpoint_nodes(apis: dict) -> tuple[list[dict], dict[str, list[str]]]:
        """Endpoint nodes plus a source-file -> [node_id] index for edge building."""
        nodes: list[dict] = []
        by_source: dict[str, list[str]] = {}
        for module, endpoints in apis.items():
            if not isinstance(endpoints, dict):
                continue
            for api_key, detail in endpoints.items():
                nid = f"{module}::{api_key}"
                nodes.append({"id": nid, "type": "endpoint", "module": module})
                for src in detail.get("sources", []) if isinstance(detail, dict) else []:
                    by_source.setdefault(src, []).append(nid)
        return nodes, by_source

    @staticmethod
    def _shared_source_edges(by_source: dict[str, list[str]]) -> list[dict]:
        """Pairwise shared-source edges (weight 4.0) between co-sourced endpoints."""
        edges: list[dict] = []
        for src, members in by_source.items():
            for i, source_id in enumerate(members):
                for target_id in members[i + 1 :]:
                    edges.append(
                        {
                            "source": source_id,
                            "target": target_id,
                            "weight": 4.0,
                            "kind": "shared_source",
                            "via": src,
                        }
                    )
        return edges

    @staticmethod
    def _concept_nodes_edges(concepts: dict) -> tuple[list[dict], list[dict]]:
        """Concept nodes and their concept->endpoint membership edges (weight 3.0)."""
        nodes: list[dict] = []
        edges: list[dict] = []
        for cname, c in concepts.items():
            if not isinstance(c, dict):
                continue
            cid = f"concept::{cname}"
            nodes.append({"id": cid, "type": "concept"})
            for r in c.get("related", []):
                edges.append({"source": cid, "target": r, "weight": 3.0, "kind": "concept"})
        return nodes, edges

    def parse_frontmatter(self, markdown: str) -> tuple[dict, str]:
        """Parse YAML frontmatter from markdown. Returns (frontmatter_dict, body)."""
        if not markdown.startswith("---"):
            return {}, markdown

        end_idx = markdown.find("---", 3)
        if end_idx == -1:
            return {}, markdown

        frontmatter_str = markdown[3:end_idx].strip()
        body = markdown[end_idx + 3 :].strip()

        try:
            frontmatter = yaml.safe_load(frontmatter_str)
            return frontmatter or {}, body
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML frontmatter: {e}") from e
