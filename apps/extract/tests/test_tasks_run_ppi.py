"""Tests for extract.tasks.run_ppi — the per-(chunk, model) extractor task."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from extract.models import ExtractionRun, PromptTemplate, RawPPI
from extract.tasks import run_ppi


@pytest.fixture
def prompt(db):
    # The seed migration inserts 1.0.0 as active; deactivate it and use ours.
    PromptTemplate.objects.all().update(is_active=False)
    return PromptTemplate.objects.create(
        version="1.0.0-test", body="p {{CHUNK_TEXT}}", is_active=True
    )


@pytest.fixture
def chunk(db, prompt):
    from corpus.models import Paper
    from papers.models import Chunk, Section

    paper = Paper.objects.create(pmid=22222222, title="t", abstract="a")
    section = Section.objects.create(
        paper=paper, doco_type="Results", order_index=0, body_text="IL1B activates MMP13."
    )
    return Chunk.objects.create(
        section=section,
        chunk_index=0,
        text="IL1B activates MMP13.",
        token_count=4,
        char_offset_start=0,
        char_offset_end=21,
    )


@pytest.fixture
def run(db, prompt, chunk):
    return ExtractionRun.objects.create(
        chunk=chunk, model_name="qwen3:8b", prompt_version="1.0.0-test"
    )


@pytest.fixture
def mock_ollama_response():
    response_text = json.dumps(
        {
            "ppis": [
                {
                    "subject": "IL1B",
                    "object": "MMP13",
                    "relation": "activates",
                    "evidence_span": "IL1B activates MMP13.",
                    "evidence_offset_start": 0,
                    "evidence_offset_end": 21,
                    "cell_type": None,
                    "stimulus": None,
                    "confidence": 0.91,
                }
            ]
        }
    )
    return response_text, -0.13, 50


def test_run_ppi_marks_run_done(db, run, mock_ollama_response):
    with patch("extract.tasks._ollama_generate", return_value=mock_ollama_response):
        run_ppi(row_id=run.id)
    run.refresh_from_db()
    assert run.status == ExtractionRun.Status.DONE


def test_run_ppi_creates_raw_ppi_rows(db, run, mock_ollama_response):
    with patch("extract.tasks._ollama_generate", return_value=mock_ollama_response):
        run_ppi(row_id=run.id)
    assert RawPPI.objects.filter(run=run).count() == 1
    ppi = RawPPI.objects.get(run=run)
    assert ppi.subject == "IL1B"
    assert ppi.relation_logprob == pytest.approx(-0.13)


def test_run_ppi_stores_relation_as_string(db, run, mock_ollama_response):
    """The relation field on RawPPI must be a string, not an enum object."""
    with patch("extract.tasks._ollama_generate", return_value=mock_ollama_response):
        run_ppi(row_id=run.id)
    ppi = RawPPI.objects.get(run=run)
    assert isinstance(ppi.relation, str)
    assert ppi.relation == "activates"


def test_run_ppi_records_timing(db, run, mock_ollama_response):
    with patch("extract.tasks._ollama_generate", return_value=mock_ollama_response):
        run_ppi(row_id=run.id)
    run.refresh_from_db()
    assert run.started_at is not None
    assert run.finished_at is not None
    assert run.duration_ms is not None
    assert run.response_tokens == 50


def test_run_ppi_increments_attempts(db, run, mock_ollama_response):
    assert run.attempts == 0
    with patch("extract.tasks._ollama_generate", return_value=mock_ollama_response):
        run_ppi(row_id=run.id)
    run.refresh_from_db()
    assert run.attempts == 1


def test_run_ppi_idempotent_when_already_done(db, run, mock_ollama_response):
    run.status = ExtractionRun.Status.DONE
    run.save()
    with patch("extract.tasks._ollama_generate", return_value=mock_ollama_response) as m:
        run_ppi(row_id=run.id)
    m.assert_not_called()
    assert RawPPI.objects.filter(run=run).count() == 0


def test_run_ppi_marks_failed_on_exception(db, run):
    from core.ollama import OllamaError

    with patch("extract.tasks._ollama_generate", side_effect=OllamaError("503")):
        run_ppi(row_id=run.id)
    run.refresh_from_db()
    assert run.status == ExtractionRun.Status.FAILED
    assert "503" in run.error


def test_run_ppi_marks_failed_on_invalid_response(db, run):
    with patch("extract.tasks._ollama_generate", return_value=("not json", None, 0)):
        run_ppi(row_id=run.id)
    run.refresh_from_db()
    assert run.status == ExtractionRun.Status.FAILED


def test_run_ppi_handles_empty_ppi_list(db, run):
    response_text = json.dumps({"ppis": []})
    with patch(
        "extract.tasks._ollama_generate",
        return_value=(response_text, None, 12),
    ):
        run_ppi(row_id=run.id)
    run.refresh_from_db()
    assert run.status == ExtractionRun.Status.DONE
    assert RawPPI.objects.filter(run=run).count() == 0


def test_run_ppi_appends_model_to_chunk_processed_by_models(db, run, mock_ollama_response):
    """After successful run, model slug appended to Chunk.processed_by_models."""
    from papers.models import Chunk

    with patch("extract.tasks._ollama_generate", return_value=mock_ollama_response):
        run_ppi(row_id=run.id)

    chunk = Chunk.objects.get(pk=run.chunk_id)
    assert run.model_name in chunk.processed_by_models
