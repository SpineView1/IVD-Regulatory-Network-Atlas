"""Tests for janitor and rate-limit refill tasks."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from schedule.models import RateLimitBucket
from schedule.tasks import janitor_reset_stale_running, refill_rate_limit_buckets


@pytest.fixture(autouse=True)
def _eager(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True


def test_refill_rate_limit_buckets_advances_tokens(db):
    bucket = RateLimitBucket.objects.create(
        provider="ncbi_eutils", capacity=10, refill_per_sec=10.0, current_tokens=5.0
    )
    RateLimitBucket.objects.filter(pk=bucket.pk).update(
        updated_at=timezone.now() - timedelta(seconds=2)
    )
    refill_rate_limit_buckets.delay().get(timeout=1)
    bucket.refresh_from_db()
    assert bucket.current_tokens >= 10.0  # capped at capacity


def test_refill_rate_limit_buckets_no_buckets(db):
    # Should not raise even if no buckets exist
    refill_rate_limit_buckets.delay().get(timeout=1)


def test_janitor_resets_stale_running_extraction_runs(db):
    # Phase 1 doesn't have ExtractionRun yet; the janitor scans models we
    # register with it. Verify the registry plumbing is in place by passing
    # an empty list (the default).
    result = janitor_reset_stale_running.delay().get(timeout=1)
    assert isinstance(result, dict)
    assert "total_reset" in result
    assert result["total_reset"] == 0


def test_janitor_resets_stale_extractionrun_to_queued(db):
    """Phase 2 wiring: stale-running ExtractionRun rows must be re-queued."""
    from datetime import timedelta

    from django.utils import timezone

    from corpus.models import Paper
    from extract.models import ExtractionRun, PromptTemplate
    from papers.models import Chunk, Section

    # Ensure a clean prompt (seed migration already inserts 1.0.0 active).
    PromptTemplate.objects.update_or_create(
        version="1.0.0", defaults={"body": "{{CHUNK_TEXT}}", "is_active": True}
    )
    paper = Paper.objects.create(pmid=55555555, title="t", abstract="a")
    section = Section.objects.create(paper=paper, doco_type="Results", order_index=0, body_text="x")
    chunk = Chunk.objects.create(
        section=section,
        chunk_index=0,
        text="x",
        token_count=1,
        char_offset_start=0,
        char_offset_end=1,
    )
    run = ExtractionRun.objects.create(
        chunk=chunk,
        model_name="qwen3:8b",
        prompt_version="1.0.0",
        status=ExtractionRun.Status.RUNNING,
        heartbeat=timezone.now() - timedelta(minutes=15),
    )

    janitor_reset_stale_running.delay().get(timeout=1)

    run.refresh_from_db()
    assert run.status == ExtractionRun.Status.QUEUED
    assert run.heartbeat is None


def test_janitor_increments_attempts_on_reset(db):
    """Fix 5: When the janitor reclaims a stale ExtractionRun, it must also
    increment the 'attempts' field (spec Task 13: run.attempts == 1 after sweep)."""
    from datetime import timedelta

    from django.utils import timezone

    from corpus.models import Paper
    from extract.models import ExtractionRun, PromptTemplate
    from papers.models import Chunk, Section

    PromptTemplate.objects.update_or_create(
        version="1.0.0", defaults={"body": "{{CHUNK_TEXT}}", "is_active": True}
    )
    paper = Paper.objects.create(pmid=77777777, title="t3", abstract="a3")
    section = Section.objects.create(paper=paper, doco_type="Results", order_index=0, body_text="z")
    chunk = Chunk.objects.create(
        section=section,
        chunk_index=0,
        text="z",
        token_count=1,
        char_offset_start=0,
        char_offset_end=1,
    )
    run = ExtractionRun.objects.create(
        chunk=chunk,
        model_name="qwen3:8b",
        prompt_version="1.0.0",
        status=ExtractionRun.Status.RUNNING,
        heartbeat=timezone.now() - timedelta(minutes=15),
        attempts=0,
    )

    janitor_reset_stale_running.delay().get(timeout=1)

    run.refresh_from_db()
    assert run.status == ExtractionRun.Status.QUEUED
    assert run.heartbeat is None
    assert run.attempts == 1, (
        f"Expected attempts==1 after janitor sweep, got {run.attempts}. "
        "Fix 5: janitor must increment attempts_field when provided."
    )


def test_janitor_summary_includes_extractionrun(db):
    """The janitor result dict must contain extract.ExtractionRun as a key."""
    from datetime import timedelta

    from django.utils import timezone

    from corpus.models import Paper
    from extract.models import ExtractionRun, PromptTemplate
    from papers.models import Chunk, Section

    PromptTemplate.objects.update_or_create(
        version="1.0.0", defaults={"body": "{{CHUNK_TEXT}}", "is_active": True}
    )
    paper = Paper.objects.create(pmid=55555556, title="t2", abstract="a2")
    section = Section.objects.create(paper=paper, doco_type="Results", order_index=0, body_text="y")
    chunk = Chunk.objects.create(
        section=section,
        chunk_index=0,
        text="y",
        token_count=1,
        char_offset_start=0,
        char_offset_end=1,
    )
    ExtractionRun.objects.create(
        chunk=chunk,
        model_name="qwen3:8b",
        prompt_version="1.0.0",
        status=ExtractionRun.Status.RUNNING,
        heartbeat=timezone.now() - timedelta(minutes=15),
    )

    result = janitor_reset_stale_running.delay().get(timeout=1)

    assert "extract.ExtractionRun" in result
    assert result["extract.ExtractionRun"] >= 1
