"""End-to-end pytest integration test for Phase 3 — NF-κB axis path.

Task 18: fully offline (stub grounder, no cluster / no Gilda network call).

Flow:
  1. Seed Paper → Section → Chunk → ExtractionRun → RawPPI (7 models)
  2. Seed Network(code="nfkb_axis") with NFKB1 as root entity
  3. Call normalize_and_integrate() with stub grounder
  4. Assert Edge + EdgeEvidence + NetworkEdgeMembership created, belief correct
  5. Hit /graph/dev/networks/nfkb_axis/edges.json via Django test client
  6. Assert JSON response contains the expected IL1B→activates→NFKB1 edge and nodes

All runs 100% offline — no Gilda HTTP, no Ollama, no cluster required.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from django.test import Client

# ---------------------------------------------------------------------------
# Stub grounder — maps upper-cased text → OntologyEntity
# ---------------------------------------------------------------------------

_STUB_TABLE: dict[str, Any] = {}


def _stub_ground(text: str) -> Any:
    """Offline replacement for core.services.ground_mention."""
    return _STUB_TABLE.get(text.strip().upper())


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def nfkb_network(db):
    """Seed the NF-κB axis network with NFKB1 (HGNC:7794) as root."""
    from networks.models import Network

    return Network.objects.create(
        code="nfkb_axis_e2e",
        title="NF-κB axis (e2e test)",
        category="I",
        root_entities=[{"scheme": "HGNC", "value": "7794"}],
        pipeline_status="idle",
    )


@pytest.fixture
def il1b_entity(db):
    from core.models import Identifier, OntologyEntity

    e = OntologyEntity.objects.create(entity_type="protein", preferred_label="IL1B")
    Identifier.objects.create(entity=e, scheme="HGNC", value="5992", is_primary=True)
    return e


@pytest.fixture
def nfkb1_entity(db):
    from core.models import Identifier, OntologyEntity

    e = OntologyEntity.objects.create(entity_type="protein", preferred_label="NFKB1")
    Identifier.objects.create(entity=e, scheme="HGNC", value="7794", is_primary=True)
    return e


@pytest.fixture
def stub_grounder(il1b_entity, nfkb1_entity):
    """Populate the stub lookup table and patch the grounder for the test."""
    _STUB_TABLE["IL1B"] = il1b_entity
    _STUB_TABLE["NFKB1"] = nfkb1_entity
    with patch("graph.services.ground_mention", side_effect=_stub_ground):
        yield
    _STUB_TABLE.clear()


@pytest.fixture
def seven_model_ppis(db, paper_factory, chunk_factory):
    """Seed 7 RawPPI rows (one per model) for IL1B activates NFKB1."""
    from extract.models import ExtractionRun, RawPPI

    paper = paper_factory(pmid="70001", year=2025)
    chunk = chunk_factory(paper=paper, text="IL1B activates NFKB1 in nucleus pulposus cells.")

    model_names = [
        "qwen3:8b",
        "phi4:14b",
        "gemma3:12b",
        "deepseek-r1:32b",
        "devstral:24b",
        "llama3.1:8b",
        "medgemma:27b",
    ]
    raw_ppis = []
    for model in model_names:
        run, _ = ExtractionRun.objects.get_or_create(
            chunk=chunk,
            model_name=model,
            prompt_version="v1",
            defaults={"status": "done"},
        )
        raw = RawPPI.objects.create(
            run=run,
            subject="IL1B",
            object="NFKB1",
            relation="activates",
            evidence_span=chunk.text,
            evidence_offset_start=0,
            evidence_offset_end=len(chunk.text),
            confidence=0.92,
            ungrounded=False,
        )
        raw_ppis.append(raw)
    return raw_ppis


# ---------------------------------------------------------------------------
# End-to-end test
# ---------------------------------------------------------------------------


def test_nfkb_axis_e2e_integration(
    db,
    nfkb_network,
    stub_grounder,
    seven_model_ppis,
):
    """Full pipeline: RawPPIs → normalize_and_integrate → Edge/evidence/membership."""
    from graph.models import Edge, EdgeEvidence, NetworkEdgeMembership
    from graph.services import (
        BELIEF_THRESHOLD_ACCEPTED,
        normalize_and_integrate,
    )

    raw_ids = [r.pk for r in seven_model_ppis]
    result = normalize_and_integrate(raw_ids)

    # ------------------------------------------------------------------
    # 1. Integration stats
    # ------------------------------------------------------------------
    assert result["edges_touched"] == 1, "One unique (IL1B, activates, NFKB1) edge"
    assert result["evidences_added"] == 7, "7 distinct model extractions"
    assert result["ungrounded"] == 0, "Stub grounder resolves all mentions"

    # ------------------------------------------------------------------
    # 2. Edge exists with correct relation
    # ------------------------------------------------------------------
    edge = Edge.objects.get()
    assert edge.relation == "activates"
    assert edge.source.preferred_label == "IL1B"
    assert edge.target.preferred_label == "NFKB1"

    # ------------------------------------------------------------------
    # 3. Belief score: 1 paper × 7 models → should be ≥ ACCEPTED threshold
    # ------------------------------------------------------------------
    assert edge.belief_score >= BELIEF_THRESHOLD_ACCEPTED, (
        f"1 paper × 7 models should exceed {BELIEF_THRESHOLD_ACCEPTED}, "
        f"got {edge.belief_score:.4f}"
    )
    assert edge.status == "accepted"

    # ------------------------------------------------------------------
    # 4. Counter fields
    # ------------------------------------------------------------------
    assert edge.n_supporting_papers == 1, "All 7 RawPPIs come from the same paper"
    assert edge.n_models_agreeing == 7

    # ------------------------------------------------------------------
    # 5. EdgeEvidence rows link back to every RawPPI
    # ------------------------------------------------------------------
    assert EdgeEvidence.objects.filter(edge=edge).count() == 7

    # ------------------------------------------------------------------
    # 6. NetworkEdgeMembership: edge must appear in nfkb_axis_e2e network
    # ------------------------------------------------------------------
    assert NetworkEdgeMembership.objects.filter(
        network=nfkb_network, edge=edge
    ).exists(), "Edge should be assigned to NF-κB axis network"

    membership = NetworkEdgeMembership.objects.get(network=nfkb_network, edge=edge)
    assert membership.relevance == 1.0


def test_nfkb_axis_dev_json_endpoint(
    db,
    nfkb_network,
    stub_grounder,
    seven_model_ppis,
):
    """After integration the dev JSON endpoint returns the NF-κB edge and nodes."""
    from graph.services import normalize_and_integrate

    raw_ids = [r.pk for r in seven_model_ppis]
    normalize_and_integrate(raw_ids)

    client = Client(HTTP_REMOTE_USER="fchemorion")
    url = f"/graph/dev/networks/{nfkb_network.code}/edges.json"
    response = client.get(url)

    assert response.status_code == 200
    data = response.json()

    # Nodes
    labels = {n["data"]["label"] for n in data["nodes"]}
    assert labels == {"IL1B", "NFKB1"}

    # Each node must have an HGNC IRI
    for node in data["nodes"]:
        assert node["data"]["iri"].startswith(
            "https://identifiers.org/hgnc:"
        ), f"Expected HGNC IRI, got: {node['data']['iri']}"

    # Edge
    assert len(data["edges"]) == 1
    edge_data = data["edges"][0]["data"]
    assert edge_data["source_label"] == "IL1B"
    assert edge_data["target_label"] == "NFKB1"
    assert edge_data["relation"] == "activates"
    assert edge_data["status"] == "accepted"
    assert edge_data["belief"] >= 0.80


def test_nfkb_axis_dev_page_renders(
    db,
    nfkb_network,
    stub_grounder,
    seven_model_ppis,
):
    """The HTML page loads and embeds the Cytoscape.js CDN script."""
    from graph.services import normalize_and_integrate

    raw_ids = [r.pk for r in seven_model_ppis]
    normalize_and_integrate(raw_ids)

    client = Client(HTTP_REMOTE_USER="fchemorion")
    response = client.get(f"/graph/dev/networks/{nfkb_network.code}/")

    assert response.status_code == 200
    # Title contains "NF-" followed by the network title; κ = U+03BA = \xce\xba in UTF-8,
    # B is plain ASCII.
    assert b"NF-\xce\xbaB axis" in response.content
    assert b"cytoscape" in response.content.lower()
