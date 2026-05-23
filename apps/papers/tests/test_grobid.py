"""Tests for papers.grobid.GrobidClient."""

from __future__ import annotations

from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from papers.grobid import GrobidClient, GrobidFailure
from schedule.models import RateLimitBucket

FIXTURE = Path(__file__).parent / "fixtures" / "sample_grobid_tei.xml"


@pytest.fixture(autouse=True)
def _bucket(db):
    RateLimitBucket.objects.create(
        provider="grobid", capacity=4, refill_per_sec=4.0, current_tokens=4.0
    )


@pytest.fixture
def client(settings):
    settings.GROBID_BASE_URL = "http://grobid.example.com:8070"
    settings.GROBID_TIMEOUT = 60.0
    return GrobidClient()


def test_process_pdf_returns_tei(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="POST",
        url="http://grobid.example.com:8070/api/processFulltextDocument",
        content=FIXTURE.read_bytes(),
    )
    tei = client.process_pdf(pdf_bytes=b"%PDF-1.4 fake")
    assert b"<TEI" in tei
    assert b"HIF1A" in tei


def test_process_pdf_raises_on_5xx(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="POST",
        url="http://grobid.example.com:8070/api/processFulltextDocument",
        status_code=503,
        text="busy",
    )
    with pytest.raises(GrobidFailure):
        client.process_pdf(pdf_bytes=b"%PDF-1.4 fake")


def test_process_pdf_consumes_rate_limit_token(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="POST",
        url="http://grobid.example.com:8070/api/processFulltextDocument",
        content=FIXTURE.read_bytes(),
    )
    before = RateLimitBucket.objects.get(provider="grobid").current_tokens
    client.process_pdf(pdf_bytes=b"%PDF-1.4 fake")
    after = RateLimitBucket.objects.get(provider="grobid").current_tokens
    assert after < before


def test_grobid_alive_check(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url="http://grobid.example.com:8070/api/isalive",
        text="true",
    )
    assert client.is_alive() is True
