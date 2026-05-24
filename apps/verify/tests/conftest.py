"""Shared fixtures for the verify test suite.

Uses REAL model field names (per cross-plan reconciliation doc):
- Network.title (not name); Network.category max_length=8
- Entity requires OntologyEntity — cannot use flat symbol/canonical_uri kwargs
- Edge.relation (not relation_type)
- Conflict.resolution_status values: open / auto_resolved / human_resolved
- ModelVersion: frozen_at (not frozen), zip_s3_key (not s3_key)
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

User = get_user_model()


@pytest.fixture
def reviewer(db):
    return User.objects.create_user(
        username="fchemorion",
        email="francis.chemorion@upf.edu",
        first_name="Francis",
        last_name="Chemorion",
    )


@pytest.fixture
def other_reviewer(db):
    return User.objects.create_user(
        username="ana_lab",
        email="ana@upf.edu",
        first_name="Ana",
        last_name="L.",
    )


@pytest.fixture
def network(db):
    from networks.models import Network

    return Network.objects.create(
        code="nfkb_axis_mmp_adamts",
        title="NF-kB → MMP/ADAMTS catabolic output",
        category="II",
        pipeline_status="version_draft",
    )


@pytest.fixture
def entities(db):
    """Create OntologyEntity + Entity pairs — the correct creation pattern."""
    from core.models import OntologyEntity
    from graph.models import Entity

    oe1 = OntologyEntity.objects.create(
        entity_type="protein",
        preferred_label="SIRT1",
        canonical_uri="https://identifiers.org/uniprot:Q96EB6",
    )
    oe2 = OntologyEntity.objects.create(
        entity_type="protein",
        preferred_label="NFKB1",
        canonical_uri="https://identifiers.org/uniprot:P19838",
    )
    e1 = Entity.objects.create(ontology_entity=oe1)
    e2 = Entity.objects.create(ontology_entity=oe2)
    return e1, e2


@pytest.fixture
def edge(db, entities):
    from graph.models import Edge

    src, tgt = entities
    return Edge.objects.create(
        source=src,
        target=tgt,
        relation="inhibits",  # canonical field name
        belief_score=0.78,
        status="candidate",
    )


@pytest.fixture
def conflict(db, network, edge, entities):
    from graph.models import Conflict, Edge

    src, tgt = entities
    edge_b = Edge.objects.create(
        source=src,
        target=tgt,
        relation="activates",  # canonical field name
        belief_score=0.55,
        status="candidate",
    )
    return Conflict.objects.create(
        edge_a=edge,
        edge_b=edge_b,
        conflict_type="inter_paper",
        resolution_status="open",
    )


@pytest.fixture
def model_version(db, network):
    from sbml.models import ModelVersion

    # ModelVersion requires n_species, n_reactions, n_edges; frozen_at (not 'frozen')
    mv = ModelVersion.objects.create(
        network=network,
        semver="0.3.2",
        zip_s3_key="sbml/nfkb_axis_mmp_adamts/v0.3.2.zip",
        n_species=3,
        n_reactions=2,
        n_edges=2,
    )
    mv.freeze()
    return mv
