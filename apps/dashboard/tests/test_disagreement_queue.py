"""Tests for Task 11 — disagreement queue view + HTMX resolve endpoint.

Tests:
- GET /networks/<code>/queue/ lists open conflicts
- Template dashboard/disagreement_queue.html used
- conflict_card.html partial included for each conflict
- POST /verify/conflicts/<pk>/resolve/ resolves a conflict (human_resolved)
  and returns the updated conflict_card.html partial
- POST is idempotent (already-resolved conflicts return 200 with card)
- POST with invalid data returns 400
- Resolved conflicts do not appear in the open queue
"""

from __future__ import annotations

import pytest
from django.test import Client

from networks.models import Network


@pytest.fixture
def client():
    return Client(HTTP_REMOTE_USER="fchemorion")


@pytest.fixture
def network(db):
    return Network.objects.create(
        code="nfkb_axis",
        category="I",
        title="NF-κB Axis",
        pipeline_status="version_draft",
    )


@pytest.fixture
def open_conflict(db, network):
    """One open conflict with both edges in the network."""
    from core.models import OntologyEntity
    from graph.models import Conflict, Edge, Entity, NetworkEdgeMembership

    oe1 = OntologyEntity.objects.create(
        entity_type="protein",
        preferred_label="NFKB1",
        canonical_uri="https://identifiers.org/uniprot:P19838",
    )
    oe2 = OntologyEntity.objects.create(
        entity_type="protein",
        preferred_label="IKBA",
        canonical_uri="https://identifiers.org/uniprot:P25963",
    )
    e1 = Entity.objects.create(ontology_entity=oe1)
    e2 = Entity.objects.create(ontology_entity=oe2)

    edge_a = Edge.objects.create(source=e1, target=e2, relation="activates", belief_score=0.7)
    edge_b = Edge.objects.create(source=e1, target=e2, relation="inhibits", belief_score=0.6)

    NetworkEdgeMembership.objects.create(network=network, edge=edge_a)
    NetworkEdgeMembership.objects.create(network=network, edge=edge_b)

    return Conflict.objects.create(
        edge_a=edge_a,
        edge_b=edge_b,
        conflict_type="inter_paper",
        resolution_status="open",
    )


@pytest.fixture
def resolved_conflict(db, network):
    """A conflict that's already human-resolved — should not appear in queue."""
    from core.models import OntologyEntity
    from graph.models import Conflict, Edge, Entity, NetworkEdgeMembership

    oe1 = OntologyEntity.objects.create(
        entity_type="protein",
        preferred_label="TNF",
        canonical_uri="https://identifiers.org/uniprot:P01375",
    )
    oe2 = OntologyEntity.objects.create(
        entity_type="protein",
        preferred_label="TNFRSF1A",
        canonical_uri="https://identifiers.org/uniprot:P19438",
    )
    e1 = Entity.objects.create(ontology_entity=oe1)
    e2 = Entity.objects.create(ontology_entity=oe2)
    edge_a = Edge.objects.create(source=e1, target=e2, relation="activates", belief_score=0.8)
    edge_b = Edge.objects.create(source=e1, target=e2, relation="inhibits", belief_score=0.5)
    NetworkEdgeMembership.objects.create(network=network, edge=edge_a)
    NetworkEdgeMembership.objects.create(network=network, edge=edge_b)
    return Conflict.objects.create(
        edge_a=edge_a,
        edge_b=edge_b,
        conflict_type="inter_paper",
        resolution_status="human_resolved",
    )


