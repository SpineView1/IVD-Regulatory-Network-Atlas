"""Test the seed_rate_limit_buckets management command."""

from __future__ import annotations

from django.core.management import call_command

from schedule.models import RateLimitBucket


def test_seed_creates_all_buckets(db):
    call_command("seed_rate_limit_buckets")
    providers = set(RateLimitBucket.objects.values_list("provider", flat=True))
    assert {
        "ncbi_eutils",
        "europe_pmc",
        "europe_pmc_oai",
        "pubtator3",
        "ollama_qwen3_8b",
        "grobid",
    } <= providers


def test_seed_is_idempotent(db):
    call_command("seed_rate_limit_buckets")
    n_first = RateLimitBucket.objects.count()
    call_command("seed_rate_limit_buckets")
    n_second = RateLimitBucket.objects.count()
    assert n_first == n_second
