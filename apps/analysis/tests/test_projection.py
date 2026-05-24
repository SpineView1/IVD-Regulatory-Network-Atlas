"""Tests for the GraphBackend contract via FakeGraphBackend, and projection mapping."""

from __future__ import annotations

import pytest

from analysis.backends.fake import FakeGraphBackend


@pytest.fixture
def backend() -> FakeGraphBackend:
    return FakeGraphBackend()


def test_upsert_entity_then_get(backend):
    backend.upsert_entity(
        {
            "pg_id": 1,
            "symbol": "IL1B",
            "entity_type": "protein",
            "compartment": "extracellular",
            "canonical_uri": "u",
            "ontology_id": 11,
        }
    )
    node = backend.get_entity(1)
    assert node["symbol"] == "IL1B"


def test_upsert_entity_is_idempotent(backend):
    for _ in range(2):
        backend.upsert_entity(
            {
                "pg_id": 1,
                "symbol": "IL1B",
                "entity_type": "protein",
                "compartment": "x",
                "canonical_uri": "u",
                "ontology_id": 11,
            }
        )
    assert backend.count_entities() == 1


def test_upsert_edge_creates_relationship(backend):
    backend.upsert_entity(
        {
            "pg_id": 1,
            "symbol": "IL1B",
            "entity_type": "protein",
            "compartment": "x",
            "canonical_uri": "u",
            "ontology_id": 11,
        }
    )
    backend.upsert_entity(
        {
            "pg_id": 2,
            "symbol": "NFKB1",
            "entity_type": "protein",
            "compartment": "n",
            "canonical_uri": "u2",
            "ontology_id": 12,
        }
    )
    backend.upsert_edge(
        source_pg_id=1,
        target_pg_id=2,
        props={
            "edge_id": 100,
            "relation": "activates",
            "belief_score": 0.9,
            "n_supporting_papers": 3,
            "n_models_agreeing": 5,
            "status": "accepted",
            "networks": ["nfkb_axis"],
        },
    )
    assert backend.count_edges() == 1


def test_upsert_edge_is_idempotent_on_edge_id(backend):
    backend.upsert_entity(
        {
            "pg_id": 1,
            "symbol": "A",
            "entity_type": "p",
            "compartment": "c",
            "canonical_uri": "u",
            "ontology_id": 1,
        }
    )
    backend.upsert_entity(
        {
            "pg_id": 2,
            "symbol": "B",
            "entity_type": "p",
            "compartment": "c",
            "canonical_uri": "u",
            "ontology_id": 2,
        }
    )
    props = {
        "edge_id": 100,
        "relation": "activates",
        "belief_score": 0.5,
        "n_supporting_papers": 1,
        "n_models_agreeing": 1,
        "status": "accepted",
        "networks": [],
    }
    backend.upsert_edge(source_pg_id=1, target_pg_id=2, props=props)
    props["belief_score"] = 0.95
    backend.upsert_edge(source_pg_id=1, target_pg_id=2, props=props)
    assert backend.count_edges() == 1
    assert backend.get_edge(100)["belief_score"] == 0.95  # updated in place


def test_delete_edge_removes_relationship(backend):
    backend.upsert_entity(
        {
            "pg_id": 1,
            "symbol": "A",
            "entity_type": "p",
            "compartment": "c",
            "canonical_uri": "u",
            "ontology_id": 1,
        }
    )
    backend.upsert_entity(
        {
            "pg_id": 2,
            "symbol": "B",
            "entity_type": "p",
            "compartment": "c",
            "canonical_uri": "u",
            "ontology_id": 2,
        }
    )
    backend.upsert_edge(
        source_pg_id=1,
        target_pg_id=2,
        props={
            "edge_id": 100,
            "relation": "activates",
            "belief_score": 0.5,
            "n_supporting_papers": 1,
            "n_models_agreeing": 1,
            "status": "accepted",
            "networks": [],
        },
    )
    backend.delete_edge(100)
    assert backend.count_edges() == 0


def test_all_edge_ids_returns_projected_set(backend):
    backend.upsert_entity(
        {
            "pg_id": 1,
            "symbol": "A",
            "entity_type": "p",
            "compartment": "c",
            "canonical_uri": "u",
            "ontology_id": 1,
        }
    )
    backend.upsert_entity(
        {
            "pg_id": 2,
            "symbol": "B",
            "entity_type": "p",
            "compartment": "c",
            "canonical_uri": "u",
            "ontology_id": 2,
        }
    )
    backend.upsert_edge(
        source_pg_id=1,
        target_pg_id=2,
        props={
            "edge_id": 100,
            "relation": "activates",
            "belief_score": 0.5,
            "n_supporting_papers": 1,
            "n_models_agreeing": 1,
            "status": "accepted",
            "networks": [],
        },
    )
    assert backend.all_edge_ids() == {100}


# ---------------------------------------------------------------------------
# Task 4: projection mapping tests
# ---------------------------------------------------------------------------


def test_build_entity_payload_uses_canonical_proxy_props(db, accepted_edge):
    from analysis.projection import build_entity_payload

    payload = build_entity_payload(accepted_edge.source)
    assert payload["pg_id"] == accepted_edge.source_id
    assert payload["symbol"] == "IL1B"  # Entity.symbol proxy (§5)
    assert payload["entity_type"] == "protein"
    assert payload["compartment"] == "cytoplasm"
    assert payload["canonical_uri"] == "https://identifiers.org/hgnc:5992"


def test_build_edge_payload_uses_canonical_edge_fields(db, accepted_edge):
    from analysis.projection import build_edge_payload

    props = build_edge_payload(accepted_edge)
    assert props["edge_id"] == accepted_edge.id
    assert props["relation"] == "activates"  # Edge.relation, NOT relation_type (§4)
    assert props["belief_score"] == pytest.approx(0.91)
    assert props["n_supporting_papers"] == 3  # now persisted (§8)
    assert props["n_models_agreeing"] == 5
    assert props["status"] == "accepted"
    assert props["networks"] == ["nfkb_axis"]  # from NetworkEdgeMembership


def test_project_edge_ids_writes_nodes_edges_and_membership(db, accepted_edge, fake_backend):
    from analysis.projection import project_edge_ids

    project_edge_ids([accepted_edge.id], backend=fake_backend)
    assert fake_backend.count_entities() == 2
    assert fake_backend.count_edges() == 1
    # both endpoints linked to the network
    cross = fake_backend.crosstalk_edges(network_a="nfkb_axis", network_b="nfkb_axis")
    assert len(cross["edges"]) == 1


def test_project_edge_ids_deletes_relationship_when_not_accepted(db, accepted_edge, fake_backend):
    from analysis.projection import project_edge_ids

    project_edge_ids([accepted_edge.id], backend=fake_backend)
    assert fake_backend.count_edges() == 1

    accepted_edge.status = "rejected"
    accepted_edge.save(update_fields=["status"])
    project_edge_ids([accepted_edge.id], backend=fake_backend)
    assert fake_backend.count_edges() == 0


def test_accepted_edge_ids_in_postgres(db, accepted_edge):
    from analysis.projection import accepted_edge_ids

    assert accepted_edge_ids() == {accepted_edge.id}
