"""Shared fixtures for sbml tests.

Uses REAL model field names (per cross-plan reconciliation doc):
- Edge.relation (not relation_type)
- Network.title (not name)
- Entity requires OntologyEntity (no flat kwargs)
"""
from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from core.models import Identifier, OntologyEntity
from graph.models import Edge, Entity, NetworkEdgeMembership
from networks.models import Network

User = get_user_model()


def _make_entity(
    label: str,
    entity_type: str,
    compartment: str = "cytoplasm",
    canonical_uri: str = "",
    identifiers: list[tuple[str, str]] | None = None,
) -> Entity:
    """Create an OntologyEntity + Entity pair with optional identifiers."""
    oe = OntologyEntity.objects.create(
        entity_type=entity_type,
        preferred_label=label,
        compartment=compartment,
        canonical_uri=canonical_uri,
    )
    for scheme, value in (identifiers or []):
        Identifier.objects.create(entity=oe, scheme=scheme, value=value)
    return Entity.objects.create(ontology_entity=oe)


@pytest.fixture
def network(db) -> Network:
    return Network.objects.create(
        code="nfkb_axis_mmp_adamts",
        title="NF-kappaB -> MMP/ADAMTS catabolic output (NP cells)",
        category="I",
        pipeline_status="stale",
    )


@pytest.fixture
def entities(db) -> dict[str, Entity]:
    out: dict[str, Entity] = {}
    out["IL1B"] = _make_entity(
        label="IL1B",
        entity_type="protein",
        compartment="extracellular",
        canonical_uri="https://identifiers.org/uniprot:P01584",
        identifiers=[("UNIPROT", "P01584"), ("HGNC", "5992")],
    )
    out["NFKB1"] = _make_entity(
        label="NFKB1",
        entity_type="protein",
        compartment="nucleus",
        canonical_uri="https://identifiers.org/uniprot:P19838",
        identifiers=[("UNIPROT", "P19838"), ("HGNC", "7794")],
    )
    out["MMP13"] = _make_entity(
        label="MMP13",
        entity_type="protein",
        compartment="extracellular",
        canonical_uri="https://identifiers.org/uniprot:P45452",
        identifiers=[("UNIPROT", "P45452"), ("HGNC", "7159")],
    )
    return out


@pytest.fixture
def accepted_edges(db, network, entities) -> list[Edge]:
    e1 = Edge.objects.create(
        source=entities["IL1B"],
        target=entities["NFKB1"],
        relation="activates",  # canonical field name
        status="accepted",
        belief_score=0.94,
        n_supporting_papers=3,
        n_models_agreeing=6,
    )
    e2 = Edge.objects.create(
        source=entities["NFKB1"],
        target=entities["MMP13"],
        relation="activates",  # canonical field name
        status="accepted",
        belief_score=0.88,
        n_supporting_papers=2,
        n_models_agreeing=5,
    )
    NetworkEdgeMembership.objects.create(network=network, edge=e1, relevance=0.99)
    NetworkEdgeMembership.objects.create(network=network, edge=e2, relevance=0.95)
    return [e1, e2]


@pytest.fixture
def reviewer(db) -> User:  # type: ignore[type-arg]
    return User.objects.create_user(username="curator", email="curator@upf.edu", password="x")
