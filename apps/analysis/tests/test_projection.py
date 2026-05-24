"""Tests for the GraphBackend contract via FakeGraphBackend, and projection mapping."""
from __future__ import annotations

import pytest

from analysis.backends.fake import FakeGraphBackend


@pytest.fixture
def backend() -> FakeGraphBackend:
    return FakeGraphBackend()


def test_upsert_entity_then_get(backend):
    backend.upsert_entity({"pg_id": 1, "symbol": "IL1B", "entity_type": "protein",
                           "compartment": "extracellular", "canonical_uri": "u", "ontology_id": 11})
    node = backend.get_entity(1)
    assert node["symbol"] == "IL1B"


def test_upsert_entity_is_idempotent(backend):
    for _ in range(2):
        backend.upsert_entity({"pg_id": 1, "symbol": "IL1B", "entity_type": "protein",
                               "compartment": "x", "canonical_uri": "u", "ontology_id": 11})
    assert backend.count_entities() == 1


def test_upsert_edge_creates_relationship(backend):
    backend.upsert_entity({"pg_id": 1, "symbol": "IL1B", "entity_type": "protein",
                           "compartment": "x", "canonical_uri": "u", "ontology_id": 11})
    backend.upsert_entity({"pg_id": 2, "symbol": "NFKB1", "entity_type": "protein",
                           "compartment": "n", "canonical_uri": "u2", "ontology_id": 12})
    backend.upsert_edge(source_pg_id=1, target_pg_id=2, props={
        "edge_id": 100, "relation": "activates", "belief_score": 0.9,
        "n_supporting_papers": 3, "n_models_agreeing": 5, "status": "accepted",
        "networks": ["nfkb_axis"],
    })
    assert backend.count_edges() == 1


def test_upsert_edge_is_idempotent_on_edge_id(backend):
    backend.upsert_entity({"pg_id": 1, "symbol": "A", "entity_type": "p", "compartment": "c",
                           "canonical_uri": "u", "ontology_id": 1})
    backend.upsert_entity({"pg_id": 2, "symbol": "B", "entity_type": "p", "compartment": "c",
                           "canonical_uri": "u", "ontology_id": 2})
    props = {"edge_id": 100, "relation": "activates", "belief_score": 0.5,
             "n_supporting_papers": 1, "n_models_agreeing": 1, "status": "accepted",
             "networks": []}
    backend.upsert_edge(source_pg_id=1, target_pg_id=2, props=props)
    props["belief_score"] = 0.95
    backend.upsert_edge(source_pg_id=1, target_pg_id=2, props=props)
    assert backend.count_edges() == 1
    assert backend.get_edge(100)["belief_score"] == 0.95  # updated in place


def test_delete_edge_removes_relationship(backend):
    backend.upsert_entity({"pg_id": 1, "symbol": "A", "entity_type": "p", "compartment": "c",
                           "canonical_uri": "u", "ontology_id": 1})
    backend.upsert_entity({"pg_id": 2, "symbol": "B", "entity_type": "p", "compartment": "c",
                           "canonical_uri": "u", "ontology_id": 2})
    backend.upsert_edge(source_pg_id=1, target_pg_id=2, props={
        "edge_id": 100, "relation": "activates", "belief_score": 0.5,
        "n_supporting_papers": 1, "n_models_agreeing": 1, "status": "accepted", "networks": []})
    backend.delete_edge(100)
    assert backend.count_edges() == 0


def test_all_edge_ids_returns_projected_set(backend):
    backend.upsert_entity({"pg_id": 1, "symbol": "A", "entity_type": "p", "compartment": "c",
                           "canonical_uri": "u", "ontology_id": 1})
    backend.upsert_entity({"pg_id": 2, "symbol": "B", "entity_type": "p", "compartment": "c",
                           "canonical_uri": "u", "ontology_id": 2})
    backend.upsert_edge(source_pg_id=1, target_pg_id=2, props={
        "edge_id": 100, "relation": "activates", "belief_score": 0.5,
        "n_supporting_papers": 1, "n_models_agreeing": 1, "status": "accepted", "networks": []})
    assert backend.all_edge_ids() == {100}
