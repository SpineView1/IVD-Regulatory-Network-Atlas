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
    for scheme, value in identifiers or []:
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
def reviewer(db):
    return User.objects.create_user(username="curator", email="curator@upf.edu", password="x")


@pytest.fixture
def evidence_rows(db, accepted_edges):
    """Minimal EdgeEvidence chain from Phase 2/3.

    Real field names per cross-plan reconciliation:
    - RawPPI.run (FK to ExtractionRun, NOT extraction_run)
    - RawPPI.subject / object / relation
    - RawPPI.evidence_offset_start / evidence_offset_end
    - RawPPI.relation_logprob (NOT logprob)
    - No direct RawPPI.chunk FK — chain goes raw_ppi.run.chunk
    - Section.order_index (NOT order)
    - Chunk.chunk_index (NOT order)
    """
    from corpus.models import Paper
    from extract.models import ExtractionRun, RawPPI
    from graph.models import EdgeEvidence
    from papers.models import Chunk, Section

    paper = Paper.objects.create(
        pmid=12345678,
        title="IL-1β drives NF-κB signalling in IDD",
        abstract="IL1B activates NFKB1.",
        is_original=True,
        ingest_status="done",
    )
    section = Section.objects.create(
        paper=paper,
        doco_type="doco:Results",
        order_index=0,
        body_text="... IL1B activates NFKB1 via canonical signalling ...",
    )
    chunk = Chunk.objects.create(
        section=section,
        paper=paper,
        text="... IL1B activates NFKB1 ...",
        token_count=8,
        chunk_index=0,
        char_offset_start=0,
        char_offset_end=27,
    )
    run = ExtractionRun.objects.create(
        chunk=chunk,
        model_name="qwen3:8b",
        prompt_version="v1",
        status="done",
    )
    rppi = RawPPI.objects.create(
        run=run,
        subject="IL1B",
        object="NFKB1",
        relation="activates",
        evidence_span="IL1B activates NFKB1",
        evidence_offset_start=5,
        evidence_offset_end=27,
        confidence=0.9,
        relation_logprob=-0.21,
    )
    rows = []
    for e in accepted_edges:
        rows.append(EdgeEvidence.objects.create(edge=e, raw_ppi=rppi))
    return rows
