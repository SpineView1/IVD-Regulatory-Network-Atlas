"""Tests for extract.tasks.requeue_transient_extraction_failures.

The sweep re-queues extraction runs that failed on a transient network error
(e.g. the Ollama/VPN link dropping mid-request) so the pipeline self-heals,
while leaving permanent failures and exhausted-attempt runs untouched.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from extract.models import ExtractionRun, PromptTemplate
from extract.tasks import requeue_transient_extraction_failures


@pytest.fixture
def chunk(db):
    PromptTemplate.objects.all().update(is_active=False)
    PromptTemplate.objects.create(version="1.0.0-rq", body="p {{CHUNK_TEXT}}", is_active=True)
    from corpus.models import Paper
    from papers.models import Chunk, Section

    paper = Paper.objects.create(pmid=44444444, title="t", abstract="a")
    section = Section.objects.create(paper=paper, doco_type="Results", order_index=0, body_text="x")
    return Chunk.objects.create(
        section=section,
        chunk_index=0,
        text="chunk-0",
        token_count=4,
        char_offset_start=0,
        char_offset_end=7,
    )


def _run(chunk, *, model="qwen3:8b", status="failed", error="", attempts=1):
    return ExtractionRun.objects.create(
        chunk=chunk,
        model_name=model,
        prompt_version="1.0.0-rq",
        status=status,
        error=error,
        attempts=attempts,
    )


@pytest.fixture(autouse=True)
def _single_model(settings):
    # Pin the active roster so dispatch targets a real queue deterministically.
    settings.EXTRACTION_ACTIVE_MODELS = ["qwen3:8b"]


def test_requeues_transient_network_failure(db, chunk):
    run = _run(chunk, error="ConnectError [Errno -2] Name or service not known")
    with patch("extract.tasks.run_ppi.apply_async") as dispatch:
        result = requeue_transient_extraction_failures()
    run.refresh_from_db()
    assert run.status == ExtractionRun.Status.QUEUED
    assert run.error == ""
    assert result == {"requeued": 1}
    dispatch.assert_called_once()
    assert dispatch.call_args.kwargs["queue"] == "q.extract.qwen3_8b"


def test_leaves_permanent_failure_untouched(db, chunk):
    run = _run(chunk, error="ValidationError: ppis.0.relation is not a valid enum member")
    with patch("extract.tasks.run_ppi.apply_async") as dispatch:
        result = requeue_transient_extraction_failures()
    run.refresh_from_db()
    assert run.status == ExtractionRun.Status.FAILED
    assert result == {"requeued": 0}
    dispatch.assert_not_called()


def test_respects_max_attempts_cap(db, chunk):
    run = _run(chunk, error="The read operation timed out", attempts=5)
    with patch("extract.tasks.run_ppi.apply_async") as dispatch:
        result = requeue_transient_extraction_failures(max_attempts=5)
    run.refresh_from_db()
    assert run.status == ExtractionRun.Status.FAILED  # attempts >= cap → left alone
    assert result == {"requeued": 0}
    dispatch.assert_not_called()


def test_ignores_runs_for_inactive_models(db, chunk):
    # gemma3 is not in the pinned active roster → must not be re-dispatched.
    run = _run(chunk, model="gemma3:12b", error="Server disconnected without sending a response")
    with patch("extract.tasks.run_ppi.apply_async") as dispatch:
        result = requeue_transient_extraction_failures()
    run.refresh_from_db()
    assert run.status == ExtractionRun.Status.FAILED
    assert result == {"requeued": 0}
    dispatch.assert_not_called()


def test_ignores_done_and_queued_runs(db, chunk):
    done = _run(chunk, status="done", error="", attempts=1)
    # a second chunk-model row can't violate the unique constraint, so reuse via model
    with patch("extract.tasks.run_ppi.apply_async") as dispatch:
        result = requeue_transient_extraction_failures()
    done.refresh_from_db()
    assert done.status == ExtractionRun.Status.DONE
    assert result == {"requeued": 0}
    dispatch.assert_not_called()
