"""Tests for graph.NetworkEdgeMembership and reassign_network_membership.

Task 12: network membership reassignment + verified/idle → stale demotion.

Uses canonical field names per reconciliation doc:
  - raw_ppi_factory uses: subject=, object=, model_name=
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.db import IntegrityError

from graph.models import Edge, Entity, NetworkEdgeMembership
from graph.services import reassign_network_membership


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


# ---------------------------------------------------------------------------
# Task 12: reassign_network_membership + stale demotion tests
# ---------------------------------------------------------------------------


def _fake_ground_mem(text: str) -> object | None:
    return _fake_ground_mem.table.get(text.strip().upper())  # type: ignore[attr-defined]


_fake_ground_mem.table = {}  # type: ignore[attr-defined]


@pytest.fixture
def gilda_table(il1b_ontology_entity, nfkb1_ontology_entity, sirt1_ontology_entity):
    _fake_ground_mem.table = {  # type: ignore[attr-defined]
        "IL1B": il1b_ontology_entity,
        "NFKB1": nfkb1_ontology_entity,
        "SIRT1": sirt1_ontology_entity,
    }
    yield
    _fake_ground_mem.table = {}  # type: ignore[attr-defined]


@patch("graph.services.ground_mention", side_effect=_fake_ground_mem)
def test_new_edge_creates_membership_when_endpoint_matches_root(
    mock_ground,
    db,
    gilda_table,
    nfkb_network,
    paper_factory,
    chunk_factory,
    raw_ppi_factory,
):
    from graph.services import normalize_and_integrate  # noqa: PLC0415

    paper = paper_factory(pmid="40001", year=2025)
    chunk = chunk_factory(paper=paper)
    raw = raw_ppi_factory(
        subject="IL1B",
        object="NFKB1",
        relation="activates",
        chunk=chunk,
    )
    normalize_and_integrate([raw.pk])

    edge = Edge.objects.get()
    assert NetworkEdgeMembership.objects.filter(network=nfkb_network, edge=edge).exists()


@patch("graph.services.ground_mention", side_effect=_fake_ground_mem)
def test_no_membership_when_no_endpoint_matches_root(
    mock_ground,
    db,
    gilda_table,
    nfkb_network,
    sirt1_ontology_entity,
    paper_factory,
    chunk_factory,
    raw_ppi_factory,
):
    from graph.services import normalize_and_integrate  # noqa: PLC0415

    # SIRT1 → IL1B has neither endpoint as NFKB1 (the only root_entity)
    paper = paper_factory(pmid="40002", year=2025)
    chunk = chunk_factory(paper=paper)
    raw = raw_ppi_factory(
        subject="SIRT1",
        object="IL1B",
        relation="inhibits",
        chunk=chunk,
    )
    normalize_and_integrate([raw.pk])

    edge = Edge.objects.get()
    assert not NetworkEdgeMembership.objects.filter(network=nfkb_network, edge=edge).exists()


@patch("graph.services.ground_mention", side_effect=_fake_ground_mem)
def test_verified_network_demoted_to_stale_on_new_edge(
    mock_ground,
    db,
    gilda_table,
    nfkb_network,
    paper_factory,
    chunk_factory,
    raw_ppi_factory,
):
    from graph.services import normalize_and_integrate  # noqa: PLC0415

    nfkb_network.pipeline_status = "verified"
    nfkb_network.save()

    paper = paper_factory(pmid="40003", year=2025)
    chunk = chunk_factory(paper=paper)
    raw = raw_ppi_factory(
        subject="IL1B",
        object="NFKB1",
        relation="activates",
        chunk=chunk,
    )
    normalize_and_integrate([raw.pk])

    nfkb_network.refresh_from_db()
    assert nfkb_network.pipeline_status == "stale"


@patch("graph.services.ground_mention", side_effect=_fake_ground_mem)
def test_idle_network_demoted_to_stale_on_new_matching_edge(
    mock_ground,
    db,
    gilda_table,
    nfkb_network,
    paper_factory,
    chunk_factory,
    raw_ppi_factory,
):
    """idle network gets demoted to stale when a matching new edge arrives."""
    from graph.services import normalize_and_integrate  # noqa: PLC0415

    nfkb_network.pipeline_status = "idle"
    nfkb_network.save()

    paper = paper_factory(pmid="40006", year=2025)
    chunk = chunk_factory(paper=paper)
    raw = raw_ppi_factory(
        subject="IL1B",
        object="NFKB1",
        relation="activates",
        chunk=chunk,
    )
    normalize_and_integrate([raw.pk])

    nfkb_network.refresh_from_db()
    assert nfkb_network.pipeline_status == "stale"


@patch("graph.services.ground_mention", side_effect=_fake_ground_mem)
def test_idle_network_remains_idle_when_no_matching_edge(
    mock_ground,
    db,
    gilda_table,
    nfkb_network,
    sirt1_ontology_entity,
    paper_factory,
    chunk_factory,
    raw_ppi_factory,
):
    """A network unrelated to the new edge should not change state."""
    from graph.services import normalize_and_integrate  # noqa: PLC0415

    nfkb_network.pipeline_status = "idle"
    nfkb_network.save()

    paper = paper_factory(pmid="40004", year=2025)
    chunk = chunk_factory(paper=paper)
    raw = raw_ppi_factory(
        subject="SIRT1",
        object="IL1B",
        relation="inhibits",
        chunk=chunk,
    )
    normalize_and_integrate([raw.pk])

    nfkb_network.refresh_from_db()
    assert nfkb_network.pipeline_status == "idle"


@patch("graph.services.ground_mention", side_effect=_fake_ground_mem)
def test_reassign_network_membership_is_idempotent(
    mock_ground,
    db,
    gilda_table,
    nfkb_network,
    paper_factory,
    chunk_factory,
    raw_ppi_factory,
):
    from graph.services import normalize_and_integrate  # noqa: PLC0415

    paper = paper_factory(pmid="40005", year=2025)
    chunk = chunk_factory(paper=paper)
    raw = raw_ppi_factory(
        subject="IL1B",
        object="NFKB1",
        relation="activates",
        chunk=chunk,
    )
    normalize_and_integrate([raw.pk])

    edge = Edge.objects.get()
    reassign_network_membership({edge.pk})
    reassign_network_membership({edge.pk})

    assert NetworkEdgeMembership.objects.filter(network=nfkb_network, edge=edge).count() == 1
