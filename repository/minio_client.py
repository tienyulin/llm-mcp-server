"""
MinioReader: responsible for fetching wiki files from Minio object storage.
"""

import json
import logging
import os

from minio import Minio
from minio.error import S3Error

logger = logging.getLogger(__name__)


class MinioReader:
    """Reads wiki data from Minio object storage."""

    def __init__(self) -> None:
        self._endpoint = os.getenv("MINIO_ENDPOINT", "minio:9000")
        self._access_key = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
        self._secret_key = os.getenv("MINIO_SECRET_KEY", "minioadmin")
        self._bucket = os.getenv("MINIO_BUCKET", "wiki-data")
        self._secure = False
        self._ensure_bucket()

    def _client(self) -> Minio:
        return Minio(
            self._endpoint,
            access_key=self._access_key,
            secret_key=self._secret_key,
            secure=self._secure,
        )

    def _ensure_bucket(self) -> None:
        """Ensure bucket exists, create if not."""
        client = self._client()
        try:
            if not client.bucket_exists(self._bucket):
                client.make_bucket(self._bucket)
                logger.info("Created bucket: %s", self._bucket)
            else:
                logger.debug("Bucket exists: %s", self._bucket)
        # Best-effort bootstrap probe: a transient MinIO outage here must not
        # abort reader construction — reads fall back / surface their own errors.
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning("Could not ensure bucket existence: %s", e)

    def get_file(self, path: str) -> str | None:
        """Fetch a text file from Minio. Returns None if not found."""
        client = self._client()
        try:
            obj = client.get_object(self._bucket, path)
            return obj.read().decode()
        except S3Error as e:
            if e.code == "NoSuchKey":
                return None
            raise

    def get_wiki(self) -> dict:
        """Fetch and parse wiki.json. Returns an empty wiki when missing."""
        content = self.get_file("wiki.json")
        if content is None:
            return {"apis": {}, "metadata": {}}
        return json.loads(content)

    def list_files(self, prefix: str = "") -> list[str]:
        """List all object keys under the given prefix."""
        client = self._client()
        objects = client.list_objects(self._bucket, prefix=prefix, recursive=True)
        return [obj.object_name for obj in objects]
