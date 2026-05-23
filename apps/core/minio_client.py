"""MinIO / S3-compatible blob storage wrapper.

Holds the PMID-prefix sharding scheme and the small set of buckets the
project uses. Boto3 is used for the wire protocol; MinIO speaks S3.

(per spec §5 storage table — papers/<pmid_prefix>/<pmid>.{xml,pdf,tei})
"""

from __future__ import annotations

import logging
from typing import Any

import boto3
from botocore.client import Config
from django.conf import settings

logger = logging.getLogger(__name__)

ALLOWED_PAPER_EXTENSIONS = {"xml", "pdf", "tei", "json"}


def paper_object_key(pmid: int, extension: str) -> str:
    """Return the canonical object key for a paper artifact.

    Sharding: first 4 digits of the zero-padded PMID. PMID 12345 →
    "papers/0001/12345.pdf"; PMID 38000123 → "papers/3800/38000123.xml".
    """
    if extension not in ALLOWED_PAPER_EXTENSIONS:
        raise ValueError(f"unknown extension {extension!r}")
    padded = f"{pmid:08d}"
    prefix = padded[:4]
    return f"papers/{prefix}/{pmid}.{extension}"


def _build_s3_client() -> Any:
    return boto3.client(
        "s3",
        endpoint_url=settings.MINIO_ENDPOINT_URL,
        aws_access_key_id=settings.MINIO_ACCESS_KEY,
        aws_secret_access_key=settings.MINIO_SECRET_KEY,
        region_name=settings.MINIO_REGION,
        config=Config(signature_version="s3v4"),
    )


class MinioClient:
    """Thin facade over boto3. One instance per worker process is fine."""

    def __init__(self) -> None:
        self._s3 = _build_s3_client()

    def put_object(
        self,
        bucket: str,
        key: str,
        body: bytes,
        content_type: str,
    ) -> None:
        self._s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
        )

    def get_object(self, bucket: str, key: str) -> bytes:
        response = self._s3.get_object(Bucket=bucket, Key=key)
        return response["Body"].read()

    def object_exists(self, bucket: str, key: str) -> bool:
        try:
            self._s3.head_object(Bucket=bucket, Key=key)
            return True
        except Exception:
            return False

    def ensure_buckets(self) -> None:
        """Create the project's buckets if they don't exist (idempotent)."""
        for bucket in (settings.MINIO_BUCKET_PAPERS, settings.MINIO_BUCKET_SBML):
            try:
                self._s3.head_bucket(Bucket=bucket)
            except Exception:
                logger.info("creating bucket %s", bucket)
                self._s3.create_bucket(Bucket=bucket)
