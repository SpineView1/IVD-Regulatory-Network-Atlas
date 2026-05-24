"""NCBI E-utilities client: ESearch, EFetch, ELink.

Spec §5 calls out these three endpoints as the primary discovery + metadata
+ citation-traversal mechanism. All calls are gated by the `ncbi_eutils`
rate-limit bucket (10 req/s with API key).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import httpx
from django.conf import settings
from lxml import etree

from schedule.ratelimit import require_token

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
ELINK_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi"


@dataclass
class PaperMetadata:
    pmid: int
    title: str
    abstract: str = ""
    journal: str = ""
    doi: str = ""
    pmcid: str = ""
    publication_date: date | None = None
    entrez_date: date | None = None
    publication_types: list[str] = field(default_factory=list)
    mesh_terms: list[str] = field(default_factory=list)
    authors: list[dict[str, str]] = field(default_factory=list)


class NcbiClient:
    """Wraps the three E-utilities endpoints we care about."""

    def __init__(self, *, timeout: float = 30.0) -> None:
        self._client = httpx.Client(timeout=timeout)
        self._base_params: dict[str, Any] = {
            "tool": settings.NCBI_TOOL_NAME,
            "email": settings.NCBI_CONTACT_EMAIL,
        }
        if settings.NCBI_API_KEY:
            self._base_params["api_key"] = settings.NCBI_API_KEY

    @require_token("ncbi_eutils", cost=1)
    def esearch(
        self,
        *,
        query: str,
        retmax: int = 1000,
        retstart: int = 0,
        db: str = "pubmed",
    ) -> list[int]:
        params: dict[str, Any] = {
            **self._base_params,
            "db": db,
            "term": query,
            "retmax": retmax,
            "retstart": retstart,
            "usehistory": "n",
        }
        resp = self._client.get(ESEARCH_URL, params=params)
        resp.raise_for_status()
        tree = etree.fromstring(resp.content)  # noqa: S320
        return [int(id_el.text) for id_el in tree.findall(".//IdList/Id")]

    @require_token("ncbi_eutils", cost=1)
    def _esearch_history(self, *, query: str, db: str = "pubmed") -> tuple[int, str, str]:
        """Store a result set on NCBI's History server.

        Returns ``(count, webenv, query_key)``. ``usehistory=y`` is required to
        page beyond the first ~10k results (plain ``retstart`` is hard-capped
        by NCBI at ~10k).
        """
        params: dict[str, Any] = {
            **self._base_params,
            "db": db,
            "term": query,
            "usehistory": "y",
            "retmax": 0,
        }
        resp = self._client.get(ESEARCH_URL, params=params)
        resp.raise_for_status()
        tree = etree.fromstring(resp.content)  # noqa: S320
        count = int(tree.findtext(".//Count") or "0")
        webenv = tree.findtext(".//WebEnv") or ""
        query_key = tree.findtext(".//QueryKey") or ""
        return count, webenv, query_key

    @require_token("ncbi_eutils", cost=1)
    def _esearch_history_page(
        self, *, webenv: str, query_key: str, retstart: int, retmax: int, db: str = "pubmed"
    ) -> list[int]:
        params: dict[str, Any] = {
            **self._base_params,
            "db": db,
            "WebEnv": webenv,
            "query_key": query_key,
            "retstart": retstart,
            "retmax": retmax,
        }
        resp = self._client.get(ESEARCH_URL, params=params)
        resp.raise_for_status()
        tree = etree.fromstring(resp.content)  # noqa: S320
        return [int(id_el.text) for id_el in tree.findall(".//IdList/Id")]

    def esearch_all(
        self,
        *,
        query: str,
        db: str = "pubmed",
        page_size: int = 9999,
        max_results: int = 40000,
    ) -> list[int]:
        """Return ALL matching PMIDs up to ``max_results`` via the History server.

        NCBI caps plain ``retstart`` paging at the first ~10k results, so a
        large result set (the master IDD query has ~30k hits) is silently
        truncated by a single ``esearch``. This stores the set with
        ``usehistory=y`` and pages through it from the History server, which
        supports deep ``retstart``. Returns de-duplicated PMIDs in order.
        """
        count, webenv, query_key = self._esearch_history(query=query, db=db)
        if not webenv or not query_key:
            # History unavailable — fall back to a single (capped) page.
            return self.esearch(query=query, retmax=min(page_size, max_results), db=db)

        target = min(count, max_results)
        seen: set[int] = set()
        out: list[int] = []
        retstart = 0
        while retstart < target:
            want = min(page_size, target - retstart)
            page = self._esearch_history_page(
                webenv=webenv, query_key=query_key, retstart=retstart, retmax=want, db=db
            )
            if not page:
                break
            for pmid in page:
                if pmid not in seen:
                    seen.add(pmid)
                    out.append(pmid)
            retstart += len(page)
        return out[:max_results]

    @require_token("ncbi_eutils", cost=1)
    def efetch(self, *, pmids: list[int], db: str = "pubmed") -> list[PaperMetadata]:
        if not pmids:
            return []
        params: dict[str, Any] = {
            **self._base_params,
            "db": db,
            "id": ",".join(str(p) for p in pmids),
            "retmode": "xml",
            "rettype": "abstract",
        }
        resp = self._client.get(EFETCH_URL, params=params)
        resp.raise_for_status()
        tree = etree.fromstring(resp.content)  # noqa: S320
        return [self._parse_article(art) for art in tree.findall(".//PubmedArticle")]

    @require_token("ncbi_eutils", cost=1)
    def elink_refs(self, *, pmid: int) -> list[int]:
        """Reference list (cited papers) via linkname=pubmed_pubmed_refs."""
        params: dict[str, Any] = {
            **self._base_params,
            "dbfrom": "pubmed",
            "db": "pubmed",
            "linkname": "pubmed_pubmed_refs",
            "id": str(pmid),
        }
        resp = self._client.get(ELINK_URL, params=params)
        resp.raise_for_status()
        tree = etree.fromstring(resp.content)  # noqa: S320
        return [int(el.text) for el in tree.findall(".//LinkSetDb/Link/Id")]

    @staticmethod
    def _parse_article(art: etree._Element) -> PaperMetadata:
        pmid = int(art.findtext(".//MedlineCitation/PMID") or "0")
        title = (art.findtext(".//Article/ArticleTitle") or "").strip()
        abstract = " ".join(
            (el.text or "") for el in art.findall(".//Article/Abstract/AbstractText")
        ).strip()
        journal = (art.findtext(".//Article/Journal/Title") or "").strip()
        doi = ""
        pmcid = ""
        for el in art.findall(".//Article/ELocationID"):
            if el.get("EIdType") == "doi":
                doi = (el.text or "").strip()
        for el in art.findall(".//PubmedData/ArticleIdList/ArticleId"):
            if el.get("IdType") == "pmc":
                pmcid = (el.text or "").strip()
        pub_date = _parse_article_date(art)
        entrez_date = _parse_entrez_date(art)
        pub_types = [
            (el.text or "").strip() for el in art.findall(".//PublicationTypeList/PublicationType")
        ]
        mesh = [
            (el.text or "").strip()
            for el in art.findall(".//MeshHeadingList/MeshHeading/DescriptorName")
        ]
        authors = []
        for au in art.findall(".//AuthorList/Author"):
            authors.append(
                {
                    "last": (au.findtext("LastName") or "").strip(),
                    "first": (au.findtext("ForeName") or "").strip(),
                }
            )
        return PaperMetadata(
            pmid=pmid,
            title=title,
            abstract=abstract,
            journal=journal,
            doi=doi,
            pmcid=pmcid,
            publication_date=pub_date,
            entrez_date=entrez_date,
            publication_types=pub_types,
            mesh_terms=mesh,
            authors=authors,
        )


def _parse_article_date(art: etree._Element) -> date | None:
    el = art.find(".//Article/ArticleDate")
    if el is None:
        return None
    try:
        return date(
            int(el.findtext("Year") or 0),
            int(el.findtext("Month") or 0),
            int(el.findtext("Day") or 0),
        )
    except (TypeError, ValueError):
        return None


def _parse_entrez_date(art: etree._Element) -> date | None:
    el = art.find(".//PubmedData/History/PubMedPubDate[@PubStatus='entrez']")
    if el is None:
        return None
    try:
        return date(
            int(el.findtext("Year") or 0),
            int(el.findtext("Month") or 0),
            int(el.findtext("Day") or 0),
        )
    except (TypeError, ValueError):
        return None
