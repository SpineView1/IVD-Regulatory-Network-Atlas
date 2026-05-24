"""Shared fixtures for analysis tests."""
from __future__ import annotations

import os

import pytest

from analysis.backends.fake import FakeGraphBackend


@pytest.fixture
def fake_backend(settings) -> FakeGraphBackend:
    """Force the analysis app onto the in-memory backend for the test."""
    settings.ANALYSIS_GRAPH_BACKEND = "fake"
    return FakeGraphBackend()


@pytest.fixture
def accepted_edge(db):
    """An accepted IL1B->NFKB1 edge with a NetworkEdgeMembership in nfkb_axis.

    Builds the Phase 3 graph rows directly (no integration run) so the
    projection mapping can be exercised in isolation. Uses ONLY canonical
    field names (reconciliation §4/§5/§6).
    """
    from core.models import Identifier, OntologyEntity
    from graph.models import Edge, Entity, NetworkEdgeMembership
    from networks.models import Network

    def make_entity(label, etype, scheme, value, uri):
        oe = OntologyEntity.objects.create(
            entity_type=etype, preferred_label=label, canonical_uri=uri,
            compartment="cytoplasm",
        )
        Identifier.objects.create(entity=oe, scheme=scheme, value=value)
        return Entity.objects.create(ontology_entity=oe)

    src = make_entity("IL1B", "protein", "HGNC", "5992",
                      "https://identifiers.org/hgnc:5992")
    tgt = make_entity("NFKB1", "protein", "HGNC", "7794",
                      "https://identifiers.org/hgnc:7794")
    edge = Edge.objects.create(
        source=src, target=tgt, relation="activates", belief_score=0.91,
        n_supporting_papers=3, n_models_agreeing=5, status="accepted",
    )
    net = Network.objects.create(code="nfkb_axis", title="NF-κB axis", category="I",
                                 root_entities=[{"scheme": "HGNC", "value": "7794"}],
                                 pipeline_status="idle")
    NetworkEdgeMembership.objects.create(network=net, edge=edge, relevance=1.0)
    return edge


@pytest.fixture
def projected_atlas(db, accepted_edge, fake_backend):
    """A fake backend with `accepted_edge` already projected into it."""
    from analysis.projection import project_edge_ids
    project_edge_ids([accepted_edge.id], backend=fake_backend)
    return fake_backend


@pytest.fixture
def neo4j_backend():
    """Live Neo4jBackend for @pytest.mark.neo4j tests; skip if unconfigured."""
    if not os.environ.get("NEO4J_URI"):
        pytest.skip("NEO4J_URI not set — skipping live Neo4j integration test")
    from analysis.backends.neo4j_backend import Neo4jBackend

    backend = Neo4jBackend(
        uri=os.environ["NEO4J_URI"],
        user=os.environ.get("NEO4J_USER", "neo4j"),
        password=os.environ.get("NEO4J_PASSWORD", ""),
    )
    backend.ensure_constraints()
    backend.clear_all()
    yield backend
    backend.clear_all()
    backend.close()
