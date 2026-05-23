"""Tests for core.minio_client.MinioClient."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.minio_client import MinioClient, paper_object_key


def test_paper_object_key_shards_by_first_four_digits():
    assert paper_object_key(38000123, "xml") == "papers/3800/38000123.xml"


def test_paper_object_key_zero_pads_short_pmids():
    assert paper_object_key(12345, "pdf") == "papers/0001/12345.pdf"


def test_paper_object_key_supports_tei_extension():
    assert paper_object_key(38000123, "tei") == "papers/3800/38000123.tei"


def test_paper_object_key_rejects_unknown_extension():
    with pytest.raises(ValueError):
        paper_object_key(1, "exe")


def test_minio_client_put_object_calls_boto3():
    fake_boto = MagicMock()
    with patch("core.minio_client._build_s3_client", return_value=fake_boto):
        client = MinioClient()
        client.put_object("papers", "papers/3800/38000123.xml", b"<xml/>", "application/xml")
    fake_boto.put_object.assert_called_once()
    kwargs = fake_boto.put_object.call_args.kwargs
    assert kwargs["Bucket"] == "papers"
    assert kwargs["Key"] == "papers/3800/38000123.xml"
    assert kwargs["Body"] == b"<xml/>"
    assert kwargs["ContentType"] == "application/xml"


def test_minio_client_get_object_returns_bytes():
    fake_boto = MagicMock()
    fake_boto.get_object.return_value = {"Body": MagicMock(read=MagicMock(return_value=b"data"))}
    with patch("core.minio_client._build_s3_client", return_value=fake_boto):
        client = MinioClient()
        data = client.get_object("papers", "papers/3800/38000123.xml")
    assert data == b"data"


def test_minio_client_ensure_buckets_creates_missing(settings):
    settings.MINIO_BUCKET_PAPERS = "papers"
    settings.MINIO_BUCKET_SBML = "sbml-artifacts"
    fake_boto = MagicMock()
    fake_boto.head_bucket.side_effect = Exception("not found")
    with patch("core.minio_client._build_s3_client", return_value=fake_boto):
        client = MinioClient()
        client.ensure_buckets()
    assert fake_boto.create_bucket.call_count >= 2
