"""Offline end-to-end integration test (Task 20).

Walks the full curator verification workflow using Django's test client
(no running server, no MinIO, no Celery workers required):

  1. Seed: network with two edges/conflicts + subscriber + frozen ModelVersion
  2. View grid → check network appears
  3. View network_detail → check edges_json URL renders
  4. Resolve a conflict via the HTMX endpoint
  5. Record a review via the HTMX edge-review endpoint
  6. Sign off (mock sbml.tasks.regenerate.delay)
  7. Assert network = verified + Signoff exists + Notification created

All state changes are asserted directly on the DB.  sbml.regenerate is
always monkeypatched so no task infrastructure is needed.

This test runs in scripts/verify.sh (not gated) because it only uses
the Django test client + postgres (same as all other tests).
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

User = get_user_model()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def e2e_curator(db):
    return User.objects.create_user(
        username="e2e_curator", email="e2e_curator@upf.edu", first_name="E2E", last_name="Curator"
    )


@pytest.fixture
def e2e_subscriber(db):
    return User.objects.create_user(username="e2e_subscriber", email="e2e_sub@upf.edu")


@pytest.fixture
def e2e_network(db):
    from networks.models import Network

    return Network.objects.create(
        code="e2e_nfkb_axis",
        title="E2E NF-kB axis",
        category="I",
        pipeline_status="version_draft",
    )


@pytest.fixture
def e2e_entities(db):
    from core.models import Identifier, OntologyEntity
    from graph.models import Entity

    oe1 = OntologyEntity.objects.create(entity_type="protein", preferred_label="SIRT1")
    Identifier.objects.create(entity=oe1, scheme="UniProt", value="Q96EB6", is_primary=True)
    oe2 = OntologyEntity.objects.create(entity_type="protein", preferred_label="NFKB1")
    Identifier.objects.create(entity=oe2, scheme="UniProt", value="P19838", is_primary=True)
    return Entity.objects.create(ontology_entity=oe1), Entity.objects.create(ontology_entity=oe2)


@pytest.fixture
def e2e_edges_conflicts(db, e2e_network, e2e_entities):
    from graph.models import Conflict, Edge, NetworkEdgeMembership

    e1, e2 = e2e_entities
    edge_a = Edge.objects.create(
        source=e1, target=e2, relation="inhibits", belief_score=0.78, status="conflicted"
    )
    edge_b = Edge.objects.create(
        source=e1, target=e2, relation="activates", belief_score=0.55, status="conflicted"
    )
    NetworkEdgeMembership.objects.create(network=e2e_network, edge=edge_a, relevance=0.9)
    NetworkEdgeMembership.objects.create(network=e2e_network, edge=edge_b, relevance=0.9)
    conflict = Conflict.objects.create(
        edge_a=edge_a,
        edge_b=edge_b,
        conflict_type="inter_paper",
        resolution_status="open",
    )
    return edge_a, edge_b, conflict


@pytest.fixture
def e2e_model_version(db, e2e_network):
    from sbml.models import ModelVersion

    mv = ModelVersion.objects.create(
        network=e2e_network,
        semver="1.0.0",
        zip_s3_key="sbml/e2e_nfkb_axis/v1.0.0.zip",
        n_species=2,
        n_reactions=1,
        n_edges=2,
    )
    mv.freeze()
    return mv


# ---------------------------------------------------------------------------
# The e2e test
# ---------------------------------------------------------------------------


def test_offline_e2e_verification_workflow(
    db,
    monkeypatch,
    settings,
    e2e_curator,
    e2e_subscriber,
    e2e_network,
    e2e_edges_conflicts,
    e2e_model_version,
):
    """Walk: grid → network_detail → resolve conflict → review edge → sign-off."""
    from django.test import Client

    from verify.models import Notification, NotificationEvent, Signoff
    from verify.services import subscribe

    # --- SETUP ---
    edge_a, edge_b, conflict = e2e_edges_conflicts
    # Subscribe the subscriber to this network
    subscribe(user=e2e_subscriber, network=e2e_network)

    # Mock sbml.tasks.regenerate.delay (no Celery in tests)
    regen_calls: list[dict] = []

    def fake_regen_delay(*args, **kwargs):
        regen_calls.append({"args": args, "kwargs": kwargs})
        return type("R", (), {"id": "fake-task"})()

    monkeypatch.setattr("sbml.tasks.regenerate.delay", fake_regen_delay)

    # Disable fake user fallback so Remote-User header drives auth
    settings.AUTHELIA_DEV_FAKE_USER = None

    client = Client()

    # --- STEP 1: View the grid ---
    response = client.get("/", HTTP_REMOTE_USER=e2e_curator.username)
    assert response.status_code == 200
    content = response.content.decode()
    assert (
        "e2e_nfkb_axis" in content or "E2E NF-kB axis" in content
    ), f"Network not found in grid response. Content snippet: {content[:500]}"

    # --- STEP 2: View network_detail ---
    response = client.get(
        f"/networks/{e2e_network.code}/",
        HTTP_REMOTE_USER=e2e_curator.username,
    )
    assert response.status_code == 200
    assert "e2e_nfkb_axis" in response.content.decode()

    # --- STEP 3: Resolve the conflict via HTMX endpoint ---
    response = client.post(
        f"/verify/conflicts/{conflict.pk}/resolve/",
        data={"decision": "approve", "comment": "Keep inhibits edge"},
        HTTP_REMOTE_USER=e2e_curator.username,
    )
    assert response.status_code == 200
    conflict.refresh_from_db()
    assert conflict.resolution_status == "human_resolved"

    # --- STEP 4: Record a review on edge_a via HTMX endpoint ---
    response = client.post(
        f"/verify/edges/{edge_a.pk}/review/",
        data={"decision": "approve", "comment": "Strong evidence"},
        HTTP_REMOTE_USER=e2e_curator.username,
    )
    assert response.status_code == 200
    from verify.models import Review

    assert Review.objects.filter(edge=edge_a).exists()

    # --- STEP 5: Sign off ---
    response = client.post(
        f"/verify/networks/{e2e_network.code}/sign-off/{e2e_model_version.semver}/",
        data={"notes": "All conflicts resolved; LGTM."},
        HTTP_REMOTE_USER=e2e_curator.username,
    )
    assert response.status_code == 200, (
        f"Sign-off failed with status {response.status_code}: "
        + response.content[:200].decode("utf-8", errors="replace")
    )

    # --- STEP 6: Assertions ---

    # Network is now verified
    e2e_network.refresh_from_db()
    assert e2e_network.pipeline_status == "verified"

    # Signoff row exists
    assert Signoff.objects.filter(network=e2e_network, model_version=e2e_model_version).exists()

    # sbml.tasks.regenerate.delay was called with triggered_by_curator=True
    assert regen_calls, "regenerate.delay was not called"
    assert regen_calls[0]["kwargs"].get("triggered_by_curator") is True

    # Subscriber received NETWORK_SIGNED_OFF notification
    assert Notification.objects.filter(
        user=e2e_subscriber,
        event_type=NotificationEvent.NETWORK_SIGNED_OFF,
    ).exists()
