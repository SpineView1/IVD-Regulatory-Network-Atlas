"""Tests for extract.tasks.enqueue_pending_chunks — Beat fan-out."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from extract.models import ExtractionRun, PromptTemplate
from extract.prompts import SUPPORTED_OLLAMA_MODELS
from extract.tasks import enqueue_pending_chunks


@pytest.fixture
def prompt(db):
    PromptTemplate.objects.all().update(is_active=False)
    return PromptTemplate.objects.create(version="1.0.0-enq", body="p {{CHUNK_TEXT}}", is_active=True)


@pytest.fixture
def two_chunks(db, prompt):
    from corpus.models import Paper
    from papers.models import Chunk, Section

    paper = Paper.objects.create(pmid=33333333, title="t", abstract="a")
    section = Section.objects.create(
        paper=paper, doco_type="Results", order_index=0, body_text="x"
    )
    return [
        Chunk.objects.create(
            section=section,
            chunk_index=i,
            text=f"chunk-{i}",
            token_count=4,
            char_offset_start=i * 10,
            char_offset_end=i * 10 + 7,
        )
        for i in range(2)
    ]


def test_enqueue_creates_runs_for_every_chunk_model_pair(db, two_chunks):
    with patch("extract.tasks.run_ppi.apply_async") as m:
        result = enqueue_pending_chunks()
    # 2 chunks × 7 models
    assert ExtractionRun.objects.count() == 14
    assert m.call_count == 14
    assert sum(result.values()) == 14


def test_enqueue_routes_each_model_to_its_queue(db, two_chunks):
    queues_used: list[str] = []
    with patch("extract.tasks.run_ppi.apply_async") as m:
        enqueue_pending_chunks()
    for call in m.call_args_list:
        queues_used.append(call.kwargs["queue"])

    # 2 messages per model
    from collections import Counter

    counts = Counter(queues_used)
    for model in SUPPORTED_OLLAMA_MODELS:
        slug = (
            model.lower().replace(":", "_").replace(".", "_").replace("-", "_")
        )
        assert counts[f"q.extract.{slug}"] == 2


def test_enqueue_is_idempotent(db, two_chunks):
    with patch("extract.tasks.run_ppi.apply_async"):
        enqueue_pending_chunks()
    n_before = ExtractionRun.objects.count()
    with patch("extract.tasks.run_ppi.apply_async") as m:
        enqueue_pending_chunks()
    # No new ExtractionRun rows; messages still re-dispatched for queued rows.
    assert ExtractionRun.objects.count() == n_before


def test_enqueue_skips_chunks_already_processed_by_all_models(db, two_chunks):
    """When every (chunk, model) pair has status=done, dispatch nothing."""
    from extract.services import upsert_runs_for_chunk

    for chunk in two_chunks:
        upsert_runs_for_chunk(chunk.id)
    ExtractionRun.objects.update(status=ExtractionRun.Status.DONE)

    with patch("extract.tasks.run_ppi.apply_async") as m:
        enqueue_pending_chunks()
    assert m.call_count == 0


def test_enqueue_only_targets_results_sections(db, prompt):
    from corpus.models import Paper
    from papers.models import Chunk, Section

    paper = Paper.objects.create(pmid=44444444, title="t", abstract="a")
    intro = Section.objects.create(
        paper=paper, doco_type="Introduction", order_index=0, body_text="ignored"
    )
    results = Section.objects.create(
        paper=paper, doco_type="Results", order_index=1, body_text="extracted"
    )
    Chunk.objects.create(
        section=intro,
        chunk_index=0,
        text="ignored",
        token_count=4,
        char_offset_start=0,
        char_offset_end=7,
    )
    Chunk.objects.create(
        section=results,
        chunk_index=0,
        text="extracted",
        token_count=4,
        char_offset_start=0,
        char_offset_end=9,
    )

    with patch("extract.tasks.run_ppi.apply_async") as m:
        enqueue_pending_chunks()
    assert m.call_count == 7  # one Results chunk × 7 models
