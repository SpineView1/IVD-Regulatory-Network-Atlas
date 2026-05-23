"""Shared pytest fixtures for the schedule app."""

from __future__ import annotations

import pytest

from schedule.models import RateLimitBucket, Watermark


@pytest.fixture
def ncbi_bucket(db: object) -> RateLimitBucket:
    return RateLimitBucket.objects.create(
        provider="ncbi_eutils",
        capacity=10,
        refill_per_sec=10.0,
        current_tokens=10.0,
    )


@pytest.fixture
def pubmed_watermark(db: object) -> Watermark:
    return Watermark.objects.create(
        source="pubmed",
        last_entrez_date=None,
        last_pmid_seen=None,
        resumption_token="",
    )
