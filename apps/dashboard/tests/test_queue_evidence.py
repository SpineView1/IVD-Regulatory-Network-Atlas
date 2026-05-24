"""Tests for feat(dashboard): evidence text + references in the disagreement queue.

TDD — written before any production code.

Tests verify:
1. edge_evidence_items() helper returns the right shape with evidence_span, pmid,
   pubmed_url, citation, model_name, relation_logprob, confidence.
2. GET disagreement_queue renders evidence_span, PubMed-linked PMID, model_name
   for each conflicting edge.
3. Query count is bounded (no N+1) when there are multiple conflicts.
"""

from __future__ import annotations

from datetime import date

import pytest
from django.test import Client  # noqa: F401 — used below

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    return Client(HTTP_REMOTE_USER="fchemorion")


@pytest.fixture
def network(db):
    from networks.models import Network

    return Network.objects.create(
        code="nfkb_axis",
        category="I",
        title="NF-κB Axis",
        pipeline_status="version_draft",
    )


def _make_conflict_with_evidence(network, *, pmid_a: int, pmid_b: int, label_suffix: str = ""):
    """
    Build a Conflict whose edge_a and edge_b each have one EdgeEvidence →
    RawPPI → ExtractionRun → Chunk → Section → Paper chain.

    Returns (conflict, raw_ppi_a, paper_a, run_a, raw_ppi_b, paper_b, run_b).
    """
    from core.models import OntologyEntity
    from corpus.models import Paper
    from extract.models import ExtractionRun, RawPPI
    from graph.models import Conflict, Edge, EdgeEvidence, Entity, NetworkEdgeMembership
    from papers.models import Chunk, Section

    suf = label_suffix

    oe1 = OntologyEntity.objects.create(
        entity_type="protein",
        preferred_label=f"NFKB1{suf}",
        canonical_uri=f"https://identifiers.org/uniprot:P19838{suf}",
    )
    oe2 = OntologyEntity.objects.create(
        entity_type="protein",
        preferred_label=f"IKBA{suf}",
        canonical_uri=f"https://identifiers.org/uniprot:P25963{suf}",
    )
    e1 = Entity.objects.create(ontology_entity=oe1)
    e2 = Entity.objects.create(ontology_entity=oe2)

    edge_a = Edge.objects.create(source=e1, target=e2, relation="activates", belief_score=0.7)
    edge_b = Edge.objects.create(source=e1, target=e2, relation="inhibits", belief_score=0.6)

    NetworkEdgeMembership.objects.create(network=network, edge=edge_a)
    NetworkEdgeMembership.objects.create(network=network, edge=edge_b)

    # Paper / Section / Chunk / Run / RawPPI for edge_a
    paper_a = Paper.objects.create(
        pmid=pmid_a,
        title=f"Paper activates {suf}",
        journal="Spine",
        publication_date=date(2024, 1, 15),
        ingest_status="chunked",
    )
    sec_a = Section.objects.create(
        paper=paper_a,
        order_index=0,
        doco_type="section",
        body_text=f"NFKB1{suf} activates IKBA{suf} in disc cells.",
    )
    chunk_a = Chunk.objects.create(
        section=sec_a,
        paper=paper_a,
        chunk_index=0,
        text=f"NFKB1{suf} activates IKBA{suf} in disc cells.",
        token_count=10,
        char_offset_start=0,
        char_offset_end=40,
    )
    run_a = ExtractionRun.objects.create(
        chunk=chunk_a,
        model_name="qwen3:8b",
        prompt_version="v1",
        status=ExtractionRun.Status.DONE,
    )
    raw_ppi_a = RawPPI.objects.create(
        run=run_a,
        subject=f"NFKB1{suf}",
        object=f"IKBA{suf}",
        relation="activates",
        evidence_span=f"NFKB1{suf} activates IKBA{suf} in nucleus",
        evidence_offset_start=0,
        evidence_offset_end=30,
        confidence=0.90,
        relation_logprob=-0.1,
    )
    EdgeEvidence.objects.create(edge=edge_a, raw_ppi=raw_ppi_a)

    # Paper / Section / Chunk / Run / RawPPI for edge_b
    paper_b = Paper.objects.create(
        pmid=pmid_b,
        title=f"Paper inhibits {suf}",
        journal="JOR",
        publication_date=date(2023, 6, 1),
        ingest_status="chunked",
    )
    sec_b = Section.objects.create(
        paper=paper_b,
        order_index=0,
        doco_type="section",
        body_text=f"NFKB1{suf} inhibits IKBA{suf}.",
    )
    chunk_b = Chunk.objects.create(
        section=sec_b,
        paper=paper_b,
        chunk_index=0,
        text=f"NFKB1{suf} inhibits IKBA{suf}.",
        token_count=8,
        char_offset_start=0,
        char_offset_end=28,
    )
    run_b = ExtractionRun.objects.create(
        chunk=chunk_b,
        model_name="llama3:70b",
        prompt_version="v1",
        status=ExtractionRun.Status.DONE,
    )
    raw_ppi_b = RawPPI.objects.create(
        run=run_b,
        subject=f"NFKB1{suf}",
        object=f"IKBA{suf}",
        relation="inhibits",
        evidence_span=f"NFKB1{suf} inhibits IKBA{suf} under hypoxia",
        evidence_offset_start=0,
        evidence_offset_end=35,
        confidence=0.85,
        relation_logprob=-0.2,
    )
    EdgeEvidence.objects.create(edge=edge_b, raw_ppi=raw_ppi_b)

    conflict = Conflict.objects.create(
        edge_a=edge_a,
        edge_b=edge_b,
        conflict_type="inter_paper",
        resolution_status="open",
    )

    return conflict, raw_ppi_a, paper_a, run_a, raw_ppi_b, paper_b, run_b


