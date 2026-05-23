"""Tests for the @require_token rate-limit decorator."""

from __future__ import annotations

import pytest

from schedule.models import RateLimitBucket
from schedule.ratelimit import RateLimitExceeded, require_token


def test_require_token_allows_call_when_bucket_has_tokens(db):
    RateLimitBucket.objects.create(
        provider="test_provider", capacity=5, refill_per_sec=1.0, current_tokens=5.0
    )

    @require_token("test_provider", cost=1)
    def call() -> str:
        return "ok"

    assert call() == "ok"
    bucket = RateLimitBucket.objects.get(provider="test_provider")
    assert bucket.current_tokens == pytest.approx(4.0, abs=0.1)


def test_require_token_raises_when_bucket_empty(db):
    RateLimitBucket.objects.create(
        provider="test_provider", capacity=5, refill_per_sec=0.0, current_tokens=0.0
    )

    @require_token("test_provider", cost=1)
    def call() -> str:
        return "ok"

    with pytest.raises(RateLimitExceeded) as exc:
        call()
    assert exc.value.provider == "test_provider"
    assert exc.value.retry_after_seconds == float("inf")


def test_require_token_provider_missing_raises(db):
    @require_token("nonexistent_provider", cost=1)
    def call() -> str:
        return "ok"

    with pytest.raises(RateLimitExceeded):
        call()


def test_require_token_multi_cost_call(db):
    RateLimitBucket.objects.create(
        provider="test_provider", capacity=10, refill_per_sec=0.0, current_tokens=3.0
    )

    @require_token("test_provider", cost=5)
    def expensive_call() -> str:
        return "expensive"

    with pytest.raises(RateLimitExceeded):
        expensive_call()
