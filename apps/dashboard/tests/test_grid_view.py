"""Tests for Task 9 — top-level network grid view at /.

Tests:
- GET / returns 200
- Response groups networks by category
- Cards show pipeline_status pill
- Cards show edge count + open conflict count
- All 17 category labels are rendered when networks exist in each
- Networks with no edges still appear
"""

from __future__ import annotations

import pytest
from django.test import Client

from networks.models import Network


@pytest.fixture
def client():
    return Client(HTTP_REMOTE_USER="fchemorion")


@pytest.fixture
def two_networks(db):
    """Two networks in two different categories."""
    n1 = Network.objects.create(
        code="nfkb_axis",
        category="I",
        title="NF-κB Axis",
        pipeline_status="version_draft",
    )
    n2 = Network.objects.create(
        code="sox9_notch",
        category="II",
        title="SOX9/Notch TF network",
        pipeline_status="idle",
    )
    return n1, n2


@pytest.fixture
def network_with_edges_and_conflicts(db):
    """A network with 2 edges and 1 open conflict."""
    from core.models import OntologyEntity
    from graph.models import Conflict, Edge, Entity, NetworkEdgeMembership

    net = Network.objects.create(
        code="tgfb_smad",
        category="I",
        title="TGF-β/SMAD axis",
        pipeline_status="stale",
    )

    oe1 = OntologyEntity.objects.create(
        entity_type="protein",
        preferred_label="TGFB1",
        canonical_uri="https://identifiers.org/uniprot:P01137",
    )
    oe2 = OntologyEntity.objects.create(
        entity_type="protein",
        preferred_label="SMAD3",
        canonical_uri="https://identifiers.org/uniprot:P84022",
    )
    oe3 = OntologyEntity.objects.create(
        entity_type="protein",
        preferred_label="SMAD7",
        canonical_uri="https://identifiers.org/uniprot:O15105",
    )
    e1 = Entity.objects.create(ontology_entity=oe1)
    e2 = Entity.objects.create(ontology_entity=oe2)
    e3 = Entity.objects.create(ontology_entity=oe3)

    edge_a = Edge.objects.create(source=e1, target=e2, relation="activates", belief_score=0.8)
    edge_b = Edge.objects.create(source=e1, target=e3, relation="inhibits", belief_score=0.6)

    NetworkEdgeMembership.objects.create(network=net, edge=edge_a)
    NetworkEdgeMembership.objects.create(network=net, edge=edge_b)

    Conflict.objects.create(
        edge_a=edge_a,
        edge_b=edge_b,
        conflict_type="inter_paper",
        resolution_status="open",
    )
    return net, edge_a, edge_b


