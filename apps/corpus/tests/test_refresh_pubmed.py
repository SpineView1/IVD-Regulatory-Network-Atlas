"""Tests for corpus.tasks.refresh_pubmed."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from corpus.models import IngestRun, Paper
from corpus.tasks import refresh_pubmed
from schedule.models import RateLimitBucket, Watermark


@pytest.fixture(autouse=True)
def _eager(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True


@pytest.fixture(autouse=True)
def _bucket(db):
    RateLimitBucket.objects.create(
        provider="ncbi_eutils", capacity=10, refill_per_sec=10.0, current_tokens=10.0
    )


def test_refresh_pubmed_calls_esearch_and_enqueues_ingest(db):
    pmids = [38000123, 38000124]
    with (
        patch("corpus.tasks.NcbiClient") as MockCls,
        patch("corpus.tasks.ingest_paper.delay") as mock_enqueue,
    ):
        instance = MockCls.return_value
        instance.esearch.return_value = pmids
        result = refresh_pubmed.delay().get(timeout=2)
    assert result["n_pmids_seen"] == 2
    assert mock_enqueue.call_count == 2


def test_refresh_pubmed_creates_ingest_run_row(db):
    with (
        patch("corpus.tasks.NcbiClient") as MockCls,
        patch("corpus.tasks.ingest_paper.delay"),
    ):
        instance = MockCls.return_value
        instance.esearch.return_value = [1, 2, 3]
        refresh_pubmed.delay().get(timeout=2)
    runs = list(IngestRun.objects.all())
    assert len(runs) == 1
    assert runs[0].source == "pubmed"
    assert runs[0].n_pmids_seen == 3
    assert runs[0].finished_at is not None


def test_refresh_pubmed_advances_watermark(db):
    with (
        patch("corpus.tasks.NcbiClient") as MockCls,
        patch("corpus.tasks.ingest_paper.delay"),
    ):
        instance = MockCls.return_value
        instance.esearch.return_value = [38000125, 38000123, 38000124]
        refresh_pubmed.delay().get(timeout=2)
    wm = Watermark.objects.get(source="pubmed")
    assert wm.last_pmid_seen == 38000125


def test_refresh_pubmed_uses_incremental_query_when_watermark_exists(db):
    Watermark.objects.create(source="pubmed", last_entrez_date=date(2024, 1, 1))
    with (
        patch("corpus.tasks.NcbiClient") as MockCls,
        patch("corpus.tasks.ingest_paper.delay"),
    ):
        instance = MockCls.return_value
        instance.esearch.return_value = []
        refresh_pubmed.delay().get(timeout=2)
        called_query = instance.esearch.call_args.kwargs["query"]
        assert "EDAT" in called_query


def test_refresh_pubmed_skips_existing_pmids(db):
    Paper.objects.create(pmid=38000123, title="already here")
    with (
        patch("corpus.tasks.NcbiClient") as MockCls,
        patch("corpus.tasks.ingest_paper.delay") as mock_enqueue,
    ):
        instance = MockCls.return_value
        instance.esearch.return_value = [38000123, 38000999]
        refresh_pubmed.delay().get(timeout=2)
    enqueued = {c.args[0] for c in mock_enqueue.call_args_list}
    assert enqueued == {38000999}
