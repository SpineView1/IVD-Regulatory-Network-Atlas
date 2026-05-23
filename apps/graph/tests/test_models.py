"""Tests for graph.models — Entity, Edge, EdgeEvidence, Conflict."""

from __future__ import annotations

import pytest
from django.db import IntegrityError

from graph.models import Entity


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
