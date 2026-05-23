"""End-to-end integration tests against a real MinIO endpoint.

These tests are SKIPPED by default (deselected via pytest.ini ``-m "not minio"``).
To run them:

  MINIO_TEST_ENDPOINT=http://localhost:9000 poetry run pytest -m minio -v

Requirements:
- A running MinIO instance at ``MINIO_TEST_ENDPOINT``
- Credentials: ``MINIO_TEST_ACCESS_KEY`` (default: ``interactome``)
             ``MINIO_TEST_SECRET_KEY`` (default: ``interactome``)
- A Django DB (bring up docker-compose postgres or use ``--reuse-db``)

The test seeds a minimal Network + edges, calls ``regenerate_network()``,
and asserts:
- Four blobs were uploaded (sbml, edges.csv, evidence.csv, zip)
- The zip is non-empty
- The download view resolves a presigned URL and records an ExportArtifact

The local compose ``minio`` service is usable.  Unit-level regenerate/storage
tests mock ObjectStore — those remain unaffected by this file.
"""

from __future__ import annotations

import os

import pytest

_MINIO_ENDPOINT = os.environ.get("MINIO_TEST_ENDPOINT", "")

pytestmark = [
    pytest.mark.minio,
    pytest.mark.skipif(
        not _MINIO_ENDPOINT,
        reason="MINIO_TEST_ENDPOINT not set; skipping real-MinIO e2e test",
    ),
]


@pytest.fixture
def real_object_store():
    """Build an ObjectStore pointed at the real MinIO test endpoint."""
    import os

    from django.test import override_settings

    endpoint = os.environ.get("MINIO_TEST_ENDPOINT", "http://localhost:9000")
    access_key = os.environ.get("MINIO_TEST_ACCESS_KEY", "interactome")
    secret_key = os.environ.get("MINIO_TEST_SECRET_KEY", "interactome")

    with override_settings(
        MINIO_ENDPOINT_URL=endpoint,
        MINIO_ACCESS_KEY=access_key,
        MINIO_SECRET_KEY=secret_key,
    ):
        # Clear lru_cache so a fresh ObjectStore is built with the test settings
        from core import storage as _storage_module

        _storage_module.get_object_store.cache_clear()
        store = _storage_module.get_object_store()
        yield store
        # Re-clear so subsequent tests don't inherit the real endpoint
        _storage_module.get_object_store.cache_clear()


def test_regenerate_uploads_blobs_to_real_minio(
    db,
    network,
    accepted_edges,
    real_object_store,
    settings,
):
    """Full regenerate pipeline against real MinIO: verifies four blobs land."""
    from sbml.models import ModelVersion
    from sbml.services import regenerate_network

    settings.CELERY_TASK_ALWAYS_EAGER = True

    result = regenerate_network(network_id=network.pk)
    assert result.created_new_version is True
    assert result.semver == "0.1.0"

    mv = ModelVersion.objects.get(network=network, semver="0.1.0")
    assert mv.frozen_at is not None

    bucket = settings.MINIO_BUCKET_SBML
    # All four blobs must exist in the real bucket
    for key in (mv.sbml_s3_key, mv.csv_s3_key, mv.evidence_csv_s3_key, mv.zip_s3_key):
        assert key, f"Expected non-empty key for {key!r}"
        assert real_object_store.object_exists(
            bucket, key
        ), f"Blob {key!r} not found in MinIO bucket {bucket!r}"

    # ZIP must be non-empty
    zip_bytes = real_object_store.download_bytes(bucket, mv.zip_s3_key)
    assert len(zip_bytes) > 100  # a zip with 4 files is at minimum a few KB


def test_download_view_presigns_url_against_real_minio(
    db,
    network,
    accepted_edges,
    real_object_store,
    settings,
):
    """Download view generates a presigned URL and records an ExportArtifact."""
    from django.test import Client

    from sbml.models import ExportArtifact
    from sbml.services import regenerate_network

    settings.CELERY_TASK_ALWAYS_EAGER = True
    regenerate_network(network_id=network.pk)

    client = Client(
        HTTP_REMOTE_USER="e2e_user",
        HTTP_REMOTE_EMAIL="e2e@test.local",
    )
    from django.urls import reverse

    url = reverse("sbml:download", kwargs={"code": network.code, "semver": "0.1.0"})
    resp = client.get(url)
    # Should redirect to a presigned MinIO URL (302)
    assert resp.status_code == 302
    location = resp["Location"]
    assert (
        location.startswith(_MINIO_ENDPOINT) or "?" in location
    ), f"Expected presigned URL, got: {location!r}"
    # Audit record created
    assert ExportArtifact.objects.filter(
        model_version__network=network,
        downloaded_by__username="e2e_user",
    ).exists()
