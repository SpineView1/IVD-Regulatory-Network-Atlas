"""MinIO / S3 client wrapper — single entry point for every blob the system writes.

* Paper full-text (PMC JATS XML, GROBID TEI, PDFs) — written by ``papers`` app
* SBML artifacts and per-version ZIPs — written by ``sbml`` app
* (Future) GROBID intermediate outputs, large LLM responses

**Integration with existing MinioClient:**
``core.minio_client.MinioClient`` (Phase 1) is the existing per-task singleton used
by the papers pipeline. It remains the authoritative API for paper blobs.
``ObjectStore`` here is the *Phase 4 extension* that adds:

- Fine-grained ``ensure_bucket()`` (idempotent, per-bucket)
- ``upload_bytes()`` convenience (replaces raw ``put_object`` calls)
- ``presigned_download_url()`` for the sbml download view
- ``download_bytes()`` helper
- ``object_exists()`` with proper 404 detection

Internally both classes share the same boto3 construction arguments (reading
``settings.MINIO_ENDPOINT_URL`` / ``MINIO_ACCESS_KEY`` / ``MINIO_SECRET_KEY`` /
``MINIO_REGION``).  We do NOT create a second boto3 ``client`` call path — this
module exposes ``get_object_store()`` (lru_cache singleton); the sbml app uses
that.  The papers pipeline keeps using ``core.minio_client.MinioClient`` directly
and is unaffected.

Wrapping ``boto3`` here means consumers never see boto3 directly, and we can swap
to ``minio-py`` or a different backend without touching call sites.  Matches spec
§1 ("Object keys stored in Postgres rows").
"""

from __future__ import annotations

import functools
from typing import BinaryIO

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from django.conf import settings


class ObjectStore:
    """Thin wrapper over a boto3 S3 client pointed at MinIO.

    ``client`` is exposed as a public attribute so tests can monkeypatch
    individual methods without replacing the whole boto3 layer.
    """

    def __init__(self) -> None:
        # Use the same setting key as core.minio_client._build_s3_client so
        # both paths resolve to the same MinIO endpoint.
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.MINIO_ENDPOINT_URL,
            aws_access_key_id=settings.MINIO_ACCESS_KEY,
            aws_secret_access_key=settings.MINIO_SECRET_KEY,
            region_name=settings.MINIO_REGION,
            config=Config(signature_version="s3v4"),
        )

    def ensure_bucket(self, bucket: str) -> None:
        """Idempotent bucket creation.  Safe to call on every task start."""
        try:
            self.client.head_bucket(Bucket=bucket)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in {"404", "NoSuchBucket", "NotFound"}:
                self.client.create_bucket(Bucket=bucket)
            else:
                raise

    def upload_bytes(
        self,
        bucket: str,
        key: str,
        data: bytes | BinaryIO,
        *,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Write bytes (or a file-like) to *bucket/key*.  Returns *key* for chaining."""
        self.client.put_object(
            Bucket=bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        return key

    def download_bytes(self, bucket: str, key: str) -> bytes:
        """Fetch the full body of *bucket/key* as bytes."""
        obj = self.client.get_object(Bucket=bucket, Key=key)
        return obj["Body"].read()

    def object_exists(self, bucket: str, key: str) -> bool:
        """Return ``True`` iff *bucket/key* exists (HEAD request)."""
        try:
            self.client.head_object(Bucket=bucket, Key=key)
            return True
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise

    def presigned_download_url(
        self,
        bucket: str,
        key: str,
        *,
        expires: int | None = None,
    ) -> str:
        """Return a time-limited GET URL.

        *expires* defaults to ``settings.MINIO_PRESIGN_EXPIRY_SECONDS`` when
        not specified.
        """
        expiry = expires if expires is not None else settings.MINIO_PRESIGN_EXPIRY_SECONDS
        return self.client.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expiry,
        )


@functools.lru_cache(maxsize=1)
def get_object_store() -> ObjectStore:
    """Module-level singleton — boto3 clients are thread-safe and expensive
    to construct, so we share one per worker process."""
    return ObjectStore()
