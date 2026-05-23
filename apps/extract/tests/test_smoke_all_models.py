"""Tests for smoke_all_models task.

Contains:
  - A unit test (always runs) that exercises smoke_all_models with a
    fully mocked OllamaClient to verify routing and RawPPI persistence
    without touching any live infrastructure.
  - A @pytest.mark.live test (skipped by default, requires -m live) that
    runs the full pipeline against the SIMBIOsys cluster Ollama gateway.

To run the live test on the cluster:
    pytest apps/extract/tests/test_smoke_all_models.py -m live -v -s

Pre-requisites for live run:
  - OLLAMA_BASE / OLLAMA_USER / OLLAMA_PASSWORD (or AUTHELIA_SVC_*)
    configured in the running environment
  - All seven worker_extract_* containers running
  - A live cluster Ollama endpoint reachable
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from extract.prompts import SUPPORTED_OLLAMA_MODELS

# ---- sample chunk text used by both tests ----

CHUNK_TEXT = (
    "Stimulation of human nucleus pulposus cells with IL-1β robustly "
    "induced MMP-13 and ADAMTS-5 transcription, an effect that was "
    "abolished by pre-treatment with the IKKβ inhibitor BMS-345541, "
    "confirming NF-κB-dependent transactivation of these catabolic genes."
)


# ---- unit test: smoke_all_models with mocked Ollama ----


@pytest.mark.django_db
def test_smoke_all_models_unit_returns_ppi_counts_per_model(db):
    """smoke_all_models calls run_ppi for every model and returns
    {model: count} using a mocked OllamaClient that returns one PPI.
    """
    from corpus.models import Paper
    from extract.models import PromptTemplate
    from extract.tasks import smoke_all_models
    from papers.models import Chunk, Section

    PromptTemplate.objects.filter(is_active=True).delete()
    PromptTemplate.objects.update_or_create(
        version="1.0.0",
        defaults={"body": "{{CHUNK_TEXT}}", "is_active": True},
    )

    paper = Paper.objects.create(
        pmid="99999901",
        title="smoke unit test paper",
        abstract=CHUNK_TEXT,
    )
    section = Section.objects.create(
        paper=paper,
        doco_type="Results",
        order_index=0,
        body_text=CHUNK_TEXT,
    )
    chunk = Chunk.objects.create(
        section=section,
        chunk_index=0,
        text=CHUNK_TEXT,
        token_count=len(CHUNK_TEXT.split()),
        char_offset_start=0,
        char_offset_end=len(CHUNK_TEXT),
    )

    fake_ppi_json = json.dumps(
        {
            "ppis": [
                {
                    "subject": "IL1B",
                    "object": "MMP13",
                    "relation": "activates",
                    "evidence_span": "IL-1β induced MMP-13",
                    "evidence_offset_start": 0,
                    "evidence_offset_end": 20,
                    "cell_type": "nucleus pulposus",
                    "stimulus": "IL-1β",
                    "confidence": 0.9,
                }
            ]
        }
    )

    with patch("extract.tasks._ollama_generate") as mock_gen:
        mock_gen.return_value = (fake_ppi_json, -0.1, 42)
        counts = smoke_all_models(chunk_id=chunk.id)

    assert isinstance(counts, dict)
    assert set(counts.keys()) == set(SUPPORTED_OLLAMA_MODELS)
    for model, count in counts.items():
        assert count >= 1, f"Expected ≥1 RawPPI for model {model}, got {count}"


@pytest.mark.django_db
def test_smoke_all_models_updates_processed_by_models(db):
    """Fix C-2: smoke_all_models must append each model slug to
    Chunk.processed_by_models so enqueue_pending_chunks does not
    re-enqueue chunks that were already processed by smoke_all_models.
    """
    from corpus.models import Paper
    from extract.models import PromptTemplate
    from extract.tasks import smoke_all_models
    from papers.models import Chunk, Section

    PromptTemplate.objects.filter(is_active=True).delete()
    PromptTemplate.objects.update_or_create(
        version="1.0.0",
        defaults={"body": "{{CHUNK_TEXT}}", "is_active": True},
    )

    paper = Paper.objects.create(
        pmid="99999902",
        title="smoke processed_by_models test",
        abstract=CHUNK_TEXT,
    )
    section = Section.objects.create(
        paper=paper,
        doco_type="Results",
        order_index=0,
        body_text=CHUNK_TEXT,
    )
    chunk = Chunk.objects.create(
        section=section,
        chunk_index=0,
        text=CHUNK_TEXT,
        token_count=len(CHUNK_TEXT.split()),
        char_offset_start=0,
        char_offset_end=len(CHUNK_TEXT),
    )

    fake_ppi_json = json.dumps(
        {
            "ppis": [
                {
                    "subject": "IL1B",
                    "object": "MMP13",
                    "relation": "activates",
                    "evidence_span": "IL-1β induced MMP-13",
                    "evidence_offset_start": 0,
                    "evidence_offset_end": 20,
                    "cell_type": "nucleus pulposus",
                    "stimulus": "IL-1β",
                    "confidence": 0.9,
                }
            ]
        }
    )

    with patch("extract.tasks._ollama_generate") as mock_gen:
        mock_gen.return_value = (fake_ppi_json, -0.1, 42)
        smoke_all_models(chunk_id=chunk.id)

    chunk.refresh_from_db()
    missing = [m for m in SUPPORTED_OLLAMA_MODELS if m not in chunk.processed_by_models]
    assert not missing, (
        f"smoke_all_models did not add these models to processed_by_models: {missing}. "
        "Consequence: enqueue_pending_chunks will re-enqueue them on the next Beat tick."
    )


# ---- live integration test (skipped by default) ----


@pytest.mark.live
@pytest.mark.django_db
def test_smoke_all_seven_models_produce_results():
    """Full end-to-end smoke: calls real Ollama gateway.

    Skipped unless -m live is passed. Run on the SIMBIOsys cluster
    where Ollama models are loaded and credentials are configured.
    """
    from corpus.models import Paper
    from extract.models import PromptTemplate, RawPPI
    from extract.tasks import smoke_all_models
    from papers.models import Chunk, Section

    PromptTemplate.objects.filter(is_active=True).delete()
    PromptTemplate.objects.update_or_create(
        version="1.0.0",
        defaults={"body": "{{CHUNK_TEXT}}", "is_active": True},
    )

    paper = Paper.objects.create(
        pmid="00000001",
        title="smoke live",
        abstract=CHUNK_TEXT,
    )
    section = Section.objects.create(
        paper=paper,
        doco_type="Results",
        order_index=0,
        body_text=CHUNK_TEXT,
    )
    chunk = Chunk.objects.create(
        section=section,
        chunk_index=0,
        text=CHUNK_TEXT,
        token_count=len(CHUNK_TEXT.split()),
        char_offset_start=0,
        char_offset_end=len(CHUNK_TEXT),
    )

    counts = smoke_all_models(chunk_id=chunk.id)

    print("\nPer-model RawPPI counts:")
    for model in SUPPORTED_OLLAMA_MODELS:
        print(f"  {model}: {counts.get(model, 0)}")

    models_with_at_least_one = sum(1 for c in counts.values() if c > 0)
    assert models_with_at_least_one >= 5, (
        f"Expected ≥ 5 of 7 models to produce at least one RawPPI; "
        f"got {models_with_at_least_one}. counts={counts}"
    )

    interesting = RawPPI.objects.filter(run__chunk_id=chunk.id)
    assert interesting.exists()
