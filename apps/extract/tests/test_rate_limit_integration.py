"""Test that all 7 Ollama per-model RateLimitBucket rows are seeded."""

from __future__ import annotations

import pytest

from schedule.models import RateLimitBucket


@pytest.mark.django_db
def test_ollama_qwen3_8b_bucket_seeded():
    """Phase 1 already seeded this one via fixtures/0001_buckets.yaml."""
    bucket = RateLimitBucket.objects.get(provider="ollama_qwen3_8b")
    assert bucket.capacity >= 1
    assert bucket.refill_per_sec >= 0.1


@pytest.mark.django_db
def test_ollama_medgemma_27b_bucket_seeded():
    bucket = RateLimitBucket.objects.get(provider="ollama_medgemma_27b")
    assert bucket.capacity >= 1


@pytest.mark.django_db
def test_ollama_phi4_14b_bucket_seeded():
    bucket = RateLimitBucket.objects.get(provider="ollama_phi4_14b")
    assert bucket.capacity >= 1


@pytest.mark.django_db
def test_ollama_gemma3_12b_bucket_seeded():
    bucket = RateLimitBucket.objects.get(provider="ollama_gemma3_12b")
    assert bucket.capacity >= 1


@pytest.mark.django_db
def test_ollama_deepseek_r1_32b_bucket_seeded():
    bucket = RateLimitBucket.objects.get(provider="ollama_deepseek_r1_32b")
    assert bucket.capacity >= 1


@pytest.mark.django_db
def test_ollama_devstral_24b_bucket_seeded():
    bucket = RateLimitBucket.objects.get(provider="ollama_devstral_24b")
    assert bucket.capacity >= 1


@pytest.mark.django_db
def test_ollama_llama3_1_8b_bucket_seeded():
    bucket = RateLimitBucket.objects.get(provider="ollama_llama3_1_8b")
    assert bucket.capacity >= 1


@pytest.mark.django_db
def test_all_seven_ollama_buckets_start_full():
    """Every per-model bucket should start at capacity."""
    providers = [
        "ollama_qwen3_8b",
        "ollama_medgemma_27b",
        "ollama_phi4_14b",
        "ollama_gemma3_12b",
        "ollama_deepseek_r1_32b",
        "ollama_devstral_24b",
        "ollama_llama3_1_8b",
    ]
    for provider in providers:
        bucket = RateLimitBucket.objects.get(provider=provider)
        assert bucket.current_tokens == pytest.approx(
            bucket.capacity
        ), f"{provider}: current_tokens={bucket.current_tokens} != capacity={bucket.capacity}"
