"""
Data models for wiki entries.
"""

from typing import Any
from typing import TypedDict


class ApiEntry(TypedDict, total=False):
    module: str
    api_key: str
    description: str
    method: str
    path: str
    parameters: list[dict[str, Any]]
    responses: dict[str, Any]
    tags: list[str]
