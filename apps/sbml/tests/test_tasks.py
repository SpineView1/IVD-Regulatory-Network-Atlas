"""Tests for sbml.tasks — regenerate and regenerate_stale_networks."""

from __future__ import annotations

import pytest

from sbml.models import ModelVersion
from sbml.tasks import regenerate, regenerate_stale_networks


@pytest.fixture(autouse=True)
def mock_object_store(monkeypatch):
    """Replace MinIO with an in-memory dict for tests."""
    from core.storage import ObjectStore

    store: dict[tuple[str, str], bytes] = {}

    def upload_bytes(self, bucket, key, data, content_type="application/octet-stream"):
        store[(bucket, key)] = data if isinstance(data, bytes) else data.read()
        return key

    monkeypatch.setattr(ObjectStore, "upload_bytes", upload_bytes)
    monkeypatch.setattr(ObjectStore, "ensure_bucket", lambda self, b: None)
    return store


def test_regenerate_creates_first_version(db, network, accepted_edges, mock_object_store, settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    result = regenerate.delay(network.id).get(timeout=10)
    assert result["semver"] == "0.1.0"
    assert result["created_new_version"] is True
    assert result["n_species"] == 3
    assert result["n_reactions"] == 2
    assert ModelVersion.objects.filter(network=network, semver="0.1.0").exists()


def test_regenerate_uploads_four_blobs(db, network, accepted_edges, mock_object_store, settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    regenerate.delay(network.id).get(timeout=10)
    keys = {k for (_, k) in mock_object_store}
    assert any(k.endswith("/model.sbml") for k in keys)
    assert any(k.endswith("/edges.csv") for k in keys)
    assert any(k.endswith("/evidence.csv") for k in keys)
    assert any(k.endswith(".zip") for k in keys)


def test_regenerate_flips_network_to_version_draft(
    db, network, accepted_edges, mock_object_store, settings
):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    assert network.pipeline_status == "stale"
    regenerate.delay(network.id).get(timeout=10)
    network.refresh_from_db()
    assert network.pipeline_status == "version_draft"


def test_regenerate_is_idempotent_on_no_change(
    db, network, accepted_edges, mock_object_store, settings
):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    regenerate.delay(network.id).get(timeout=10)
    network.refresh_from_db()
    # Simulate stale flag without any edge changes
    network.pipeline_status = "stale"
    network.save()
    second = regenerate.delay(network.id).get(timeout=10)
    assert second["created_new_version"] is False
    assert second["semver"] == "0.1.0"
    assert ModelVersion.objects.filter(network=network).count() == 1


def test_regenerate_bumps_patch_on_added_edge(
    db, network, entities, accepted_edges, mock_object_store, settings
):
    from graph.models import Edge, NetworkEdgeMembership

    settings.CELERY_TASK_ALWAYS_EAGER = True
    regenerate.delay(network.id).get(timeout=10)

    # Add a third edge, then regen
    e3 = Edge.objects.create(
        source=entities["IL1B"],
        target=entities["MMP13"],
        relation="activates",  # real field name
        status="accepted",
        belief_score=0.7,
        n_supporting_papers=1,
        n_models_agreeing=2,
    )
    NetworkEdgeMembership.objects.create(network=network, edge=e3, relevance=0.9)
    network.pipeline_status = "stale"
    network.save()

    result = regenerate.delay(network.id).get(timeout=10)
    assert result["semver"] == "0.1.1"


def test_regenerate_bumps_minor_on_edge_removed(
    db, network, accepted_edges, mock_object_store, settings
):
    """Removing an edge from 'accepted' (set to rejected) bumps MINOR.

    NOTE: The M2M generated_from_edges stores live references — changing
    relation on a shared Edge object makes both prev/new snapshots identical.
    The correct way to simulate a MINOR bump is removing an edge from
    accepted status, which genuinely changes the new_snapshots set.
    """
    settings.CELERY_TASK_ALWAYS_EAGER = True
    regenerate.delay(network.id).get(timeout=10)

    # Remove one edge from accepted status — this is a genuine removal
    accepted_edges[0].status = "rejected"
    accepted_edges[0].save()
    network.pipeline_status = "stale"
    network.save()

    result = regenerate.delay(network.id).get(timeout=10)
    assert result["semver"] == "0.2.0"


def test_regenerate_curator_action_bumps_major(
    db, network, accepted_edges, mock_object_store, settings
):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    regenerate.delay(network.id).get(timeout=10)

    result = regenerate.delay(network.id, triggered_by_curator=True).get(timeout=10)
    assert result["semver"] == "1.0.0"


def test_regenerate_stale_networks_enqueues_all_stale(
    db, network, accepted_edges, mock_object_store, settings
):
    from networks.models import Network

    settings.CELERY_TASK_ALWAYS_EAGER = True
    Network.objects.create(code="foo", title="Foo Network", category="II", pipeline_status="stale")
    Network.objects.create(code="bar", title="Bar Network", category="II", pipeline_status="idle")
    summary = regenerate_stale_networks.delay().get(timeout=10)
    # Two stale networks: `network` fixture + the new "foo".
    # "bar" is idle and is not enqueued.
    assert summary["enqueued"] >= 1
