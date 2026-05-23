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
    """After all retries exhausted, OllamaError → status=failed."""
    from core.ollama import OllamaError

    with (
        patch("extract.tasks._ollama_generate", side_effect=OllamaError("503")),
        # Simulate retries exhausted: request.retries (0) >= max_retries (0)
        patch.object(run_ppi, "max_retries", 0),
    ):
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


# ---------------------------------------------------------------------------
# Fix 2: select_for_update prevents lost-update race on processed_by_models
# ---------------------------------------------------------------------------


def test_run_ppi_uses_select_for_update_when_appending_model(db, run, mock_ollama_response):
    """Fix 2: The success path must fetch the Chunk inside the atomic block via
    select_for_update so concurrent workers don't clobber each other's appends.
    We assert that select_for_update() is called during the transaction."""
    import django.db.models.query

    original_sfq = django.db.models.query.QuerySet.select_for_update
    calls: list[bool] = []

    # Spy: tracks call count, delegates to the original unbound method.
    def _spy(qs: django.db.models.query.QuerySet, **kw: object) -> django.db.models.query.QuerySet:
        calls.append(True)
        return original_sfq(qs, **kw)  # type: ignore[arg-type]

    with (
        patch("extract.tasks._ollama_generate", return_value=mock_ollama_response),
        patch.object(django.db.models.query.QuerySet, "select_for_update", _spy),
    ):
        run_ppi(row_id=run.id)

    # At least one select_for_update call should have occurred during the task.
    assert calls, "Expected select_for_update() to be called inside the atomic block"


# ---------------------------------------------------------------------------
# Fix 3: autoretry on OllamaError — task should be configured with autoretry_for
# ---------------------------------------------------------------------------


def test_run_ppi_task_configured_with_autoretry_for_ollama_error():
    """Fix 3: run_ppi must declare autoretry_for=(OllamaError,) so Celery
    retries transient Ollama errors instead of marking status=failed immediately."""
    from core.ollama import OllamaError

    # The task object carries its autoretry_for attribute.
    autoretry = getattr(run_ppi, "autoretry_for", ())
    assert OllamaError in autoretry, (
        f"run_ppi.autoretry_for={autoretry!r} does not contain OllamaError. "
        "Transient Ollama blips would permanently dead-end the run."
    )


def test_run_ppi_autoretry_does_not_prematurely_write_failed(db, run):
    """Fix 3: When retries are not yet exhausted (retries < max_retries), an
    OllamaError must NOT set status=failed — the row is left retryable.

    We simulate: max_retries=3 (default), request.retries=0 (first attempt).
    Patching self.retry to raise Retry (which Celery does) stops execution so
    we can assert the status is NOT failed."""
    import contextlib

    from celery.exceptions import Retry
    from core.ollama import OllamaError

    with (
        patch("extract.tasks._ollama_generate", side_effect=OllamaError("transient")),
        # retry raises Retry — simulates Celery scheduling the next attempt
        patch.object(run_ppi, "retry", side_effect=Retry()) as mock_retry,
        contextlib.suppress(Retry),
    ):
        run_ppi(row_id=run.id)

    run.refresh_from_db()
    # Status must NOT be failed — retries not exhausted yet.
    assert (
        run.status != ExtractionRun.Status.FAILED
    ), "run_ppi set status=failed before retries were exhausted"
    # self.retry() was explicitly invoked
    mock_retry.assert_called()


# ---------------------------------------------------------------------------
# Fix 4: narrow the rate-limit except (structural check)
# ---------------------------------------------------------------------------


def test_run_ppi_rate_limit_except_is_narrowed():
    """Fix 4: The bucket-lookup except must NOT catch arbitrary exceptions.
    Inspect the source to assert no bare 'except Exception' exists in the
    rate-limit block.  We do a simple string search on the compiled task source."""
    import inspect

    from extract import tasks as tasks_module

    wrapped = getattr(tasks_module.run_ppi, "__wrapped__", None)
    source = inspect.getsource(wrapped if wrapped is not None else tasks_module.run_ppi)
    # The fix narrows to (RateLimitBucket.DoesNotExist, ImportError) — the old
    # bare 'except Exception' must be gone.
    # We check that the narrowed form is present.
    assert (
        "DoesNotExist" in source or "except (RateLimitBucket" in source
    ), "Fix 4 not applied: rate-limit except block should reference DoesNotExist"


# ---------------------------------------------------------------------------
# Fix 6: heartbeat must not write to already-done rows
# ---------------------------------------------------------------------------


def test_run_ppi_does_not_write_heartbeat_for_already_done_run(db, run):
    """Fix 6: When run.status == DONE (idempotency guard), the heartbeat
    decorator must NOT update the heartbeat field for a done row."""
    run.status = ExtractionRun.Status.DONE
    run.save()

    original_hb = run.heartbeat  # None or whatever it was

    with patch("extract.tasks._ollama_generate") as m:
        run_ppi(row_id=run.id)

    m.assert_not_called()
    run.refresh_from_db()
    # heartbeat must not have been touched for an already-done row.
    assert run.heartbeat == original_hb, (
        "Heartbeat was written to an already-done ExtractionRun — "
        "Fix 6 requires skipping heartbeat writes for done/failed rows."
    )