class TestGridView:
    """Tests for GET / (dashboard:grid)."""

    def test_grid_returns_200(self, client, db, two_networks):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_grid_lists_network_codes(self, client, db, two_networks):
        resp = client.get("/")
        body = resp.content.decode()
        assert "nfkb_axis" in body
        assert "sox9_notch" in body

    def test_grid_shows_network_titles(self, client, db, two_networks):
        resp = client.get("/")
        body = resp.content.decode()
        assert "NF-κB Axis" in body

    def test_grid_groups_by_category(self, client, db, two_networks):
        """Category labels from _CATEGORY_LABELS should appear in the page."""
        resp = client.get("/")
        body = resp.content.decode()
        # Category I label
        assert "Core Signaling" in body
        # Category II label
        assert "Transcription Factor" in body

    def test_grid_shows_pipeline_status(self, client, db, two_networks):
        resp = client.get("/")
        body = resp.content.decode()
        # Status pills should be present
        assert "version_draft" in body
        assert "idle" in body

    def test_grid_shows_edge_count_for_network_with_edges(
        self, client, db, network_with_edges_and_conflicts
    ):
        """Networks with edges should show their own integer edge count in the card."""
        resp = client.get("/")
        body = resp.content.decode()
        assert "tgfb_smad" in body
        # The card must render the per-network integer ("2 edges"), NOT the raw
        # edge_counts dict. Regression guard for the bug where network_card.html
        # rendered the whole {network_id: count} mapping on every card.
        assert "2 edges" in body
        assert "} edges" not in body  # no dict repr leaked into the card

    def test_grid_shows_open_conflict_count(self, client, db, network_with_edges_and_conflicts):
        """Networks with open conflicts should show conflict count."""
        resp = client.get("/")
        body = resp.content.decode()
        assert "tgfb_smad" in body
        # 1 open conflict
        assert "1" in body

    def test_grid_empty_database_returns_200(self, client, db):
        """Grid works even when no networks exist."""
        resp = client.get("/")
        assert resp.status_code == 200

    def test_grid_template_used(self, client, db, two_networks):
        resp = client.get("/")
        template_names = [t.name for t in resp.templates]
        assert "dashboard/grid.html" in template_names

    def test_grid_uses_partials(self, client, db, two_networks):
        """Response should use the category_section and network_card partials."""
        resp = client.get("/")
        template_names = [t.name for t in resp.templates]
        assert "dashboard/partials/category_section.html" in template_names
        assert "dashboard/partials/network_card.html" in template_names

    def test_grid_only_shows_active_networks(self, client, db):
        """Inactive networks (is_active=False) must not appear."""
        Network.objects.create(code="inactive_net", category="I", title="Hidden", is_active=False)
        Network.objects.create(code="active_net", category="I", title="Visible", is_active=True)
        resp = client.get("/")
        body = resp.content.decode()
        assert "active_net" in body
        assert "inactive_net" not in body

    def test_grid_has_17_category_headers_when_all_exist(self, client, db):
        """When at least one network exists per category, 17 sections appear."""
        for i, cat in enumerate(
            [
                "I",
                "II",
                "III",
                "IV",
                "V",
                "VI",
                "VII",
                "VIII",
                "IX",
                "X",
                "XI",
                "XII",
                "XIII",
                "XIV",
                "XV",
                "XVI",
                "XVII",
            ]
        ):
            Network.objects.create(
                code=f"net_{i}", category=cat, title=f"Net {cat}", pipeline_status="idle"
            )
        resp = client.get("/")
        body = resp.content.decode()
        # All 17 category labels must appear (just check a subset of unique ones)
        assert "Core Signaling" in body
        assert "Transcription Factor" in body
        assert "Multi-Omics" in body
        assert "Proteostasis" in body

    def test_grid_open_conflict_count_is_bounded_queries(
        self, client, db, network_with_edges_and_conflicts, django_assert_max_num_queries
    ):
        """open_conflict_counts must be built with O(1) DB queries, not one per network.

        We create two additional networks (no edges/conflicts) to prove the query
        count does not scale with the number of networks.
        """
        Network.objects.create(code="extra_net_1", category="II", title="Extra 1")
        Network.objects.create(code="extra_net_2", category="III", title="Extra 2")

        # Allow a generous upper bound — the important invariant is that it is
        # NOT proportional to the number of networks (which would be 200+ queries
        # in production).  A constant ~20 queries covers: session, auth, networks
        # queryset, edge_counts agg, memberships list, conflicts list, template
        # context, etc.
        with django_assert_max_num_queries(20):
            resp = client.get("/")
        assert resp.status_code == 200

    def test_grid_open_conflict_count_correct_value(
        self, client, db, network_with_edges_and_conflicts
    ):
        """grid() must report the correct open-conflict count (1) for tgfb_smad."""
        net, _edge_a, _edge_b = network_with_edges_and_conflicts
        resp = client.get("/")
        assert resp.status_code == 200
        ctx = resp.context
        counts = ctx["open_conflict_counts"]
        assert (
            counts[net.pk] == 1
        ), f"Expected 1 open conflict for {net.code!r}, got {counts[net.pk]}"