@pytest.fixture
def conflict_with_evidence(db, network):
    conflict, raw_ppi_a, paper_a, run_a, raw_ppi_b, paper_b, run_b = _make_conflict_with_evidence(
        network, pmid_a=10001, pmid_b=10002
    )
    return conflict, raw_ppi_a, paper_a, run_a, raw_ppi_b, paper_b, run_b


# ---------------------------------------------------------------------------
# Tests for edge_evidence_items() helper
# ---------------------------------------------------------------------------


class TestEdgeEvidenceItemsHelper:
    """Unit tests for graph.services.edge_evidence_items()."""

    def test_returns_list_of_dicts(self, db, conflict_with_evidence):
        from graph.services import edge_evidence_items

        conflict, _raw_a, _paper_a, _run_a, *_ = conflict_with_evidence
        items = edge_evidence_items(conflict.edge_a)
        assert isinstance(items, list)
        assert len(items) >= 1

    def test_item_has_required_keys(self, db, conflict_with_evidence):
        from graph.services import edge_evidence_items

        conflict, *_ = conflict_with_evidence
        items = edge_evidence_items(conflict.edge_a)
        item = items[0]
        assert "pmid" in item
        assert "pubmed_url" in item
        assert "citation" in item
        assert "model_name" in item
        assert "relation_logprob" in item
        assert "confidence" in item
        assert "evidence_span" in item

    def test_pubmed_url_format(self, db, conflict_with_evidence):
        from graph.services import edge_evidence_items

        conflict, _raw_a, paper_a, *_ = conflict_with_evidence
        items = edge_evidence_items(conflict.edge_a)
        item = items[0]
        assert item["pubmed_url"] == f"https://pubmed.ncbi.nlm.nih.gov/{paper_a.pmid}/"

    def test_pmid_matches_paper(self, db, conflict_with_evidence):
        from graph.services import edge_evidence_items

        conflict, _raw_a, paper_a, *_ = conflict_with_evidence
        items = edge_evidence_items(conflict.edge_a)
        assert items[0]["pmid"] == paper_a.pmid

    def test_citation_includes_title_journal_year(self, db, conflict_with_evidence):
        from graph.services import edge_evidence_items

        conflict, _raw_a, paper_a, *_ = conflict_with_evidence
        items = edge_evidence_items(conflict.edge_a)
        citation = items[0]["citation"]
        assert paper_a.title in citation
        assert paper_a.journal in citation
        assert str(paper_a.publication_date.year) in citation

    def test_evidence_span_is_verbatim(self, db, conflict_with_evidence):
        from graph.services import edge_evidence_items

        conflict, raw_ppi_a, *_ = conflict_with_evidence
        items = edge_evidence_items(conflict.edge_a)
        assert items[0]["evidence_span"] == raw_ppi_a.evidence_span

    def test_model_name_correct(self, db, conflict_with_evidence):
        from graph.services import edge_evidence_items

        conflict, _raw_a, _paper_a, run_a, *_ = conflict_with_evidence
        items = edge_evidence_items(conflict.edge_a)
        assert items[0]["model_name"] == run_a.model_name

    def test_ordered_by_confidence_desc(self, db, network):
        """When an edge has multiple evidence items, highest confidence comes first."""
        from core.models import OntologyEntity
        from corpus.models import Paper
        from extract.models import ExtractionRun, RawPPI
        from graph.models import Edge, EdgeEvidence, Entity
        from graph.services import edge_evidence_items
        from papers.models import Chunk, Section

        oe1 = OntologyEntity.objects.create(
            entity_type="protein",
            preferred_label="TGFB1_ord",
            canonical_uri="https://identifiers.org/uniprot:P01137_ord",
        )
        oe2 = OntologyEntity.objects.create(
            entity_type="protein",
            preferred_label="SMAD3_ord",
            canonical_uri="https://identifiers.org/uniprot:P84022_ord",
        )
        e1 = Entity.objects.create(ontology_entity=oe1)
        e2 = Entity.objects.create(ontology_entity=oe2)
        edge = Edge.objects.create(source=e1, target=e2, relation="activates", belief_score=0.7)

        for i, (conf, pmid) in enumerate([(0.50, 20001), (0.95, 20002), (0.70, 20003)]):
            paper = Paper.objects.create(
                pmid=pmid,
                title=f"Paper {i}",
                journal="Spine",
                publication_date=date(2024, 1, 1),
                ingest_status="chunked",
            )
            sec = Section.objects.create(
                paper=paper,
                order_index=0,
                doco_type="section",
                body_text="text",
            )
            chunk = Chunk.objects.create(
                section=sec,
                paper=paper,
                chunk_index=0,
                text="text",
                token_count=5,
                char_offset_start=0,
                char_offset_end=4,
            )
            run = ExtractionRun.objects.create(
                chunk=chunk,
                model_name=f"model{i}",
                prompt_version="v1",
                status=ExtractionRun.Status.DONE,
            )
            raw = RawPPI.objects.create(
                run=run,
                subject="TGFB1_ord",
                object="SMAD3_ord",
                relation="activates",
                evidence_span=f"evidence {i}",
                evidence_offset_start=0,
                evidence_offset_end=10,
                confidence=conf,
                relation_logprob=-0.1,
            )
            EdgeEvidence.objects.create(edge=edge, raw_ppi=raw)

        items = edge_evidence_items(edge)
        confidences = [item["confidence"] for item in items]
        assert confidences == sorted(
            confidences, reverse=True
        ), "Should be sorted desc by confidence"

    def test_deduplication_same_raw_ppi(self, db, conflict_with_evidence):
        """No duplicate pmids / raw_ppis in result."""
        from graph.services import edge_evidence_items

        conflict, *_ = conflict_with_evidence
        items = edge_evidence_items(conflict.edge_a)
        pmids = [item["pmid"] for item in items]
        assert len(pmids) == len(set(pmids)), "Duplicate pmids in evidence items"


