"""Tests for core.storage — MinIO S3 client wrapper."""

from __future__ import annotations

import pytest
from botocore.exceptions import ClientError

from core.storage import ObjectStore, get_object_store


@pytest.fixture
def store() -> ObjectStore:
    # Reset the lru_cache so we get a fresh instance for each test that calls
    # get_object_store() directly, but the fixture returns a bare instance
    # so monkeypatching works without sharing state between tests.
    return ObjectStore()


def test_get_object_store_returns_singleton() -> None:
    get_object_store.cache_clear()
    a = get_object_store()
    b = get_object_store()
    assert a is b
    get_object_store.cache_clear()


def test_ensure_bucket_creates_when_missing(
    store: ObjectStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    created: list[str] = []

    def fake_head(Bucket: str) -> dict:  # noqa: ARG001 (never returns — raises)
        raise ClientError({"Error": {"Code": "404"}}, "HeadBucket")

    def fake_create(Bucket: str) -> dict:
        created.append(Bucket)
        return {"Location": f"/{Bucket}"}

    monkeypatch.setattr(store.client, "head_bucket", fake_head)
    monkeypatch.setattr(store.client, "create_bucket", fake_create)
    store.ensure_bucket("test-bucket")
    assert created == ["test-bucket"]


def test_ensure_bucket_no_op_when_exists(
    store: ObjectStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    created: list[str] = []
    monkeypatch.setattr(store.client, "head_bucket", lambda Bucket: {})
    monkeypatch.setattr(store.client, "create_bucket", lambda Bucket: created.append(Bucket))
    store.ensure_bucket("test-bucket")
    assert created == []


def test_upload_bytes_uses_correct_bucket_and_key(
    store: ObjectStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict] = []

    def fake_put(**kw: object) -> dict:
        calls.append(dict(kw))
        return {"ETag": '"abc"'}

    monkeypatch.setattr(store.client, "put_object", fake_put)
    store.upload_bytes("buk", "k/p", b"hello", content_type="text/plain")
    assert calls[0]["Bucket"] == "buk"
    assert calls[0]["Key"] == "k/p"
    assert calls[0]["Body"] == b"hello"
    assert calls[0]["ContentType"] == "text/plain"


def test_presigned_url_includes_expiry(store: ObjectStore, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_generate(ClientMethod: str, Params: dict, ExpiresIn: int) -> str:
        captured.update(method=ClientMethod, params=Params, expires=ExpiresIn)
        return "https://minio/signed?token=xyz"

    monkeypatch.setattr(store.client, "generate_presigned_url", fake_generate)
    url = store.presigned_download_url("buk", "k/p", expires=600)
    assert url == "https://minio/signed?token=xyz"
    assert captured["expires"] == 600
    assert captured["params"] == {"Bucket": "buk", "Key": "k/p"}
    assert captured["method"] == "get_object"


def test_object_exists_true_when_head_succeeds(
    store: ObjectStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(store.client, "head_object", lambda **kw: {"ETag": '"x"'})
    assert store.object_exists("b", "k") is True


def test_object_exists_false_on_404(store: ObjectStore, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_head(**kw: object) -> None:
        raise ClientError({"Error": {"Code": "404"}}, "HeadObject")

    monkeypatch.setattr(store.client, "head_object", fake_head)
    assert store.object_exists("b", "k") is False
