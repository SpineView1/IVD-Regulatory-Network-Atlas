"""Tests for corpus.clients.europepmc.EuropePmcClient (REST fullTextXML)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from corpus.clients.europepmc import EuropePmcClient, EuropePmcNotFound
from schedule.models import RateLimitBucket

FIXTURE_DIR = Path(__file__).parent / "fixtures"

# REST endpoint: {base}/{pmcid}/fullTextXML
REST_URL_RE = re.compile(r"https://www\.ebi\.ac\.uk/europepmc/webservices/rest/.*/fullTextXML")


@pytest.fixture(autouse=True)
def _bucket(db):
    RateLimitBucket.objects.create(
        provider="europe_pmc_oai", capacity=10, refill_per_sec=5.0, current_tokens=10.0
    )


@pytest.fixture
def client():
    return EuropePmcClient()


def test_get_jats_returns_xml(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url=REST_URL_RE,
        content=(FIXTURE_DIR / "europepmc_jats.xml").read_bytes(),
    )
    xml = client.get_jats_for_pmcid("PMC11000000")
    assert b"<article" in xml or b"article xmlns" in xml


def test_get_jats_404_not_found(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(method="GET", url=REST_URL_RE, status_code=404)
    with pytest.raises(EuropePmcNotFound):
        client.get_jats_for_pmcid("PMC99999999")


def test_get_jats_empty_body_not_found(client, httpx_mock: HTTPXMock):
    """A 200 with no <article> (non-OA record) maps to EuropePmcNotFound."""
    httpx_mock.add_response(method="GET", url=REST_URL_RE, status_code=200, content=b"")
    with pytest.raises(EuropePmcNotFound):
        client.get_jats_for_pmcid("PMC88888888")


def test_get_jats_hits_rest_fulltextxml_endpoint(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url=REST_URL_RE,
        content=(FIXTURE_DIR / "europepmc_jats.xml").read_bytes(),
    )
    client.get_jats_for_pmcid("PMC11000000")
    req = httpx_mock.get_requests()[0]
    assert str(req.url).endswith("/PMC11000000/fullTextXML")
    assert "ebi.ac.uk/europepmc/webservices/rest" in str(req.url)


def test_get_jats_consumes_rate_limit_token(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url=REST_URL_RE,
        content=(FIXTURE_DIR / "europepmc_jats.xml").read_bytes(),
    )
    before = RateLimitBucket.objects.get(provider="europe_pmc_oai").current_tokens
    client.get_jats_for_pmcid("PMC11000000")
    after = RateLimitBucket.objects.get(provider="europe_pmc_oai").current_tokens
    assert after < before


def test_client_follows_redirects():
    assert EuropePmcClient()._client.follow_redirects is True
