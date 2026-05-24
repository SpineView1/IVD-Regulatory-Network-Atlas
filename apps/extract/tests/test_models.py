"""Tests for extract.models — ExtractionRun, RawPPI, PromptTemplate."""

from __future__ import annotations

import pytest
from django.db import IntegrityError

from extract.models import ExtractionRun, PromptTemplate, RawPPI


@pytest.fixture
def prompt(db) -> PromptTemplate:
    # Use a test-specific version that won't conflict with the seeded PROMPT_V1
    # (version=1.0.0 is inserted by migration 0002_seed_prompt).
    return PromptTemplate.objects.create(
        version="99.0.0-test",
        body="dummy {{CHUNK_TEXT}}",
        is_active=False,
    )


@pytest.fixture
def chunk(db):
    """Create a real Chunk via Phase 1 paper/section/chunk models."""
    from corpus.models import Paper
    from papers.models import Chunk, Section

    paper = Paper.objects.create(
        pmid=99999999,
        title="t",
        abstract="a",
    )
    section = Section.objects.create(
        paper=paper,
        doco_type="Results",
        order_index=0,
        body_text="IL1B activates MMP13.",
    )
    return Chunk.objects.create(
        section=section,
        chunk_index=0,
        text="IL1B activates MMP13.",
        token_count=5,
        char_offset_start=0,
        char_offset_end=21,
    )


def test_prompt_template_unique_on_version(db):
    # Use a version not claimed by the seed migrations (V1=1.0.0, V2=2.0.0).
    PromptTemplate.objects.create(version="9.9.9", body="x", is_active=False)
    with pytest.raises(IntegrityError):
        PromptTemplate.objects.create(version="9.9.9", body="y", is_active=False)


def test_only_one_active_prompt_at_a_time(db):
    # The seed migration already inserted version=1.0.0 as is_active=True.
    # Attempting a second active row must raise IntegrityError.
    assert PromptTemplate.objects.filter(is_active=True).count() == 1
    with pytest.raises(IntegrityError):
        PromptTemplate.objects.create(version="3.0.0", body="y", is_active=True)


def test_extractionrun_unique_on_chunk_model_promptversion(db, prompt, chunk):
    ExtractionRun.objects.create(chunk=chunk, model_name="qwen3:8b", prompt_version=prompt.version)
    with pytest.raises(IntegrityError):
        ExtractionRun.objects.create(
            chunk=chunk, model_name="qwen3:8b", prompt_version=prompt.version
        )


def test_extractionrun_default_status_is_queued(db, prompt, chunk):
    run = ExtractionRun.objects.create(
        chunk=chunk, model_name="qwen3:8b", prompt_version=prompt.version
    )
    assert run.status == ExtractionRun.Status.QUEUED


def test_extractionrun_attempts_defaults_zero(db, prompt, chunk):
    run = ExtractionRun.objects.create(
        chunk=chunk, model_name="qwen3:8b", prompt_version=prompt.version
    )
    assert run.attempts == 0


def test_extractionrun_heartbeat_initially_null(db, prompt, chunk):
    run = ExtractionRun.objects.create(
        chunk=chunk, model_name="qwen3:8b", prompt_version=prompt.version
    )
    assert run.heartbeat is None


def test_extractionrun_status_choices_are_full_fsm(db):
    statuses = {choice[0] for choice in ExtractionRun.Status.choices}
    assert statuses == {"queued", "running", "done", "failed"}


def test_rawppi_persists_offsets_and_confidence(db, prompt, chunk):
    run = ExtractionRun.objects.create(
        chunk=chunk, model_name="qwen3:8b", prompt_version=prompt.version
    )
    ppi = RawPPI.objects.create(
        run=run,
        subject="IL1B",
        object="MMP13",
        relation="activates",
        evidence_span="IL1B activates MMP13.",
        evidence_offset_start=0,
        evidence_offset_end=21,
        cell_type=None,
        stimulus=None,
        confidence=0.9,
        relation_logprob=-0.13,
        ungrounded=False,
    )
    ppi.refresh_from_db()
    assert ppi.confidence == 0.9
    assert ppi.evidence_offset_end == 21
    assert ppi.relation_logprob == -0.13


def test_rawppi_default_ungrounded_false(db, prompt, chunk):
    run = ExtractionRun.objects.create(
        chunk=chunk, model_name="qwen3:8b", prompt_version=prompt.version
    )
    ppi = RawPPI.objects.create(
        run=run,
        subject="A",
        object="B",
        relation="activates",
        evidence_span="x",
        evidence_offset_start=0,
        evidence_offset_end=1,
        confidence=0.5,
    )
    assert ppi.ungrounded is False


def test_extractionrun_indexed_on_status_for_janitor_sweep(db):
    indexes = {tuple(i.fields) for i in ExtractionRun._meta.indexes}
    assert ("status", "heartbeat") in indexes
