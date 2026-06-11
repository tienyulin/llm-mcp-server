"""
WikiService: file browsing interface for the Karpathy-style wiki.
"""

import logging

import yaml

from storage.minio_client import MinioReader

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
            relative = key[len(prefix):]
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
                    results.append({
                        "module": module,
                        "api_key": api_key,
                        "description": detail.get("description", "") if isinstance(detail, dict) else "",
                    })
        return results

    def get_api_detail(self, module: str, api_key: str, wiki: dict | None = None) -> dict | None:
        """Get full details for one API. Returns None when not found."""
        wiki = wiki if wiki is not None else self._minio.get_wiki()
        return wiki.get("apis", {}).get(module, {}).get(api_key)

    def parse_frontmatter(self, markdown: str) -> tuple[dict, str]:
        """Parse YAML frontmatter from markdown. Returns (frontmatter_dict, body)."""
        if not markdown.startswith("---"):
            return {}, markdown

        end_idx = markdown.find("---", 3)
        if end_idx == -1:
            return {}, markdown

        frontmatter_str = markdown[3:end_idx].strip()
        body = markdown[end_idx + 3:].strip()

        try:
            frontmatter = yaml.safe_load(frontmatter_str)
            return frontmatter or {}, body
        except yaml.YAMLError as e:
            raise ValueError(f"Invalid YAML frontmatter: {e}")
