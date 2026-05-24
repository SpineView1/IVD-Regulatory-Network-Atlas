"""Tests for Task 10 — per-network drill-down view.

Tests:
- GET /networks/<code>/ returns 200
- Template network_detail.html is used
- Cytoscape partial cytoscape_init.html is included
- Edge JSON URL is embedded in the page
- ModelVersion panel shows semver list
- Download links point to the Phase 4 download view
- 404 for unknown network code
"""

from __future__ import annotations

import pytest
from django.test import Client

from networks.models import Network


@pytest.fixture
def client():
    return Client(HTTP_REMOTE_USER="fchemorion")


@pytest.fixture
def network(db):
    return Network.objects.create(
        code="nfkb_axis",
        category="I",
        title="NF-κB Axis",
        pipeline_status="version_draft",
    )


@pytest.fixture
def model_version(db, network):
    from sbml.models import ModelVersion

    mv = ModelVersion.objects.create(
        network=network,
        semver="1.2.0",
        n_species=5,
        n_reactions=4,
        n_edges=4,
        zip_s3_key="sbml/nfkb_axis/v1.2.0.zip",
        sbml_s3_key="sbml/nfkb_axis/v1.2.0.xml",
        csv_s3_key="sbml/nfkb_axis/v1.2.0.csv",
    )
    mv.freeze()
    return mv


@pytest.fixture
def draft_version(db, network):
    """A non-frozen draft version — should NOT appear in the versions panel."""
    from sbml.models import ModelVersion

    return ModelVersion.objects.create(
        network=network,
        semver="1.3.0",
        n_species=5,
        n_reactions=4,
        n_edges=4,
    )


class TestNetworkDetailView:
    """Tests for GET /networks/<code>/ (dashboard:network_detail)."""

    def test_network_detail_returns_200(self, client, db, network):
        resp = client.get(f"/networks/{network.code}/")
        assert resp.status_code == 200

    def test_network_detail_404_for_unknown_code(self, client, db):
        resp = client.get("/networks/nonexistent_code/")
        assert resp.status_code == 404

    def test_network_detail_shows_network_title(self, client, db, network):
        resp = client.get(f"/networks/{network.code}/")
        body = resp.content.decode()
        assert "NF-κB Axis" in body

    def test_network_detail_uses_template(self, client, db, network):
        resp = client.get(f"/networks/{network.code}/")
        template_names = [t.name for t in resp.templates]
        assert "dashboard/network_detail.html" in template_names

    def test_network_detail_includes_cytoscape_partial(self, client, db, network):
        """Cytoscape init partial must be included."""
        resp = client.get(f"/networks/{network.code}/")
        template_names = [t.name for t in resp.templates]
        assert "dashboard/partials/cytoscape_init.html" in template_names

    def test_network_detail_embeds_edges_json_url(self, client, db, network):
        """The edges JSON URL should appear in the rendered HTML."""
        resp = client.get(f"/networks/{network.code}/")
        body = resp.content.decode()
        assert "edges.json" in body

    def test_network_detail_shows_frozen_versions(self, client, db, network, model_version):
        """Frozen ModelVersions should appear in the versions panel."""
        resp = client.get(f"/networks/{network.code}/")
        body = resp.content.decode()
        assert "1.2.0" in body

    def test_network_detail_hides_draft_versions(
        self, client, db, network, model_version, draft_version
    ):
        """Draft (non-frozen) versions must not appear."""
        resp = client.get(f"/networks/{network.code}/")
        body = resp.content.decode()
        assert "1.2.0" in body
        assert "1.3.0" not in body

    def test_network_detail_download_links_point_to_sbml_download_view(
        self, client, db, network, model_version
    ):
        """Download links for each frozen version should reference the sbml:download URL."""
        resp = client.get(f"/networks/{network.code}/")
        body = resp.content.decode()
        # The download URL pattern: /networks/<code>/v/<semver>/download
        assert f"/networks/{network.code}/v/1.2.0/download" in body

    def test_network_detail_shows_pipeline_status(self, client, db, network):
        resp = client.get(f"/networks/{network.code}/")
        body = resp.content.decode()
        assert "version_draft" in body

    def test_network_detail_no_versions_still_renders(self, client, db, network):
        """View works even with no frozen versions."""
        resp = client.get(f"/networks/{network.code}/")
        assert resp.status_code == 200

    def test_cytoscape_init_contains_edges_json_variable(self, client, db, network):
        """The cytoscape_init partial should define the edgesUrl JS variable."""
        resp = client.get(f"/networks/{network.code}/")
        body = resp.content.decode()
        assert "edgesUrl" in body or "edges_json_url" in body.lower() or "edges.json" in body


def _add_edge_with_evidence(network, *, pmid, span, model="qwen3:8b"):
    """Seed one edge in `network` with a full EdgeEvidence provenance chain."""
    from core.models import OntologyEntity
    from corpus.models import Paper
    from extract.models import ExtractionRun, RawPPI
    from graph.models import Edge, EdgeEvidence, Entity, NetworkEdgeMembership
    from papers.models import Chunk, Section

    oe1 = OntologyEntity.objects.create(entity_type="protein", preferred_label="TNF")
    oe2 = OntologyEntity.objects.create(entity_type="protein", preferred_label="IL6")
    src = Entity.objects.create(ontology_entity=oe1)
    tgt = Entity.objects.create(ontology_entity=oe2)
    edge = Edge.objects.create(
        source=src,
        target=tgt,
        relation="activates",
        status="candidate",
        belief_score=0.6,
        n_supporting_papers=1,
        n_models_agreeing=1,
    )
    NetworkEdgeMembership.objects.create(network=network, edge=edge, relevance=1.0)
    paper = Paper.objects.create(
        pmid=pmid,
        title="TNF and IL6 in disc degeneration",
        journal="Spine",
        publication_date="2024-01-01",
        ingest_status="chunked",
    )
    sec = Section.objects.create(paper=paper, doco_type="Results", order_index=0, body_text=span)
    chunk = Chunk.objects.create(
        section=sec,
        chunk_index=0,
        text=span,
        char_offset_start=0,
        char_offset_end=len(span),
        token_count=12,
    )
    run = ExtractionRun.objects.create(
        chunk=chunk, model_name=model, prompt_version="v1", status=ExtractionRun.Status.DONE
    )
    raw = RawPPI.objects.create(
        run=run,
        subject="TNF",
        object="IL6",
        relation="activates",
        evidence_span=span,
        evidence_offset_start=0,
        evidence_offset_end=len(span),
        confidence=0.9,
        relation_logprob=-0.1,
    )
    EdgeEvidence.objects.create(edge=edge, raw_ppi=raw)
    return edge


def test_network_detail_shows_edge_evidence_and_references(client, network):
    span = "TNF-alpha markedly upregulated IL6 in nucleus pulposus cells."
    edge = _add_edge_with_evidence(network, pmid=41356258, span=span)
    resp = client.get(f"/networks/{network.code}/")
    body = resp.content.decode()
    assert resp.status_code == 200
    assert span in body  # verbatim evidence sentence
    assert "41356258" in body  # PMID
    assert "pubmed.ncbi.nlm.nih.gov/41356258" in body  # PubMed reference link
    assert "qwen3:8b" in body  # extracting model
    assert f"/networks/edges/{edge.pk}/audit/" in body  # link to full audit trail