class TestDisagreementQueueView:
    """Tests for GET /networks/<code>/queue/ (dashboard:disagreement_queue)."""

    def test_queue_returns_200(self, client, db, network, open_conflict):
        resp = client.get(f"/networks/{network.code}/queue/")
        assert resp.status_code == 200

    def test_queue_404_for_unknown_network(self, client, db):
        resp = client.get("/networks/no_such_network/queue/")
        assert resp.status_code == 404

    def test_queue_lists_open_conflicts(self, client, db, network, open_conflict):
        resp = client.get(f"/networks/{network.code}/queue/")
        template_names = [t.name for t in resp.templates]
        assert "verify/partials/conflict_card.html" in template_names

    def test_queue_uses_correct_template(self, client, db, network, open_conflict):
        resp = client.get(f"/networks/{network.code}/queue/")
        template_names = [t.name for t in resp.templates]
        assert "dashboard/disagreement_queue.html" in template_names

    def test_queue_shows_conflict_edge_labels(self, client, db, network, open_conflict):
        resp = client.get(f"/networks/{network.code}/queue/")
        body = resp.content.decode()
        assert "activates" in body
        assert "inhibits" in body

    def test_queue_does_not_show_resolved_conflicts(
        self, client, db, network, open_conflict, resolved_conflict
    ):
        resp = client.get(f"/networks/{network.code}/queue/")
        body = resp.content.decode()
        # open conflict edges appear
        assert "NFKB1" in body
        # resolved conflict entities should not appear in the queue body
        # (TNF–TNFRSF1A is the resolved pair)
        assert "TNFRSF1A" not in body

    def test_queue_empty_is_200(self, client, db, network):
        resp = client.get(f"/networks/{network.code}/queue/")
        assert resp.status_code == 200

    def test_queue_shows_network_title(self, client, db, network, open_conflict):
        resp = client.get(f"/networks/{network.code}/queue/")
        body = resp.content.decode()
        assert "NF-κB Axis" in body


class TestConflictResolveHTMXEndpoint:
    """Tests for POST /verify/conflicts/<pk>/resolve/ HTMX endpoint."""

    def test_resolve_endpoint_returns_200(self, client, db, network, open_conflict):
        resp = client.post(
            f"/verify/conflicts/{open_conflict.pk}/resolve/",
            data={"decision": "approve", "comment": "Edge A is correct"},
            HTTP_HX_REQUEST="true",
        )
        assert resp.status_code == 200

    def test_resolve_endpoint_marks_conflict_human_resolved(
        self, client, db, network, open_conflict
    ):
        client.post(
            f"/verify/conflicts/{open_conflict.pk}/resolve/",
            data={"decision": "approve", "comment": ""},
            HTTP_HX_REQUEST="true",
        )
        open_conflict.refresh_from_db()
        assert open_conflict.resolution_status == "human_resolved"

    def test_resolve_endpoint_creates_review_row(self, client, db, network, open_conflict):
        """Resolving via HTMX creates a Review record via record_review service."""
        client.post(
            f"/verify/conflicts/{open_conflict.pk}/resolve/",
            data={"decision": "approve", "comment": "looks good"},
            HTTP_HX_REQUEST="true",
        )
        from verify.models import Review

        reviews = Review.objects.filter(conflict=open_conflict)
        assert reviews.count() == 1
        first = reviews.first()
        assert first is not None
        assert first.decision == "approve"

    def test_resolve_endpoint_returns_conflict_card_partial(
        self, client, db, network, open_conflict
    ):
        """Response must be the conflict_card.html partial fragment."""
        resp = client.post(
            f"/verify/conflicts/{open_conflict.pk}/resolve/",
            data={"decision": "reject", "comment": "disagree"},
            HTTP_HX_REQUEST="true",
        )
        # Should be a small fragment, not a full page
        body = resp.content.decode()
        # Full page indicator would be <!doctype or <html>
        assert "<!doctype" not in body.lower()
        assert "<html" not in body.lower()

    def test_resolve_endpoint_404_for_unknown_conflict(self, client, db):
        resp = client.post(
            "/verify/conflicts/99999/resolve/",
            data={"decision": "approve"},
            HTTP_HX_REQUEST="true",
        )
        assert resp.status_code == 404

    def test_resolve_endpoint_requires_decision(self, client, db, network, open_conflict):
        """POST without a valid decision returns 400."""
        resp = client.post(
            f"/verify/conflicts/{open_conflict.pk}/resolve/",
            data={"decision": "", "comment": ""},
            HTTP_HX_REQUEST="true",
        )
        assert resp.status_code == 400
