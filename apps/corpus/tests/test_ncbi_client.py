"""Tests for corpus.clients.ncbi.NcbiClient."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from corpus.clients.ncbi import NcbiClient, PaperMetadata
from schedule.models import RateLimitBucket

FIXTURE_DIR = Path(__file__).parent / "fixtures"

ESEARCH_URL_RE = re.compile(r"https://eutils\.ncbi\.nlm\.nih\.gov/entrez/eutils/esearch\.fcgi.*")
EFETCH_URL_RE = re.compile(r"https://eutils\.ncbi\.nlm\.nih\.gov/entrez/eutils/efetch\.fcgi.*")
ELINK_URL_RE = re.compile(r"https://eutils\.ncbi\.nlm\.nih\.gov/entrez/eutils/elink\.fcgi.*")


@pytest.fixture(autouse=True)
def _ncbi_bucket(db):
    RateLimitBucket.objects.create(
        provider="ncbi_eutils", capacity=10, refill_per_sec=10.0, current_tokens=10.0
    )


@pytest.fixture
def client(settings):
    settings.NCBI_API_KEY = "test-key"
    settings.NCBI_CONTACT_EMAIL = "test@example.com"
    return NcbiClient()


def test_esearch_parses_pmids(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url=ESEARCH_URL_RE,
        content=(FIXTURE_DIR / "esearch_response.xml").read_bytes(),
    )
    pmids = client.esearch(query="test", retmax=10)
    assert pmids == [38000123, 38000124, 38000125]


def test_esearch_includes_api_key_and_tool(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url=ESEARCH_URL_RE,
        content=(FIXTURE_DIR / "esearch_response.xml").read_bytes(),
    )
    client.esearch(query="test")
    req = httpx_mock.get_requests()[0]
    assert "api_key=test-key" in str(req.url)
    assert "tool=" in str(req.url)
    assert "email=" in str(req.url)


def test_esearch_consumes_rate_limit_token(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url=ESEARCH_URL_RE,
        content=(FIXTURE_DIR / "esearch_response.xml").read_bytes(),
    )
    before = RateLimitBucket.objects.get(provider="ncbi_eutils").current_tokens
    client.esearch(query="test")
    after = RateLimitBucket.objects.get(provider="ncbi_eutils").current_tokens
    assert after < before


def test_efetch_parses_paper_metadata(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url=EFETCH_URL_RE,
        content=(FIXTURE_DIR / "efetch_response.xml").read_bytes(),
    )
    papers = client.efetch(pmids=[38000123])
    assert len(papers) == 1
    p: PaperMetadata = papers[0]
    assert p.pmid == 38000123
    assert "hypoxia" in p.title.lower()
    assert p.doi == "10.1234/spine.2024.123"
    assert p.pmcid == "PMC11000000"
    assert p.journal == "Spine"
    assert p.publication_date == date(2024, 5, 1)
    assert p.entrez_date == date(2024, 5, 2)
    assert "Intervertebral Disc" in p.mesh_terms
    assert "Journal Article" in p.publication_types
    assert p.authors[0]["last"] == "Doe"


def test_elink_returns_referenced_pmids(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url=ELINK_URL_RE,
        content=(FIXTURE_DIR / "elink_response.xml").read_bytes(),
    )
    refs = client.elink_refs(pmid=38000123)
    assert refs == [30000001, 30000002, 30000003]


def test_esearch_paginates_via_retstart(client, httpx_mock: HTTPXMock):
    # The fixture has count=3, retmax=3; an explicit retstart should appear
    httpx_mock.add_response(
        method="GET",
        url=ESEARCH_URL_RE,
        content=(FIXTURE_DIR / "esearch_response.xml").read_bytes(),
    )
    client.esearch(query="test", retstart=200, retmax=100)
    req = httpx_mock.get_requests()[0]
    assert "retstart=200" in str(req.url)
    assert "retmax=100" in str(req.url)


def _esearch_xml(pmids):
    ids = "".join(f"<Id>{p}</Id>" for p in pmids)
    return f"<eSearchResult><IdList>{ids}</IdList></eSearchResult>".encode()


def test_esearch_all_paginates_until_exhausted(client, httpx_mock: HTTPXMock):
    """esearch_all walks retstart in pages until a short page ends it."""
    httpx_mock.add_response(method="GET", url=ESEARCH_URL_RE, content=_esearch_xml([1, 2, 3]))
    httpx_mock.add_response(method="GET", url=ESEARCH_URL_RE, content=_esearch_xml([4, 5, 6]))
    httpx_mock.add_response(
        method="GET", url=ESEARCH_URL_RE, content=_esearch_xml([7, 8])
    )  # short → stop
    out = client.esearch_all(query="test", page_size=3, max_results=100)
    assert out == [1, 2, 3, 4, 5, 6, 7, 8]


def test_esearch_all_respects_max_results(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(method="GET", url=ESEARCH_URL_RE, content=_esearch_xml([1, 2, 3]))
    httpx_mock.add_response(method="GET", url=ESEARCH_URL_RE, content=_esearch_xml([4, 5, 6]))
    out = client.esearch_all(query="test", page_size=3, max_results=5)
    assert len(out) == 5
    assert out == [1, 2, 3, 4, 5]


def test_esearch_all_dedupes(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(method="GET", url=ESEARCH_URL_RE, content=_esearch_xml([1, 2, 3]))
    httpx_mock.add_response(
        method="GET", url=ESEARCH_URL_RE, content=_esearch_xml([3, 4])
    )  # 3 dup, short → stop
    out = client.esearch_all(query="test", page_size=3, max_results=100)
    assert out == [1, 2, 3, 4]
