"""Tests for schedule.models."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.db import IntegrityError
from django.utils import timezone

from schedule.models import RateLimitBucket, ScheduledJob, Watermark


def test_ratelimit_bucket_round_trip(db):
    bucket = RateLimitBucket.objects.create(
        provider="ncbi_eutils", capacity=10, refill_per_sec=10.0, current_tokens=5.0
    )
    assert bucket.pk is not None
    assert bucket.updated_at is not None


def test_ratelimit_bucket_provider_is_unique(db):
    RateLimitBucket.objects.create(
        provider="ncbi_eutils", capacity=10, refill_per_sec=10.0, current_tokens=10.0
    )
    with pytest.raises(IntegrityError):
        RateLimitBucket.objects.create(
            provider="ncbi_eutils", capacity=20, refill_per_sec=20.0, current_tokens=20.0
        )


def test_ratelimit_bucket_consume_decrements(db, ncbi_bucket):
    assert ncbi_bucket.consume(1) is True
    ncbi_bucket.refresh_from_db()
    assert ncbi_bucket.current_tokens == 9.0


def test_ratelimit_bucket_consume_refuses_when_empty(db):
    # Use refill_per_sec=0.0 so no time-based refill occurs during the call
    bucket = RateLimitBucket.objects.create(
        provider="ncbi_eutils", capacity=10, refill_per_sec=0.0, current_tokens=0.0
    )
    assert bucket.consume(1) is False
    bucket.refresh_from_db()
    assert bucket.current_tokens == 0.0


def test_ratelimit_bucket_refill_caps_at_capacity(db):
    bucket = RateLimitBucket.objects.create(
        provider="ncbi_eutils", capacity=10, refill_per_sec=10.0, current_tokens=5.0
    )
    # Use queryset.update() to bypass auto_now=True on updated_at
    RateLimitBucket.objects.filter(pk=bucket.pk).update(
        updated_at=timezone.now() - timedelta(seconds=60)
    )
    bucket.refill()
    bucket.refresh_from_db()
    assert bucket.current_tokens == 10.0


def test_ratelimit_bucket_seconds_until_refill_when_empty(db):
    bucket = RateLimitBucket.objects.create(
        provider="ncbi_eutils", capacity=10, refill_per_sec=10.0, current_tokens=0.0
    )
    # Need 1 token at 10/s = 0.1s
    assert 0.05 < bucket.seconds_until_refill(cost=1) < 0.2


def test_watermark_round_trip(db, pubmed_watermark):
    assert pubmed_watermark.pk is not None
    pubmed_watermark.last_pmid_seen = 39000000
    pubmed_watermark.save()
    pubmed_watermark.refresh_from_db()
    assert pubmed_watermark.last_pmid_seen == 39000000


def test_watermark_source_is_unique(db):
    Watermark.objects.create(source="pubmed")
    with pytest.raises(IntegrityError):
        Watermark.objects.create(source="pubmed")


def test_scheduled_job_round_trip(db):
    job = ScheduledJob.objects.create(
        name="corpus.refresh_pubmed",
        cadence_seconds=3600,
        last_run_at=None,
        last_status="never_run",
    )
    assert job.pk is not None
