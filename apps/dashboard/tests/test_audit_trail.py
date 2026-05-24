"""Tests for Task 12 — Audit trail view for a single edge.

Tests:
- GET /networks/edges/<pk>/audit/ returns 200
- Template dashboard/audit_trail.html is used
- Renders evidence rows containing pmid + model_name + relation_logprob
- Shows review history for the edge
- 404 for unknown edge pk
- Evidence table lists RawPPI rows via EdgeEvidence
- DataTables initialisation script is present in the response
"""

from __future__ import annotations

import pytest
from django.test import Client


@pytest.fixture
def client():
    return Client(HTTP_REMOTE_USER="fchemorion")


@pytest.fixture
def full_provenance(db):
    """Create the complete provenance chain for one edge:
    Paper → Section → Chunk → ExtractionRun → RawPPI → EdgeEvidence → Edge
    """
    from datetime import date

    from core.models import OntologyEntity
    from corpus.models import Paper
    from extract.models import ExtractionRun, RawPPI
    from graph.models import Edge, EdgeEvidence, Entity
    from papers.models import Chunk, Section

    paper = Paper.objects.create(
        pmid=99001,
        title="Test Paper on NF-κB",
        journal="Spine",
        publication_date=date(2024, 1, 15),
        ingest_status="chunked",
    )
    section = Section.objects.create(
        paper=paper,
        order_index=0,
        doco_type="section",
        body_text="SIRT1 inhibits NFKB1 activation in disc cells.",
    )
    chunk = Chunk.objects.create(
        section=section,
        paper=paper,
        chunk_index=0,
        text="SIRT1 inhibits NFKB1 activation in disc cells.",
        token_count=10,
        char_offset_start=0,
        char_offset_end=47,
    )
    run = ExtractionRun.objects.create(
        chunk=chunk,
        model_name="qwen3:8b",
        prompt_version="v1",
        status=ExtractionRun.Status.DONE,
    )
    raw_ppi = RawPPI.objects.create(
        run=run,
        subject="SIRT1",
        object="NFKB1",
        relation="inhibits",
        evidence_span="SIRT1 inhibits NFKB1",
        evidence_offset_start=0,
        evidence_offset_end=20,
        confidence=0.92,
        relation_logprob=-0.3,
    )
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
    edge = Edge.objects.create(
        source=e1,
        target=e2,
        relation="inhibits",
        belief_score=0.88,
        status="accepted",
    )
    EdgeEvidence.objects.create(edge=edge, raw_ppi=raw_ppi)
    return edge, raw_ppi, paper, run


@pytest.fixture
def edge_with_reviews(db, full_provenance):
    """Add review rows to the edge."""
    from django.contrib.auth import get_user_model

    from verify.models import Review

    User = get_user_model()
    edge, _raw_ppi, _paper, _run = full_provenance
    reviewer = User.objects.create_user(username="fchemorion_a", email="a@upf.edu")
    Review.objects.create(reviewer=reviewer, edge=edge, decision="approve", comment="Looks good")
    Review.objects.create(reviewer=reviewer, edge=edge, decision="discuss", comment="Wait")
    return edge


class TestAuditTrailView:
    """Tests for GET /networks/edges/<pk>/audit/ (dashboard:audit_trail)."""

    def test_audit_trail_returns_200(self, client, db, full_provenance):
        edge, *_ = full_provenance
        resp = client.get(f"/networks/edges/{edge.pk}/audit/")
        assert resp.status_code == 200

    def test_audit_trail_uses_correct_template(self, client, db, full_provenance):
        edge, *_ = full_provenance
        resp = client.get(f"/networks/edges/{edge.pk}/audit/")
        template_names = [t.name for t in resp.templates]
        assert "dashboard/audit_trail.html" in template_names

    def test_audit_trail_404_for_unknown_edge(self, client, db):
        resp = client.get("/networks/edges/99999/audit/")
        assert resp.status_code == 404

    def test_audit_trail_renders_pmid_in_evidence_table(self, client, db, full_provenance):
        edge, _raw_ppi, paper, _run = full_provenance
        resp = client.get(f"/networks/edges/{edge.pk}/audit/")
        body = resp.content.decode()
        assert str(paper.pmid) in body

    def test_audit_trail_renders_model_name_in_evidence_table(self, client, db, full_provenance):
        edge, _raw_ppi, _paper, run = full_provenance
        resp = client.get(f"/networks/edges/{edge.pk}/audit/")
        body = resp.content.decode()
        assert run.model_name in body

    def test_audit_trail_renders_relation_logprob(self, client, db, full_provenance):
        edge, raw_ppi, _paper, _run = full_provenance
        resp = client.get(f"/networks/edges/{edge.pk}/audit/")
        body = resp.content.decode()
        # logprob is -0.3, so "-0.3" should appear (rendered as float)
        assert "-0.3" in body or "relation_logprob" in body.lower()

    def test_audit_trail_shows_edge_source_and_target(self, client, db, full_provenance):
        edge, *_ = full_provenance
        resp = client.get(f"/networks/edges/{edge.pk}/audit/")
        body = resp.content.decode()
        assert "SIRT1" in body
        assert "NFKB1" in body

    def test_audit_trail_shows_review_history(self, client, db, edge_with_reviews):
        resp = client.get(f"/networks/edges/{edge_with_reviews.pk}/audit/")
        body = resp.content.decode()
        # At least one review row must appear
        assert "approve" in body or "discuss" in body

    def test_audit_trail_shows_review_comment(self, client, db, edge_with_reviews):
        resp = client.get(f"/networks/edges/{edge_with_reviews.pk}/audit/")
        body = resp.content.decode()
        assert "Looks good" in body or "Wait" in body

    def test_audit_trail_includes_datatables_init(self, client, db, full_provenance):
        """DataTables.js must be initialised for the evidence table."""
        edge, *_ = full_provenance
        resp = client.get(f"/networks/edges/{edge.pk}/audit/")
        body = resp.content.decode()
        assert "DataTable" in body or "datatable" in body.lower() or "datatables" in body.lower()

    def test_audit_trail_shows_evidence_span(self, client, db, full_provenance):
        edge, raw_ppi, *_ = full_provenance
        resp = client.get(f"/networks/edges/{edge.pk}/audit/")
        body = resp.content.decode()
        assert raw_ppi.evidence_span in body

    def test_audit_trail_no_reviews_still_renders(self, client, db, full_provenance):
        """Edge with no review history must still render without error."""
        edge, *_ = full_provenance
        resp = client.get(f"/networks/edges/{edge.pk}/audit/")
        assert resp.status_code == 200
