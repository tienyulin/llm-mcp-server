"""
WikiService: business logic for querying the API wiki.
"""

import json
import logging
import re

from models.wiki import ApiEntry
from storage.minio_client import MinioReader

logger = logging.getLogger(__name__)


class WikiService:
    """Provides list, search, and detail lookup over the API wiki."""

    def __init__(self, reader: MinioReader) -> None:
        self._reader = reader

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _all_apis(self, wiki: dict) -> list[ApiEntry]:
        """Flatten the wiki structure into a list of ApiEntry records."""
        apis: list[ApiEntry] = []
        for module, endpoints in wiki.get("apis", {}).items():
            for api_key, info in endpoints.items():
                entry: ApiEntry = {
                    "module": module,
                    "api_key": api_key,
                    **info,
                }
                apis.append(entry)
        return apis

    @staticmethod
    def _tool_name(module: str, api_key: str) -> str:
        """Convert module + API key to a valid MCP tool name."""
        raw = f"{module}__{api_key}"
        return re.sub(r"[^a-zA-Z0-9_]", "_", raw)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_apis(self, module_filter: str = "") -> dict[str, list[str]]:
        """
        Return all API keys grouped by module.

        Args:
            module_filter: if non-empty, only return the matching module (case-insensitive).

        Returns:
            dict mapping module name → list of api_key strings.
        """
        wiki = self._reader.get_wiki()
        filter_lower = module_filter.strip().lower()
        result: dict[str, list[str]] = {}
        for module, endpoints in wiki.get("apis", {}).items():
            if filter_lower and module.lower() != filter_lower:
                continue
            result[module] = list(endpoints.keys())
        return result

    def search_apis(self, query: str) -> list[ApiEntry]:
        """
        Search all API records for a keyword.

        Matches against the full JSON representation of each record
        (path, description, parameter names, etc.).

        Args:
            query: search keyword (case-insensitive).

        Returns:
            List of matching ApiEntry records.
        """
        wiki = self._reader.get_wiki()
        query_lower = query.strip().lower()
        hits: list[ApiEntry] = []
        for api in self._all_apis(wiki):
            if query_lower in json.dumps(api).lower():
                hits.append(api)
        return hits

    def get_api_detail(self, module: str, api_key: str) -> ApiEntry | None:
        """
        Return the full detail record for a specific API endpoint.

        Args:
            module:  module name (exact match).
            api_key: API key string such as 'GET /inventory/{id}'.

        Returns:
            ApiEntry dict on success, or None if not found.
        """
        wiki = self._reader.get_wiki()
        endpoints = wiki.get("apis", {}).get(module, {})
        info = endpoints.get(api_key)
        if info is None:
            return None
        return {"module": module, "api_key": api_key, **info}
