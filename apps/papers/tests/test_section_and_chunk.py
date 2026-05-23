"""Tests for papers.tasks.section_and_chunk."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from corpus.models import Paper
from papers.models import Chunk, Section
from papers.tasks import section_and_chunk, section_pending

FIXTURE = Path(__file__).parent / "fixtures" / "sample_jats.xml"


@pytest.fixture(autouse=True)
def _eager(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True


def test_section_and_chunk_parses_jats_from_minio(db):
    p = Paper.objects.create(
        pmid=1,
        title="x",
        pmcid="PMC1",
        ingest_status="fetched",
        full_text_status="pmc_jats",
        fulltext_s3_key="papers/0000/1.xml",
        is_original=True,
    )
    with (
        patch("papers.tasks.MinioClient") as MC,
        patch("corpus.tasks.triage_relevance_cheap.delay"),
    ):
        MC.return_value.get_object.return_value = FIXTURE.read_bytes()
        section_and_chunk.delay(1).get(timeout=10)
    p.refresh_from_db()
    assert p.ingest_status == "chunked"
    sections = list(Section.objects.filter(paper=p))
    assert any(s.doco_type == "Results" for s in sections)
    assert any(s.doco_type == "Introduction" for s in sections)


def test_section_and_chunk_only_creates_chunks_for_results(db):
    p = Paper.objects.create(
        pmid=2,
        title="x",
        pmcid="PMC2",
        ingest_status="fetched",
        full_text_status="pmc_jats",
        fulltext_s3_key="papers/0000/2.xml",
        is_original=True,
    )
    with (
        patch("papers.tasks.MinioClient") as MC,
        patch("corpus.tasks.triage_relevance_cheap.delay"),
    ):
        MC.return_value.get_object.return_value = FIXTURE.read_bytes()
        section_and_chunk.delay(2).get(timeout=10)
    chunked_section_types = {c.section.doco_type for c in Chunk.objects.filter(paper=p)}
    assert "Results" in chunked_section_types
    # Spec §4 says keep Results AND Conclusions (as aux); allow both.
    assert chunked_section_types <= {"Results", "Conclusion", "Abstract"}


def test_section_and_chunk_abstract_only_uses_abstract(db):
    p = Paper.objects.create(
        pmid=3,
        title="A study",
        abstract="HIF1A upregulated in disc cells under hypoxia.",
        ingest_status="fetched",
        full_text_status="abstract_only",
        is_original=True,
    )
    with patch("corpus.tasks.triage_relevance_cheap.delay"):
        section_and_chunk.delay(3).get(timeout=10)
    p.refresh_from_db()
    assert p.ingest_status == "chunked"
    sections = list(Section.objects.filter(paper=p))
    assert len(sections) == 1
    assert sections[0].doco_type == "Abstract"
    assert Chunk.objects.filter(paper=p).count() >= 1


def test_section_and_chunk_idempotent(db):
    p = Paper.objects.create(
        pmid=4,
        title="x",
        abstract="data",
        ingest_status="chunked",
        full_text_status="abstract_only",
        is_original=True,
    )
    section_and_chunk.delay(4).get(timeout=10)
    # Should not re-process; no sections created
    assert Section.objects.filter(paper=p).count() == 0


def test_section_pending_picks_up_fetched_papers(db):
    Paper.objects.create(
        pmid=5,
        title="x",
        ingest_status="fetched",
        full_text_status="abstract_only",
        is_original=True,
    )
    Paper.objects.create(  # not eligible — still classified
        pmid=6,
        title="y",
        ingest_status="classified",
        is_original=True,
    )
    with patch("papers.tasks.section_and_chunk.delay") as mock_enq:
        section_pending.delay().get(timeout=2)
    enqueued = {c.args[0] for c in mock_enq.call_args_list}
    assert 5 in enqueued
    assert 6 not in enqueued
