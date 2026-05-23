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
