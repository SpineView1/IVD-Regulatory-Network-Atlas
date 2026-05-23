"""Tests for graph.models — Entity, Edge, EdgeEvidence, Conflict."""

from __future__ import annotations

import pytest
from django.db import IntegrityError

from graph.models import Conflict, Edge, EdgeEvidence, Entity


def test_entity_links_to_ontology_entity(db, il1b_ontology_entity):
    e = Entity.objects.create(ontology_entity=il1b_ontology_entity)
    assert e.ontology_entity == il1b_ontology_entity
    assert e.created_at is not None


def test_entity_unique_per_ontology_entity(db, il1b_ontology_entity):
    Entity.objects.create(ontology_entity=il1b_ontology_entity)
    with pytest.raises(IntegrityError):
        Entity.objects.create(ontology_entity=il1b_ontology_entity)


def test_entity_preferred_label_derives_from_ontology(db, il1b_ontology_entity):
    e = Entity.objects.create(ontology_entity=il1b_ontology_entity)
    assert e.preferred_label == "IL1B"


def test_entity_has_primary_identifier(db, il1b_ontology_entity):
    e = Entity.objects.create(ontology_entity=il1b_ontology_entity)
    assert e.primary_identifier.value == "5992"
    assert e.primary_identifier.scheme == "HGNC"


def test_entity_proxy_symbol_returns_preferred_label(db, il1b_ontology_entity):
    """Phase 4 proxy property contract — reconciliation doc §5/§8."""
    e = Entity.objects.create(ontology_entity=il1b_ontology_entity)
    assert e.symbol == "IL1B"


def test_entity_proxy_compartment_defaults_to_cytoplasm(db, il1b_ontology_entity):
    e = Entity.objects.create(ontology_entity=il1b_ontology_entity)
    assert e.compartment == "cytoplasm"


def test_entity_proxy_miriam_uris_for_hgnc(db, il1b_ontology_entity):
    e = Entity.objects.create(ontology_entity=il1b_ontology_entity)
    uris = e.miriam_uris
    assert any("hgnc:5992" in u for u in uris)


# ---------------------------------------------------------------------------
# Task 6: Edge, EdgeEvidence, Conflict
# ---------------------------------------------------------------------------


def test_edge_unique_on_source_target_relation(
    db, il1b_ontology_entity, nfkb1_ontology_entity
):
    src = Entity.objects.create(ontology_entity=il1b_ontology_entity)
    tgt = Entity.objects.create(ontology_entity=nfkb1_ontology_entity)
    Edge.objects.create(source=src, target=tgt, relation="activates")
    with pytest.raises(IntegrityError):
        Edge.objects.create(source=src, target=tgt, relation="activates")


def test_edge_allows_same_pair_with_different_relation(
    db, il1b_ontology_entity, nfkb1_ontology_entity
):
    src = Entity.objects.create(ontology_entity=il1b_ontology_entity)
    tgt = Entity.objects.create(ontology_entity=nfkb1_ontology_entity)
    Edge.objects.create(source=src, target=tgt, relation="activates")
    Edge.objects.create(source=src, target=tgt, relation="binds")  # OK


def test_edge_defaults_to_candidate_status(
    db, il1b_ontology_entity, nfkb1_ontology_entity
):
    src = Entity.objects.create(ontology_entity=il1b_ontology_entity)
    tgt = Entity.objects.create(ontology_entity=nfkb1_ontology_entity)
    e = Edge.objects.create(source=src, target=tgt, relation="activates")
    assert e.status == "candidate"
    assert e.belief_score == 0.0
    assert e.n_supporting_papers == 0
    assert e.n_models_agreeing == 0


def test_edge_evidence_links_edge_to_raw_ppi(
    db, raw_ppi_factory, il1b_ontology_entity, nfkb1_ontology_entity
):
    src = Entity.objects.create(ontology_entity=il1b_ontology_entity)
    tgt = Entity.objects.create(ontology_entity=nfkb1_ontology_entity)
    e = Edge.objects.create(source=src, target=tgt, relation="activates")
    raw = raw_ppi_factory(subject="IL1B", object="NFKB1")
    ev = EdgeEvidence.objects.create(edge=e, raw_ppi=raw)
    assert ev.edge == e and ev.raw_ppi == raw