# ---------------------------------------------------------------------------
# Tests for the disagreement_queue view
# ---------------------------------------------------------------------------


class TestQueueShowsEvidenceText:
    """GET /networks/<code>/queue/ must surface evidence text per conflicting edge."""

    def test_queue_renders_evidence_span_for_edge_a(
        self, client, db, network, conflict_with_evidence
    ):
        conflict, raw_ppi_a, *_ = conflict_with_evidence
        resp = client.get(f"/networks/{network.code}/queue/")
        body = resp.content.decode()
        assert (
            raw_ppi_a.evidence_span in body
        ), f"evidence_span '{raw_ppi_a.evidence_span}' not found in queue HTML"

    def test_queue_renders_evidence_span_for_edge_b(
        self, client, db, network, conflict_with_evidence
    ):
        conflict, _raw_a, _paper_a, _run_a, raw_ppi_b, *_ = conflict_with_evidence
        resp = client.get(f"/networks/{network.code}/queue/")
        body = resp.content.decode()
        assert (
            raw_ppi_b.evidence_span in body
        ), f"evidence_span '{raw_ppi_b.evidence_span}' not found in queue HTML"

    def test_queue_renders_pubmed_link_for_edge_a(
        self, client, db, network, conflict_with_evidence
    ):
        _conflict, _raw_a, paper_a, *_ = conflict_with_evidence
        resp = client.get(f"/networks/{network.code}/queue/")
        body = resp.content.decode()
        expected_url = f"https://pubmed.ncbi.nlm.nih.gov/{paper_a.pmid}/"
        assert expected_url in body, f"PubMed URL '{expected_url}' not found in queue HTML"

    def test_queue_renders_pubmed_link_for_edge_b(
        self, client, db, network, conflict_with_evidence
    ):
        _conflict, _raw_a, _paper_a, _run_a, _raw_b, paper_b, _run_b = conflict_with_evidence
        resp = client.get(f"/networks/{network.code}/queue/")
        body = resp.content.decode()
        expected_url = f"https://pubmed.ncbi.nlm.nih.gov/{paper_b.pmid}/"
        assert expected_url in body, f"PubMed URL '{expected_url}' not found in queue HTML"

    def test_queue_renders_model_name_for_edge_a(self, client, db, network, conflict_with_evidence):
        _conflict, _raw_a, _paper_a, run_a, *_ = conflict_with_evidence
        resp = client.get(f"/networks/{network.code}/queue/")
        body = resp.content.decode()
        assert run_a.model_name in body, f"model_name '{run_a.model_name}' not found in queue HTML"

    def test_queue_renders_model_name_for_edge_b(self, client, db, network, conflict_with_evidence):
        _conflict, _raw_a, _paper_a, _run_a, _raw_b, _paper_b, run_b = conflict_with_evidence
        resp = client.get(f"/networks/{network.code}/queue/")
        body = resp.content.decode()
        assert run_b.model_name in body, f"model_name '{run_b.model_name}' not found in queue HTML"

    def test_queue_renders_paper_citation_title(self, client, db, network, conflict_with_evidence):
        _conflict, _raw_a, paper_a, *_ = conflict_with_evidence
        resp = client.get(f"/networks/{network.code}/queue/")
        body = resp.content.decode()
        assert paper_a.title in body, f"paper title '{paper_a.title}' not found in queue HTML"

    def test_queue_returns_200_with_evidence(self, client, db, network, conflict_with_evidence):
        resp = client.get(f"/networks/{network.code}/queue/")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Query-count guard: no N+1 across evidence when there are multiple conflicts
# ---------------------------------------------------------------------------


class TestQueueQueryCount:
    """The queue must not produce N+1 queries across evidence items."""

    def test_queue_bounded_queries_with_multiple_conflicts(
        self, client, db, network, django_assert_max_num_queries
    ):
        """2 conflicts (= 4 edges, 4 evidence chains) must stay under 30 queries."""
        _make_conflict_with_evidence(network, pmid_a=30001, pmid_b=30002, label_suffix="_q1")
        _make_conflict_with_evidence(network, pmid_a=30003, pmid_b=30004, label_suffix="_q2")

        with django_assert_max_num_queries(30):
            resp = client.get(f"/networks/{network.code}/queue/")
        assert resp.status_code == 200
