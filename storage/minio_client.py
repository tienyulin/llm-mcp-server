"""
MinioReader: responsible for fetching wiki.json from Minio object storage.
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
                logger.info(f"Created bucket: {self._bucket}")
            else:
                logger.debug(f"Bucket exists: {self._bucket}")
        except Exception as e:
            logger.warning(f"Could not ensure bucket existence: {e}")

    def get_wiki(self) -> dict:
        """Fetch wiki.json from Minio. Returns empty structure if not found."""
        client = self._client()
        try:
            obj = client.get_object(self._bucket, "wiki.json")
            return json.loads(obj.read().decode())
        except S3Error as e:
            if e.code == "NoSuchKey":
                logger.warning("wiki.json not found — wiki may not be generated yet")
                return {"apis": {}, "metadata": {}}
            raise
