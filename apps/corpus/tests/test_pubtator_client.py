"""Tests for corpus.clients.pubtator.PubtatorClient."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from corpus.clients.pubtator import PubtatorClient
from schedule.models import RateLimitBucket

FIXTURE_DIR = Path(__file__).parent / "fixtures"

PUBTATOR_URL_RE = re.compile(r"https://www\.ncbi\.nlm\.nih\.gov/research/pubtator3-api.*")


@pytest.fixture(autouse=True)
def _bucket(db):
    RateLimitBucket.objects.create(
        provider="pubtator3", capacity=10, refill_per_sec=10.0, current_tokens=10.0
    )


@pytest.fixture
def client():
    return PubtatorClient()


def test_get_annotations_returns_entity_list(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url=PUBTATOR_URL_RE,
        text=(FIXTURE_DIR / "pubtator_response.json").read_text(),
    )
    entities = client.get_annotations(pmid=38000123)
    assert len(entities) == 3
    types = {e["type"] for e in entities}
    assert "Gene" in types
    texts = {e["text"] for e in entities}
    assert "HIF1A" in texts
    assert "NFKB1" in texts


def test_get_annotations_uses_correct_url(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url=PUBTATOR_URL_RE,
        text=(FIXTURE_DIR / "pubtator_response.json").read_text(),
    )
    client.get_annotations(pmid=38000123)
    req = httpx_mock.get_requests()[0]
    assert "38000123" in str(req.url)


def test_get_annotations_consumes_token(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url=PUBTATOR_URL_RE,
        text=(FIXTURE_DIR / "pubtator_response.json").read_text(),
    )
    before = RateLimitBucket.objects.get(provider="pubtator3").current_tokens
    client.get_annotations(pmid=38000123)
    after = RateLimitBucket.objects.get(provider="pubtator3").current_tokens
    assert after < before


def test_get_annotations_empty_on_404(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url=PUBTATOR_URL_RE,
        status_code=404,
        text="not found",
    )
    entities = client.get_annotations(pmid=99999999)
    assert entities == []
