"""Tests for papers.tasks.classify_original."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from corpus.models import Paper
from papers.models import PaperClassification
from papers.tasks import classify_original, classify_pending


@pytest.fixture(autouse=True)
def _eager(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True


def test_cheap_path_marks_review_as_non_original(db):
    p = Paper.objects.create(
        pmid=1,
        title="A review",
        abstract="x",
        publication_types=["Review"],
        ingest_status="ingested",
    )
    with patch("papers.tasks.fetch_fulltext.delay"):
        classify_original.delay(1).get(timeout=2)
    p.refresh_from_db()
    assert p.is_original is False
    pc = PaperClassification.objects.get(paper=p)
    assert pc.classifier == "rule:pubtype"
    assert pc.is_original is False


def test_cheap_path_marks_meta_analysis_as_non_original(db):
    p = Paper.objects.create(
        pmid=2,
        title="A meta",
        abstract="x",
        publication_types=["Meta-Analysis"],
        ingest_status="ingested",
    )
    with patch("papers.tasks.fetch_fulltext.delay"):
        classify_original.delay(2).get(timeout=2)
    p.refresh_from_db()
    assert p.is_original is False


def test_cheap_path_marks_systematic_review_as_non_original(db):
    p = Paper.objects.create(
        pmid=3,
        title="x",
        abstract="x",
        publication_types=["Systematic Review"],
        ingest_status="ingested",
    )
    with patch("papers.tasks.fetch_fulltext.delay"):
        classify_original.delay(3).get(timeout=2)
    p.refresh_from_db()
    assert p.is_original is False


def test_llm_path_invoked_when_pubtype_ambiguous(db):
    p = Paper.objects.create(
        pmid=4,
        title="A study",
        abstract="Original data.",
        publication_types=["Journal Article"],
        ingest_status="ingested",
    )
    fake_llm_response = {
        "response": json.dumps(
            {
                "is_original": True,
                "confidence": 0.93,
                "reason": "Reports primary experiments.",
            }
        )
    }
    with patch("papers.tasks.OllamaClient") as M, patch("papers.tasks.fetch_fulltext.delay"):
        M.return_value.generate.return_value = fake_llm_response
        classify_original.delay(4).get(timeout=2)
    p.refresh_from_db()
    assert p.is_original is True
    pc = PaperClassification.objects.get(paper=p)
    assert pc.classifier == "llm:qwen3:8b"
    assert 0.9 < pc.confidence < 1.0


def test_llm_path_returns_non_original(db):
    p = Paper.objects.create(
        pmid=5,
        title="An editorial",
        abstract="Opinion piece.",
        publication_types=["Journal Article"],
        ingest_status="ingested",
    )
    fake_response = {
        "response": json.dumps(
            {
                "is_original": False,
                "confidence": 0.85,
                "reason": "Editorial opinion, no primary data.",
            }
        )
    }
    with patch("papers.tasks.OllamaClient") as M, patch("papers.tasks.fetch_fulltext.delay"):
        M.return_value.generate.return_value = fake_response
        classify_original.delay(5).get(timeout=2)
    p.refresh_from_db()
    assert p.is_original is False


def test_llm_bad_json_falls_back_to_rule(db):
    p = Paper.objects.create(
        pmid=6,
        title="A study",
        abstract="Data.",
        publication_types=["Journal Article"],
        ingest_status="ingested",
    )
    with patch("papers.tasks.OllamaClient") as M, patch("papers.tasks.fetch_fulltext.delay"):
        M.return_value.generate.return_value = {"response": "not json {{{"}
        classify_original.delay(6).get(timeout=2)
    p.refresh_from_db()
    # Fallback: default to is_original=True (conservative — keeps it in pipeline)
    assert p.is_original is True
    pc = PaperClassification.objects.get(paper=p)
    assert pc.classifier == "rule:pubtype"


def test_classify_original_advances_ingest_status_to_classified(db):
    p = Paper.objects.create(
        pmid=7,
        title="A review",
        publication_types=["Review"],
        ingest_status="ingested",
    )
    with patch("papers.tasks.fetch_fulltext.delay"):
        classify_original.delay(7).get(timeout=2)
    p.refresh_from_db()
    assert p.ingest_status == "classified"


def test_classify_pending_picks_up_unclassified_papers(db):
    Paper.objects.create(pmid=8, title="x", ingest_status="ingested")
    Paper.objects.create(pmid=9, title="y", ingest_status="pending")  # not eligible
    with patch("papers.tasks.classify_original.delay") as mock_enqueue:
        classify_pending.delay().get(timeout=2)
    enqueued = {c.args[0] for c in mock_enqueue.call_args_list}
    assert 8 in enqueued
    assert 9 not in enqueued


def test_classify_original_is_idempotent(db):
    """Calling classify_original twice must not create two PaperClassification rows."""
    p = Paper.objects.create(
        pmid=10,
        title="A study",
        abstract="data",
        publication_types=["Journal Article"],
        ingest_status="classified",
        is_original=True,  # already classified
    )
    PaperClassification.objects.create(
        paper=p, is_original=True, confidence=0.9, classifier="llm:qwen3:8b"
    )
    with patch("papers.tasks.OllamaClient") as M:
        classify_original.delay(10).get(timeout=2)
    # No second call to LLM; still exactly one classification row.
    M.return_value.generate.assert_not_called()
    assert PaperClassification.objects.filter(paper=p).count() == 1
