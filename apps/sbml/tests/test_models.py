"""Tests for sbml.models — ModelVersion and ExportArtifact."""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from sbml.models import ExportArtifact, ModelVersion


def test_model_version_unique_per_network_semver(db, network, accepted_edges):
    ModelVersion.objects.create(
        network=network,
        semver="0.1.0",
        n_species=2,
        n_reactions=1,
        n_edges=2,
        sbml_s3_key="k1",
        csv_s3_key="c1",
        zip_s3_key="z1",
    )
    with pytest.raises(IntegrityError):
        ModelVersion.objects.create(
            network=network,
            semver="0.1.0",
            n_species=2,
            n_reactions=1,
            n_edges=2,
            sbml_s3_key="k2",
            csv_s3_key="c2",
            zip_s3_key="z2",
        )


def test_model_version_starts_unfrozen(db, network):
    mv = ModelVersion.objects.create(
        network=network,
        semver="0.1.0",
        n_species=0,
        n_reactions=0,
        n_edges=0,
        sbml_s3_key="",
        csv_s3_key="",
        zip_s3_key="",
    )
    assert mv.frozen_at is None


def test_model_version_freeze_sets_timestamp(db, network):
    mv = ModelVersion.objects.create(
        network=network,
        semver="0.1.0",
        n_species=0,
        n_reactions=0,
        n_edges=0,
        sbml_s3_key="",
        csv_s3_key="",
        zip_s3_key="",
    )
    mv.freeze()
    assert mv.frozen_at is not None


def test_model_version_freeze_is_idempotent(db, network):
    mv = ModelVersion.objects.create(
        network=network,
        semver="0.1.0",
        n_species=0,
        n_reactions=0,
        n_edges=0,
        sbml_s3_key="",
        csv_s3_key="",
        zip_s3_key="",
    )
    mv.freeze()
    first = mv.frozen_at
    mv.freeze()
    assert mv.frozen_at == first


def test_model_version_rejects_invalid_semver(db, network):
    mv = ModelVersion(
        network=network,
        semver="not-a-version",
        n_species=0,
        n_reactions=0,
        n_edges=0,
        sbml_s3_key="",
        csv_s3_key="",
        zip_s3_key="",
    )
    with pytest.raises(ValidationError):
        mv.full_clean()


def test_model_version_generated_from_edges_m2m(db, network, accepted_edges):
    mv = ModelVersion.objects.create(
        network=network,
        semver="0.1.0",
        n_species=3,
        n_reactions=2,
        n_edges=2,
        sbml_s3_key="k",
        csv_s3_key="c",
        zip_s3_key="z",
    )
    mv.generated_from_edges.set(accepted_edges)
    assert mv.generated_from_edges.count() == 2


def test_model_version_latest_for_network(db, network):
    for v in ["0.1.0", "0.1.1", "0.2.0", "1.0.0"]:
        ModelVersion.objects.create(
            network=network,
            semver=v,
            n_species=0,
            n_reactions=0,
            n_edges=0,
            sbml_s3_key="",
            csv_s3_key="",
            zip_s3_key="",
        )
    latest = ModelVersion.latest_for(network)
    assert latest is not None
    assert latest.semver == "1.0.0"


def test_model_version_frozen_edges_default_empty(db, network):
    """frozen_edges defaults to an empty list."""
    mv = ModelVersion.objects.create(
        network=network,
        semver="0.1.0",
        n_species=0,
        n_reactions=0,
        n_edges=0,
        sbml_s3_key="",
        csv_s3_key="",
        zip_s3_key="",
    )
    assert mv.frozen_edges == []


def test_model_version_frozen_edges_stored_and_retrieved(db, network):
    """frozen_edges JSON is round-tripped through the DB correctly."""
    snapshot = [
        {"edge_id": 1, "source_id": 10, "target_id": 20, "relation": "activates"},
        {"edge_id": 2, "source_id": 10, "target_id": 30, "relation": "inhibits"},
    ]
    mv = ModelVersion.objects.create(
        network=network,
        semver="0.1.0",
        n_species=0,
        n_reactions=0,
        n_edges=0,
        sbml_s3_key="",
        csv_s3_key="",
        zip_s3_key="",
        frozen_edges=snapshot,
    )
    mv.refresh_from_db()
    assert mv.frozen_edges == snapshot


def test_export_artifact_records_download(db, network, reviewer):
    mv = ModelVersion.objects.create(
        network=network,
        semver="0.1.0",
        n_species=0,
        n_reactions=0,
        n_edges=0,
        sbml_s3_key="",
        csv_s3_key="",
        zip_s3_key="z",
    )
    ea = ExportArtifact.objects.create(
        model_version=mv,
        downloaded_by=reviewer,
        artifact_type="zip",
        s3_key="z",
    )
    assert ea.downloaded_at is not None
    assert ea.artifact_type == "zip"


def test_export_artifact_type_constrained(db, network, reviewer):
    mv = ModelVersion.objects.create(
        network=network,
        semver="0.1.0",
        n_species=0,
        n_reactions=0,
        n_edges=0,
        sbml_s3_key="",
        csv_s3_key="",
        zip_s3_key="z",
    )
    ea = ExportArtifact(
        model_version=mv,
        downloaded_by=reviewer,
        artifact_type="rar",
        s3_key="z",
    )
    with pytest.raises(ValidationError):
        ea.full_clean()
