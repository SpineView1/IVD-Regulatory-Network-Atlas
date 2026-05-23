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
    """Removing an edge from 'accepted' (set to rejected) bumps MINOR."""
    settings.CELERY_TASK_ALWAYS_EAGER = True
    regenerate.delay(network.id).get(timeout=10)

    # Remove one edge from accepted status — this is a genuine removal
    accepted_edges[0].status = "rejected"
    accepted_edges[0].save()
    network.pipeline_status = "stale"
    network.save()

    result = regenerate.delay(network.id).get(timeout=10)
    assert result["semver"] == "0.2.0"


def test_regenerate_bumps_minor_on_sign_flip(
    db, network, accepted_edges, mock_object_store, settings
):
    """Changing an edge's relation (sign flip) must bump MINOR.

    This is the canonical spec §7 "MINOR on sign flip" test. It requires
    frozen_edges to work correctly: without the immutable JSON snapshot, both
    the previous and new versions would read the CURRENT (post-flip) relation
    from the live M2M FK rows, so diff_edge_sets would see no change and the
    MINOR bump would never fire.

    Flow:
      1. Regenerate v0.1.0 (edge[0] relation = "activates")
      2. Change edge[0].relation to "inhibits" in-place (same edge row)
      3. Regenerate again → prev frozen snapshot still shows "activates",
         new snapshot shows "inhibits" → sign flip detected → v0.2.0
    """
    settings.CELERY_TASK_ALWAYS_EAGER = True
    result_v1 = regenerate.delay(network.id).get(timeout=10)
    assert result_v1["semver"] == "0.1.0"

    # Flip the sign on the first edge — keep it accepted, only change relation
    accepted_edges[0].relation = "inhibits"
    accepted_edges[0].save()
    network.pipeline_status = "stale"
    network.save()

    result_v2 = regenerate.delay(network.id).get(timeout=10)

    # Must be a MINOR bump (0.1.0 → 0.2.0)
    assert result_v2["semver"] == "0.2.0", (
        f"Expected 0.2.0 (MINOR for sign flip), got {result_v2['semver']}. "
        "This would have been 0.1.0 (no change) before the frozen_edges fix."
    )
    assert result_v2["created_new_version"] is True

    # The previous version's frozen_edges must still record the original relation
    from sbml.models import ModelVersion

    v1 = ModelVersion.objects.get(network=network, semver="0.1.0")
    v1_relations = {row["relation"] for row in v1.frozen_edges}
    # v1 was frozen with "activates" — the in-place mutation must not bleed back
    assert (
        "activates" in v1_relations
    ), f"v1 frozen_edges should still have 'activates' but got: {v1_relations}"
    assert (
        "inhibits" not in v1_relations
    ), "frozen_edges were mutated by the live edge update — sign-flip isolation is broken"


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