def test_edge_evidence_unique_per_edge_raw_ppi(
    db, raw_ppi_factory, il1b_ontology_entity, nfkb1_ontology_entity
):
    src = Entity.objects.create(ontology_entity=il1b_ontology_entity)
    tgt = Entity.objects.create(ontology_entity=nfkb1_ontology_entity)
    e = Edge.objects.create(source=src, target=tgt, relation="activates")
    raw = raw_ppi_factory(subject="IL1B", object="NFKB1")
    EdgeEvidence.objects.create(edge=e, raw_ppi=raw)
    with pytest.raises(IntegrityError):
        EdgeEvidence.objects.create(edge=e, raw_ppi=raw)


def test_edge_evidence_reverse_name_is_evidence(
    db, raw_ppi_factory, il1b_ontology_entity, nfkb1_ontology_entity
):
    """Phase 4 uses edge.evidence.all() — confirm the related_name."""
    src = Entity.objects.create(ontology_entity=il1b_ontology_entity)
    tgt = Entity.objects.create(ontology_entity=nfkb1_ontology_entity)
    e = Edge.objects.create(source=src, target=tgt, relation="activates")
    raw = raw_ppi_factory(subject="IL1B", object="NFKB1")
    EdgeEvidence.objects.create(edge=e, raw_ppi=raw)
    assert e.evidence.count() == 1


def test_conflict_records_two_edges_and_status(
    db, il1b_ontology_entity, nfkb1_ontology_entity
):
    src = Entity.objects.create(ontology_entity=il1b_ontology_entity)
    tgt = Entity.objects.create(ontology_entity=nfkb1_ontology_entity)
    e1 = Edge.objects.create(source=src, target=tgt, relation="activates")
    e2 = Edge.objects.create(source=src, target=tgt, relation="inhibits")
    c = Conflict.objects.create(
        edge_a=e1,
        edge_b=e2,
        conflict_type="inter_model",
        resolution_status="open",
    )
    assert c.resolution_status == "open"
    assert c.conflict_type == "inter_model"


def test_conflict_unique_per_edge_pair_and_type(
    db, il1b_ontology_entity, nfkb1_ontology_entity
):
    src = Entity.objects.create(ontology_entity=il1b_ontology_entity)
    tgt = Entity.objects.create(ontology_entity=nfkb1_ontology_entity)
    e1 = Edge.objects.create(source=src, target=tgt, relation="activates")
    e2 = Edge.objects.create(source=src, target=tgt, relation="inhibits")
    Conflict.objects.create(
        edge_a=e1, edge_b=e2, conflict_type="inter_model", resolution_status="open"
    )
    with pytest.raises(IntegrityError):
        Conflict.objects.create(
            edge_a=e1, edge_b=e2, conflict_type="inter_model", resolution_status="open"
        )


def test_conflict_resolution_status_choices_include_canonical_values(
    db, il1b_ontology_entity, nfkb1_ontology_entity
):
    """Canonical values per reconciliation doc §9.C: open/auto_resolved/human_resolved."""
    src = Entity.objects.create(ontology_entity=il1b_ontology_entity)
    tgt = Entity.objects.create(ontology_entity=nfkb1_ontology_entity)
    e1 = Edge.objects.create(source=src, target=tgt, relation="activates")
    e2 = Edge.objects.create(source=src, target=tgt, relation="inhibits")
    c = Conflict.objects.create(
        edge_a=e1, edge_b=e2, conflict_type="inter_paper", resolution_status="open"
    )
    c.resolution_status = "auto_resolved"
    c.save()
    c.resolution_status = "human_resolved"
    c.save()
    assert c.resolution_status == "human_resolved"
