"""Tests for extract.services."""

from __future__ import annotations

import pytest

from extract.models import ExtractionRun, PromptTemplate
from extract.services import (
    active_prompt_version,
    build_prompt_text,
    upsert_runs_for_chunk,
)


@pytest.fixture
def prompt(db):
    # The seed migration already inserted 1.0.0 as active; we need to deactivate it
    # and use our own version for isolation.
    PromptTemplate.objects.all().update(is_active=False)
    return PromptTemplate.objects.create(version="9.9.9", body="say {{CHUNK_TEXT}}", is_active=True)


@pytest.fixture
def chunk(db, prompt):
    from corpus.models import Paper
    from papers.models import Chunk, Section

    paper = Paper.objects.create(pmid=11111111, title="t", abstract="a")
    section = Section.objects.create(
        paper=paper, doco_type="Results", order_index=0, body_text="A activates B."
    )
    return Chunk.objects.create(
        section=section,
        chunk_index=0,
        text="A activates B.",
        token_count=4,
        char_offset_start=0,
        char_offset_end=14,
    )


def test_upsert_creates_seven_runs(db, prompt, chunk):
    n = upsert_runs_for_chunk(chunk.id)
    assert n == 7
    assert ExtractionRun.objects.filter(chunk=chunk).count() == 7


def test_upsert_is_idempotent(db, prompt, chunk):
    upsert_runs_for_chunk(chunk.id)
    upsert_runs_for_chunk(chunk.id)
    assert ExtractionRun.objects.filter(chunk=chunk).count() == 7


def test_upsert_uses_active_prompt_version(db, prompt, chunk):
    upsert_runs_for_chunk(chunk.id)
    versions = set(
        ExtractionRun.objects.filter(chunk=chunk).values_list("prompt_version", flat=True)
    )
    assert versions == {"9.9.9"}


def test_upsert_covers_every_supported_model(db, prompt, chunk):
    from extract.prompts import SUPPORTED_OLLAMA_MODELS

    upsert_runs_for_chunk(chunk.id)
    models = set(ExtractionRun.objects.filter(chunk=chunk).values_list("model_name", flat=True))
    assert models == set(SUPPORTED_OLLAMA_MODELS)


def test_active_prompt_version_returns_string(db, prompt):
    assert active_prompt_version() == "9.9.9"


def test_build_prompt_text_renders_with_chunk(db, prompt):
    text = build_prompt_text("IL1B activates MMP13.")
    assert "IL1B activates MMP13." in text


def test_active_prompt_version_raises_when_no_active(db):
    PromptTemplate.objects.all().update(is_active=False)
    with pytest.raises(RuntimeError):
        active_prompt_version()
