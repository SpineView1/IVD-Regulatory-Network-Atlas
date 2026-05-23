"""Tests for core.OntologyEntity and core.Identifier."""

from __future__ import annotations

import pytest
from django.db import IntegrityError

from core.models import Identifier, OntologyEntity


def test_ontology_entity_requires_preferred_label(db):
    with pytest.raises(IntegrityError):
        OntologyEntity.objects.create(entity_type="protein", preferred_label="")


def test_ontology_entity_records_type_and_label(db):
    e = OntologyEntity.objects.create(entity_type="protein", preferred_label="IL1B")
    assert e.entity_type == "protein"
    assert e.preferred_label == "IL1B"
    assert e.created_at is not None


def test_identifier_unique_per_scheme_and_value(db):
    e = OntologyEntity.objects.create(entity_type="protein", preferred_label="IL1B")
    Identifier.objects.create(entity=e, scheme="HGNC", value="5992")
    with pytest.raises(IntegrityError):
        Identifier.objects.create(entity=e, scheme="HGNC", value="5992")


def test_identifier_is_iri_for_known_schemes(db):
    e = OntologyEntity.objects.create(entity_type="protein", preferred_label="IL1B")
    i = Identifier.objects.create(entity=e, scheme="HGNC", value="5992")
    assert i.as_iri() == "https://identifiers.org/hgnc:5992"


def test_identifier_is_iri_for_uniprot(db):
    e = OntologyEntity.objects.create(entity_type="protein", preferred_label="IL1B")
    i = Identifier.objects.create(entity=e, scheme="UNIPROT", value="P01584")
    assert i.as_iri() == "https://identifiers.org/uniprot:P01584"


def test_identifier_is_iri_for_chebi(db):
    e = OntologyEntity.objects.create(entity_type="metabolite", preferred_label="NAD+")
    i = Identifier.objects.create(entity=e, scheme="CHEBI", value="13389")
    assert i.as_iri() == "https://identifiers.org/chebi:CHEBI:13389"


def test_identifier_is_iri_for_mirbase(db):
    e = OntologyEntity.objects.create(entity_type="mirna", preferred_label="miR-21")
    i = Identifier.objects.create(entity=e, scheme="MIRBASE", value="MIMAT0000076")
    assert i.as_iri() == "https://identifiers.org/mirbase:MIMAT0000076"


def test_ontology_entity_reverse_relation_named_identifiers(db):
    e = OntologyEntity.objects.create(entity_type="protein", preferred_label="IL1B")
    Identifier.objects.create(entity=e, scheme="HGNC", value="5992")
    Identifier.objects.create(entity=e, scheme="UNIPROT", value="P01584")
    assert e.identifiers.count() == 2


def test_ontology_entity_has_compartment_and_canonical_uri_fields(db):
    """Fields required by cross-plan reconciliation §5/§8."""
    e = OntologyEntity.objects.create(
        entity_type="protein",
        preferred_label="IL1B",
        compartment="nucleus",
        canonical_uri="https://identifiers.org/hgnc:5992",
    )
    assert e.compartment == "nucleus"
    assert e.canonical_uri == "https://identifiers.org/hgnc:5992"


def test_ontology_entity_default_compartment_is_cytoplasm(db):
    e = OntologyEntity.objects.create(entity_type="protein", preferred_label="IL1B")
    assert e.compartment == "cytoplasm"
