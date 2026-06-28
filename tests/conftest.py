"""Shared test setup: stub the Minio SDK so no test touches the network.

MinioReader's constructor probes the bucket with urllib3 retries — against
an unreachable endpoint that costs ~10s per TestClient startup. Same
pattern as wiki-processor/tests/conftest.py.
"""

import os
from unittest.mock import MagicMock

import repository.minio_client as _minio_client

# Deliberate test monkeypatch: replace the Minio SDK class with a mock so no test
# touches the network. mypy flags assigning to a name bound to a type — expected here.
_minio_client.Minio = MagicMock()  # type: ignore[misc]

# PG is enabled by default in docker-compose, so an in-container `pytest`
# inherits PG_DSN. Force it off for hermetic unit tests — tests that exercise
# the PG read path inject a stub via app.state.pg_reader instead.
os.environ["PG_DSN"] = ""
