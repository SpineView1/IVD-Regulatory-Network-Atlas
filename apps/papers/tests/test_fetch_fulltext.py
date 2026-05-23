"""Tests for papers.tasks.fetch_fulltext."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from corpus.models import Paper
from papers.tasks import fetch_fulltext, fetch_fulltext_pending


@pytest.fixture(autouse=True)
def _eager(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True


def test_fetch_fulltext_pmc_path_writes_to_minio(db):
    p = Paper.objects.create(
        pmid=1,
        title="x",
        pmcid="PMC11000000",
        ingest_status="classified",
        is_original=True,
    )
    with (
        patch("papers.tasks.EuropePmcClient") as EPC,
        patch("papers.tasks.MinioClient") as MC,
        patch("papers.tasks.section_and_chunk.delay"),
    ):
        EPC.return_value.get_jats_for_pmcid.return_value = b"<article/>"
        fetch_fulltext.delay(1).get(timeout=2)
    p.refresh_from_db()
    assert p.full_text_status == "pmc_jats"
    assert p.fulltext_s3_key.startswith("papers/")
    MC.return_value.put_object.assert_called_once()


def test_fetch_fulltext_no_pmcid_marks_abstract_only(db):
    p = Paper.objects.create(
        pmid=2,
        title="x",
        pmcid="",
        ingest_status="classified",
        is_original=True,
    )
    with (
        patch("papers.tasks.EuropePmcClient"),
        patch("papers.tasks.MinioClient"),
        patch("papers.tasks.section_and_chunk.delay"),
    ):
        fetch_fulltext.delay(2).get(timeout=2)
    p.refresh_from_db()
    assert p.full_text_status == "abstract_only"


def test_fetch_fulltext_europepmc_not_found_falls_to_abstract(db):
    p = Paper.objects.create(
        pmid=3,
        title="x",
        pmcid="PMC99999999",
        ingest_status="classified",
        is_original=True,
    )
    from corpus.clients.europepmc import EuropePmcNotFound

    with (
        patch("papers.tasks.EuropePmcClient") as EPC,
        patch("papers.tasks.MinioClient"),
        patch("papers.tasks.section_and_chunk.delay"),
    ):
        EPC.return_value.get_jats_for_pmcid.side_effect = EuropePmcNotFound("PMC99999999")
        fetch_fulltext.delay(3).get(timeout=2)
    p.refresh_from_db()
    assert p.full_text_status == "abstract_only"


def test_fetch_fulltext_advances_ingest_status_to_fetched(db):
    p = Paper.objects.create(
        pmid=4,
        title="x",
        pmcid="PMC1",
        ingest_status="classified",
        is_original=True,
    )
    with (
        patch("papers.tasks.EuropePmcClient") as EPC,
        patch("papers.tasks.MinioClient"),
        patch("papers.tasks.section_and_chunk.delay"),
    ):
        EPC.return_value.get_jats_for_pmcid.return_value = b"<article/>"
        fetch_fulltext.delay(4).get(timeout=2)
    p.refresh_from_db()
    assert p.ingest_status == "fetched"


def test_fetch_fulltext_idempotent(db):
    Paper.objects.create(
        pmid=5,
        title="x",
        pmcid="PMC1",
        ingest_status="fetched",
        full_text_status="pmc_jats",
        fulltext_s3_key="papers/0000/5.xml",
        is_original=True,
    )
    with patch("papers.tasks.EuropePmcClient") as EPC:
        fetch_fulltext.delay(5).get(timeout=2)
    EPC.return_value.get_jats_for_pmcid.assert_not_called()


def test_fetch_fulltext_generic_exception_sets_fetch_failed(db):
    """Generic network error → full_text_status='fetch_failed' with error recorded."""
    p = Paper.objects.create(
        pmid=20,
        title="x",
        pmcid="PMC20",
        ingest_status="classified",
        is_original=True,
    )
    with (
        patch("papers.tasks.EuropePmcClient") as EPC,
        patch("papers.tasks.MinioClient"),
    ):
        EPC.return_value.get_jats_for_pmcid.side_effect = OSError("connection refused")
        with pytest.raises(OSError):
            fetch_fulltext(20)
    p.refresh_from_db()
    assert p.full_text_status == "fetch_failed"
    assert "connection refused" in p.fulltext_fetch_error


def test_fetch_fulltext_pending_picks_up_fetch_failed_papers(db):
    """fetch_fulltext_pending must re-sweep papers with full_text_status='fetch_failed'."""
    Paper.objects.create(
        pmid=21,
        title="x",
        pmcid="PMC21",
        ingest_status="classified",
        is_original=True,
        full_text_status="fetch_failed",
        fulltext_fetch_error="OSError: connection refused",
    )
    with patch("papers.tasks.fetch_fulltext.delay") as mock_enq:
        fetch_fulltext_pending.delay().get(timeout=2)
    enqueued = {c.args[0] for c in mock_enq.call_args_list}
    assert 21 in enqueued


def test_fetch_fulltext_pending_skips_non_original(db):
    Paper.objects.create(
        pmid=10,
        title="x",
        pmcid="PMC1",
        ingest_status="classified",
        is_original=False,  # not original — skip
    )
    Paper.objects.create(
        pmid=11,
        title="y",
        pmcid="PMC2",
        ingest_status="classified",
        is_original=True,
    )
    with patch("papers.tasks.fetch_fulltext.delay") as mock_enq:
        fetch_fulltext_pending.delay().get(timeout=2)
    enqueued = {c.args[0] for c in mock_enq.call_args_list}
    assert 11 in enqueued
    assert 10 not in enqueued
