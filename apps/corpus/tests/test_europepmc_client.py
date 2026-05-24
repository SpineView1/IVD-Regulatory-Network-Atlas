"""Tests for corpus.clients.europepmc.EuropePmcClient."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from corpus.clients.europepmc import EuropePmcClient, EuropePmcNotFound
from schedule.models import RateLimitBucket

FIXTURE_DIR = Path(__file__).parent / "fixtures"

OAI_URL_RE = re.compile(r"https://europepmc\.org/oai\.cgi.*")


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
        url=OAI_URL_RE,
        content=(FIXTURE_DIR / "europepmc_jats.xml").read_bytes(),
    )
    xml = client.get_jats_for_pmcid("PMC11000000")
    assert b"<article" in xml or b"article xmlns" in xml


def test_get_jats_not_found(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url=OAI_URL_RE,
        content=b"<OAI-PMH><error code='idDoesNotExist'>x</error></OAI-PMH>",
    )
    with pytest.raises(EuropePmcNotFound):
        client.get_jats_for_pmcid("PMC99999999")


def test_get_jats_consumes_rate_limit_token(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url=OAI_URL_RE,
        content=(FIXTURE_DIR / "europepmc_jats.xml").read_bytes(),
    )
    before = RateLimitBucket.objects.get(provider="europe_pmc_oai").current_tokens
    client.get_jats_for_pmcid("PMC11000000")
    after = RateLimitBucket.objects.get(provider="europe_pmc_oai").current_tokens
    assert after < before


def test_get_jats_includes_correct_oai_verb(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url=OAI_URL_RE,
        content=(FIXTURE_DIR / "europepmc_jats.xml").read_bytes(),
    )
    client.get_jats_for_pmcid("PMC11000000")
    req = httpx_mock.get_requests()[0]
    assert "verb=GetRecord" in str(req.url)
    assert "metadataPrefix=pmc" in str(req.url)
    assert "oai%3Aeuropepmc.org%3APMC11000000" in str(
        req.url
    ) or "oai:europepmc.org:PMC11000000" in str(req.url)


def test_client_follows_redirects():
    """Europe PMC moved the OAI endpoint (301 /oai.cgi -> /backend/oai.cgi);
    the client must follow redirects so fetch_fulltext keeps working."""
    assert EuropePmcClient()._client.follow_redirects is True


def test_get_jats_follows_301_redirect(client, httpx_mock: HTTPXMock):
    """A 301 to the relocated endpoint is followed transparently."""
    httpx_mock.add_response(
        method="GET",
        url=OAI_URL_RE,
        status_code=301,
        headers={"Location": "https://europepmc.org/backend/oai.cgi?verb=GetRecord"},
    )
    httpx_mock.add_response(
        method="GET",
        url=re.compile(r"https://europepmc\.org/backend/oai\.cgi.*"),
        content=(FIXTURE_DIR / "europepmc_jats.xml").read_bytes(),
    )
    xml = client.get_jats_for_pmcid("PMC11000000")
    assert b"<article" in xml or b"article xmlns" in xml
