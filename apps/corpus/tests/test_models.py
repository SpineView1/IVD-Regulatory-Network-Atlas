"""Tests for corpus.models."""

from __future__ import annotations

import pytest
from django.db import IntegrityError

from corpus.models import IngestRun, Paper, PaperRelevance


def test_paper_uses_pmid_as_primary_key(db, paper_minimal):
    assert paper_minimal.pk == 38000123
    assert paper_minimal.pmid == 38000123


def test_paper_pmid_is_unique(db, paper_minimal):
    with pytest.raises(IntegrityError):
        Paper.objects.create(pmid=38000123, title="dup")


def test_paper_default_ingest_status_pending(db, paper_minimal):
    assert paper_minimal.ingest_status == "pending"


def test_paper_ingest_status_transitions(db, paper_minimal):
    for status in [
        "ingested",
        "classified",
        "fetched",
        "chunked",
        "done",
        "failed",
    ]:
        paper_minimal.ingest_status = status
        paper_minimal.save()
        paper_minimal.refresh_from_db()
        assert paper_minimal.ingest_status == status


def test_paper_full_text_status_default_none(db, paper_minimal):
    assert paper_minimal.full_text_status == "none"


def test_paper_full_text_status_choices(db, paper_minimal):
    for status in ["none", "abstract_only", "pmc_jats", "grobid_tei", "fetch_failed"]:
        paper_minimal.full_text_status = status
        paper_minimal.save()


def test_paper_is_original_nullable(db, paper_minimal):
    assert paper_minimal.is_original is None
    paper_minimal.is_original = True
    paper_minimal.save()
    paper_minimal.refresh_from_db()
    assert paper_minimal.is_original is True


def test_paper_jsonb_fields(db):
    p = Paper.objects.create(
        pmid=1,
        title="t",
        authors=[{"last": "A"}, {"last": "B"}],
        mesh_terms=["X", "Y"],
        publication_types=["Review"],
    )
    p.refresh_from_db()
    assert len(p.authors) == 2
    assert "X" in p.mesh_terms


def test_paper_doi_indexed(db, paper_minimal):
    paper_minimal.doi = "10.1234/abc"
    paper_minimal.save()
    found = Paper.objects.filter(doi="10.1234/abc").first()
    assert found == paper_minimal


def test_paper_heartbeat_field(db, paper_minimal):
    assert paper_minimal.ingest_heartbeat is None


def test_paper_attempts_default_zero(db, paper_minimal):
    assert paper_minimal.ingest_attempts == 0


def test_paper_pmcid_optional(db):
    p = Paper.objects.create(pmid=2, title="t", pmcid="PMC1234567")
    p.refresh_from_db()
    assert p.pmcid == "PMC1234567"


def test_paper_fulltext_s3_key_stored(db, paper_minimal):
    paper_minimal.fulltext_s3_key = "papers/3800/38000123.xml"
    paper_minimal.save()
    paper_minimal.refresh_from_db()
    assert paper_minimal.fulltext_s3_key.startswith("papers/")


def test_paper_relevance_round_trip(db, paper_minimal, nfkb_network):
    pr = PaperRelevance.objects.create(
        paper=paper_minimal,
        network=nfkb_network,
        score=0.85,
        classified_by="llm:qwen3:8b",
    )
    assert pr.pk is not None


def test_paper_relevance_unique_per_paper_network(db, paper_minimal, nfkb_network):
    PaperRelevance.objects.create(paper=paper_minimal, network=nfkb_network, score=0.5)
    with pytest.raises(IntegrityError):
        PaperRelevance.objects.create(paper=paper_minimal, network=nfkb_network, score=0.9)


def test_ingest_run_round_trip(db):
    run = IngestRun.objects.create(
        source="pubmed",
        query="dummy",
        n_pmids_seen=5,
        n_papers_created=3,
        n_papers_updated=2,
    )
    assert run.pk is not None
    assert run.finished_at is None
