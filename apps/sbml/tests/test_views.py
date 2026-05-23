"""Tests for sbml.views — download endpoint + audit."""

from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse

from sbml.models import ExportArtifact, ModelVersion


@pytest.fixture
def frozen_mv(db, network):
    mv = ModelVersion.objects.create(
        network=network,
        semver="0.1.0",
        n_species=3,
        n_reactions=2,
        n_edges=2,
        sbml_s3_key=f"{network.code}/v0.1.0/model.sbml",
        csv_s3_key=f"{network.code}/v0.1.0/edges.csv",
        evidence_csv_s3_key=f"{network.code}/v0.1.0/evidence.csv",
        zip_s3_key=f"{network.code}/v0.1.0/{network.code}_v0.1.0.zip",
    )
    mv.freeze()
    return mv


@pytest.fixture
def client_with_user() -> Client:
    return Client(
        HTTP_REMOTE_USER="fchemorion",
        HTTP_REMOTE_EMAIL="francis.chemorion@upf.edu",
    )


@pytest.fixture(autouse=True)
def mock_presign(monkeypatch):
    from core.storage import ObjectStore

    monkeypatch.setattr(
        ObjectStore,
        "presigned_download_url",
        lambda self, bucket, key, expires=None: f"https://minio.test/{bucket}/{key}?sig=abc",
    )


def test_download_zip_redirects_to_presigned_url(db, network, frozen_mv, client_with_user):
    url = reverse("sbml:download", kwargs={"code": network.code, "semver": "0.1.0"})
    resp = client_with_user.get(url)
    assert resp.status_code == 302
    assert frozen_mv.zip_s3_key in resp["Location"]


def test_download_records_export_artifact(db, network, frozen_mv, client_with_user):
    url = reverse("sbml:download", kwargs={"code": network.code, "semver": "0.1.0"})
    client_with_user.get(url)
    assert ExportArtifact.objects.filter(model_version=frozen_mv).count() == 1
    ea = ExportArtifact.objects.get(model_version=frozen_mv)
    assert ea.downloaded_by.username == "fchemorion"
    assert ea.artifact_type == "zip"


def test_download_unknown_type_returns_400(db, network, frozen_mv, client_with_user):
    url = reverse("sbml:download", kwargs={"code": network.code, "semver": "0.1.0"})
    resp = client_with_user.get(url + "?type=rar")
    assert resp.status_code == 400


def test_download_unknown_semver_returns_404(db, network, client_with_user):
    url = reverse("sbml:download", kwargs={"code": network.code, "semver": "9.9.9"})
    resp = client_with_user.get(url)
    assert resp.status_code == 404


def test_download_unfrozen_version_returns_404(db, network, client_with_user):
    ModelVersion.objects.create(
        network=network,
        semver="0.1.0",
        n_species=0,
        n_reactions=0,
        n_edges=0,
        sbml_s3_key="k",
        csv_s3_key="c",
        zip_s3_key="z",
    )  # frozen_at left NULL
    url = reverse("sbml:download", kwargs={"code": network.code, "semver": "0.1.0"})
    resp = client_with_user.get(url)
    assert resp.status_code == 404


def test_download_sbml_type_resolves_correct_key(db, network, frozen_mv, client_with_user):
    url = reverse("sbml:download", kwargs={"code": network.code, "semver": "0.1.0"})
    resp = client_with_user.get(url + "?type=sbml")
    assert resp.status_code == 302
    assert "model.sbml" in resp["Location"]


def test_download_edges_csv_type_resolves_correct_key(db, network, frozen_mv, client_with_user):
    url = reverse("sbml:download", kwargs={"code": network.code, "semver": "0.1.0"})
    resp = client_with_user.get(url + "?type=edges_csv")
    assert resp.status_code == 302
    assert "edges.csv" in resp["Location"]


def test_download_evidence_csv_type_resolves_correct_key(db, network, frozen_mv, client_with_user):
    url = reverse("sbml:download", kwargs={"code": network.code, "semver": "0.1.0"})
    resp = client_with_user.get(url + "?type=evidence_csv")
    assert resp.status_code == 302
    assert "evidence.csv" in resp["Location"]
