"""Tests for corpus.tasks.ingest_paper."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from corpus.clients.ncbi import PaperMetadata
from corpus.models import Paper
from corpus.tasks import ingest_paper
from schedule.models import RateLimitBucket


@pytest.fixture(autouse=True)
def _eager(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True


@pytest.fixture(autouse=True)
def _buckets(db):
    RateLimitBucket.objects.create(
        provider="ncbi_eutils", capacity=10, refill_per_sec=10.0, current_tokens=10.0
    )
    RateLimitBucket.objects.create(
        provider="pubtator3", capacity=10, refill_per_sec=10.0, current_tokens=10.0
    )


def _stub_meta(pmid: int = 38000123) -> PaperMetadata:
    return PaperMetadata(
        pmid=pmid,
        title="A hypoxia study",
        abstract="HIF1A upregulated.",
        journal="Spine",
        doi="10.1/x",
        pmcid="PMC11000000",
        publication_date=date(2024, 5, 1),
        entrez_date=date(2024, 5, 2),
        publication_types=["Journal Article"],
        mesh_terms=["Intervertebral Disc"],
        authors=[{"last": "Doe", "first": "Jane"}],
    )


def test_ingest_paper_creates_row(db):
    with (
        patch("corpus.tasks.NcbiClient") as M,
        patch("corpus.tasks.PubtatorClient") as P,
        patch("papers.tasks.classify_original.delay"),
    ):
        M.return_value.efetch.return_value = [_stub_meta()]
        P.return_value.get_annotations.return_value = [
            {"text": "HIF1A", "type": "Gene", "identifier": "3091"}
        ]
        ingest_paper.delay(38000123).get(timeout=2)
    p = Paper.objects.get(pmid=38000123)
    assert p.title.startswith("A hypoxia study")
    assert p.doi == "10.1/x"
    assert p.pmcid == "PMC11000000"
    assert p.ingest_status == "ingested"


def test_ingest_paper_stores_pubtator_entities(db):
    with (
        patch("corpus.tasks.NcbiClient") as M,
        patch("corpus.tasks.PubtatorClient") as P,
        patch("papers.tasks.classify_original.delay"),
    ):
        M.return_value.efetch.return_value = [_stub_meta()]
        P.return_value.get_annotations.return_value = [
            {"text": "HIF1A", "type": "Gene", "identifier": "3091"},
            {"text": "NFKB1", "type": "Gene", "identifier": "4790"},
        ]
        ingest_paper.delay(38000123).get(timeout=2)
    p = Paper.objects.get(pmid=38000123)
    texts = {e["text"] for e in p.pubtator_entities}
    assert "HIF1A" in texts
    assert "NFKB1" in texts


def test_ingest_paper_is_idempotent(db):
    Paper.objects.create(pmid=38000123, title="seed", ingest_status="ingested")
    with (
        patch("corpus.tasks.NcbiClient") as M,
        patch("corpus.tasks.PubtatorClient"),
    ):
        M.return_value.efetch.return_value = [_stub_meta()]
        ingest_paper.delay(38000123).get(timeout=2)
    # Existing row should be preserved (no IntegrityError, no second row).
    assert Paper.objects.count() == 1
    # Short-circuit must prevent any re-work: efetch must NOT have been called.
    M.return_value.efetch.assert_not_called()


def test_ingest_paper_missing_efetch_marks_failed(db):
    with (
        patch("corpus.tasks.NcbiClient") as M,
        patch("corpus.tasks.PubtatorClient"),
    ):
        M.return_value.efetch.return_value = []
        ingest_paper.delay(99999).get(timeout=2)
    p = Paper.objects.get(pmid=99999)
    assert p.ingest_status == "ingest_failed"


def test_ingest_paper_pubtator_failure_does_not_block(db):
    with (
        patch("corpus.tasks.NcbiClient") as M,
        patch("corpus.tasks.PubtatorClient") as P,
        patch("papers.tasks.classify_original.delay"),
    ):
        M.return_value.efetch.return_value = [_stub_meta()]
        P.return_value.get_annotations.side_effect = RuntimeError("pubtator down")
        ingest_paper.delay(38000123).get(timeout=2)
    p = Paper.objects.get(pmid=38000123)
    assert p.ingest_status == "ingested"
    assert p.pubtator_entities == []
