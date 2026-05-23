"""Tests for graph.NetworkEdgeMembership."""

from __future__ import annotations

import pytest
from django.db import IntegrityError

from graph.models import Edge, Entity, NetworkEdgeMembership


@pytest.fixture
def nfkb_network(db):
    from networks.models import Network  # noqa: PLC0415

    return Network.objects.create(
        code="nfkb_axis",
        title="NF-κB axis",
        category="I",
        root_entities=[{"scheme": "HGNC", "value": "7794"}],  # NFKB1
        pipeline_status="idle",
    )


def test_membership_links_edge_to_network(
    db, il1b_ontology_entity, nfkb1_ontology_entity, nfkb_network
):
    src = Entity.objects.create(ontology_entity=il1b_ontology_entity)
    tgt = Entity.objects.create(ontology_entity=nfkb1_ontology_entity)
    e = Edge.objects.create(source=src, target=tgt, relation="activates")
    m = NetworkEdgeMembership.objects.create(network=nfkb_network, edge=e, relevance=1.0)
    assert m.network == nfkb_network
    assert m.edge == e
    assert m.relevance == 1.0


def test_membership_unique_per_network_edge(
    db, il1b_ontology_entity, nfkb1_ontology_entity, nfkb_network
):
    src = Entity.objects.create(ontology_entity=il1b_ontology_entity)
    tgt = Entity.objects.create(ontology_entity=nfkb1_ontology_entity)
    e = Edge.objects.create(source=src, target=tgt, relation="activates")
    NetworkEdgeMembership.objects.create(network=nfkb_network, edge=e, relevance=1.0)
    with pytest.raises(IntegrityError):
        NetworkEdgeMembership.objects.create(network=nfkb_network, edge=e, relevance=0.5)


def test_membership_reverse_on_network_is_edge_memberships(
    db, il1b_ontology_entity, nfkb1_ontology_entity, nfkb_network
):
    """Network.edge_memberships reverse manager exists and works."""
    src = Entity.objects.create(ontology_entity=il1b_ontology_entity)
    tgt = Entity.objects.create(ontology_entity=nfkb1_ontology_entity)
    e = Edge.objects.create(source=src, target=tgt, relation="activates")
    NetworkEdgeMembership.objects.create(network=nfkb_network, edge=e, relevance=1.0)
    assert nfkb_network.edge_memberships.count() == 1


def test_membership_reverse_on_edge_is_network_memberships(
    db, il1b_ontology_entity, nfkb1_ontology_entity, nfkb_network
):
    """Edge.network_memberships reverse manager exists and works."""
    src = Entity.objects.create(ontology_entity=il1b_ontology_entity)
    tgt = Entity.objects.create(ontology_entity=nfkb1_ontology_entity)
    e = Edge.objects.create(source=src, target=tgt, relation="activates")
    NetworkEdgeMembership.objects.create(network=nfkb_network, edge=e, relevance=0.8)
    membership = e.network_memberships.first()
    assert membership is not None
    assert membership.relevance == pytest.approx(0.8)


def test_membership_cascade_delete_with_network(
    db, il1b_ontology_entity, nfkb1_ontology_entity, nfkb_network
):
    """Deleting the network cascades to memberships."""
    src = Entity.objects.create(ontology_entity=il1b_ontology_entity)
    tgt = Entity.objects.create(ontology_entity=nfkb1_ontology_entity)
    e = Edge.objects.create(source=src, target=tgt, relation="activates")
    NetworkEdgeMembership.objects.create(network=nfkb_network, edge=e, relevance=1.0)
    assert NetworkEdgeMembership.objects.count() == 1
    nfkb_network.delete()
    assert NetworkEdgeMembership.objects.count() == 0
