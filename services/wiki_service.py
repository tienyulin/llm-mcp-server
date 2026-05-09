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
