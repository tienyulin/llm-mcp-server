"""Shared test setup: stub the Minio SDK so no test touches the network.

MinioReader's constructor probes the bucket with urllib3 retries — against
an unreachable endpoint that costs ~10s per TestClient startup. Same
pattern as wiki-processor/tests/conftest.py.
"""
from unittest.mock import MagicMock

import storage.minio_client as _minio_client

_minio_client.Minio = MagicMock()
