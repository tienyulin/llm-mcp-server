"""Query-side embeddings for semantic search.

mock_embed is a BYTE-IDENTICAL copy of
wiki-processor/services/embeddings/mock.py — query vectors must live in the
same space as the index vectors written by the processor. Golden-value tests
in both suites (tests/test_embeddings.py here and in wiki-processor) pin the
algorithm; change both copies together.

The per-service duplication follows the repo's storage precedent
(MinioStorage vs MinioReader): each service owns a copy tailored to its
role — the processor batches entry texts, this side embeds one query string.
"""

import hashlib
import logging
import math
import os
import re

import httpx

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def mock_embed(text: str, dim: int) -> list[float]:
    """Map text to a deterministic L2-normalized vector of length dim."""
    vec = [0.0] * dim
    for token in _TOKEN_RE.findall(text.lower()):
        h = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        idx = int.from_bytes(h[:4], "big") % dim
        sign = 1.0 if h[4] & 1 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(c * c for c in vec))
    if norm == 0.0:
        vec[0] = 1.0
        return vec
    return [c / norm for c in vec]


class QueryEmbedder:
    """Embeds a single query string via the same endpoint/env vars as the
    processor (EMBEDDING_BASE_URL/_API_KEY/_MODEL/_DIM, MOCK_EMBEDDINGS)."""

    def __init__(self):
        self.base_url = (os.getenv("EMBEDDING_BASE_URL") or "").rstrip("/")
        self.api_key = os.getenv("EMBEDDING_API_KEY", "")
        self.model = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
        self.dim = int(os.getenv("EMBEDDING_DIM", "1536"))
        self.timeout = float(os.getenv("EMBEDDING_TIMEOUT", "30"))
        self.mock_mode = os.getenv("MOCK_EMBEDDINGS", "false").lower() == "true"

    def is_enabled(self) -> bool:
        return self.mock_mode or bool(self.base_url)

    async def aembed_query(self, text: str) -> list[float]:
        if self.mock_mode:
            return mock_embed(text, self.dim)

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/v1/embeddings",
                headers=headers,
                json={"model": self.model, "input": [text]},
            )
            response.raise_for_status()
            vec = response.json()["data"][0]["embedding"]
        if len(vec) != self.dim:
            raise ValueError(
                f"Embedding dimension mismatch: expected {self.dim}, got {len(vec)}"
            )
        return vec


def query_embedder_from_env() -> QueryEmbedder | None:
    embedder = QueryEmbedder()
    return embedder if embedder.is_enabled() else None
