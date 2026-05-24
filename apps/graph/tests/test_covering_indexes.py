"""TDD: Phase 7 covering indexes for graph network drill-down hot paths.

Tests assert that the indexes created by migration
0006_edge_covering_indexes exist after migrate runs, and that the
drill-down query still returns correct results.

EXPLAIN ANALYZE timings against production data are to be captured at
deploy time — not fabricated here.
"""

from __future__ import annotations

import pytest
from django.db import connection


@pytest.mark.django_db
def test_covering_index_graph_edge_status_belief_exists() -> None:
    """graph_edge_status_belief_idx must exist after migration."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT indexname
            FROM pg_indexes
            WHERE tablename = 'graph_edge'
              AND indexname = 'graph_edge_status_belief_idx'
            """
        )
        row = cursor.fetchone()
    assert row is not None, (
        "Index graph_edge_status_belief_idx not found — "
        "migration 0006_edge_covering_indexes may not have run."
    )


@pytest.mark.django_db
def test_covering_index_graph_networkedgemembership_network_edge_exists() -> None:
    """graph_networkedgemembership_network_edge_idx must exist after migration."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT indexname
            FROM pg_indexes
            WHERE tablename = 'graph_networkedgemembership'
              AND indexname = 'graph_networkedgemembership_network_edge_idx'
            """
        )
        row = cursor.fetchone()
    assert row is not None, (
        "Index graph_networkedgemembership_network_edge_idx not found — "
        "migration 0006_edge_covering_indexes may not have run."
    )


@pytest.mark.django_db
def test_network_drilldown_query_returns_accepted_edges_ordered(db) -> None:
    """The network drill-down query returns accepted edges ordered by belief_score DESC."""
    from core.models import OntologyEntity
    from graph.models import Edge, Entity, NetworkEdgeMembership
    from networks.models import Network

    network = Network.objects.create(code="test_drilldown", title="Drill-down test network")
    oe_a = OntologyEntity.objects.create(entity_type="protein", preferred_label="GeneA")
    oe_b = OntologyEntity.objects.create(entity_type="protein", preferred_label="GeneB")
    oe_c = OntologyEntity.objects.create(entity_type="protein", preferred_label="GeneC")
    a = Entity.objects.create(ontology_entity=oe_a)
    b = Entity.objects.create(ontology_entity=oe_b)
    c = Entity.objects.create(ontology_entity=oe_c)

    e1 = Edge.objects.create(
        source=a, target=b, relation="activates", belief_score=0.9, status="accepted"
    )
    e2 = Edge.objects.create(
        source=b, target=c, relation="inhibits", belief_score=0.7, status="accepted"
    )
    e3 = Edge.objects.create(
        source=a, target=c, relation="binds", belief_score=0.5, status="candidate"
    )
    NetworkEdgeMembership.objects.create(network=network, edge=e1)
    NetworkEdgeMembership.objects.create(network=network, edge=e2)
    NetworkEdgeMembership.objects.create(network=network, edge=e3)

    # Hot query: join via network_memberships, filter accepted, order by belief DESC
    edges = list(
        Edge.objects.filter(
            network_memberships__network=network,
            status="accepted",
        ).order_by("-belief_score")[:200]
    )

    assert len(edges) == 2
    assert edges[0].belief_score == 0.9
    assert edges[1].belief_score == 0.7
    # candidate edge excluded
    assert all(e.status == "accepted" for e in edges)
