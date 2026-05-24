"""Europe PMC full-text client.

Returns the raw JATS XML bytes for a PMCID. The caller (papers.jats)
parses the structure; this layer only does HTTP + error mapping.

Uses the Europe PMC REST ``fullTextXML`` endpoint
(``{base}/{pmcid}/fullTextXML``), which returns the JATS ``<article>``
directly. The legacy OAI-PMH endpoint (``/oai.cgi``) was retired — it now
301-redirects to ``/backend/oai.cgi`` and returns HTTP 500 — so we use the
REST API, which is fast (~1 s) and reliable.

(per spec §5: "Europe PMC | Full-text JATS XML for PMC open-access papers")
"""

from __future__ import annotations

import httpx
from django.conf import settings

from schedule.ratelimit import require_token


class EuropePmcNotFound(Exception):
    """Raised when the PMCID isn't in Europe PMC's open-access set."""


class EuropePmcClient:
    def __init__(self, *, timeout: float = 30.0) -> None:
        # follow_redirects=True so any future endpoint relocation keeps working.
        self._client = httpx.Client(timeout=timeout, follow_redirects=True)
        self._base = settings.EUROPE_PMC_BASE_URL.rstrip("/")

    @require_token("europe_pmc_oai", cost=1)
    def get_jats_for_pmcid(self, pmcid: str) -> bytes:
        """GET the JATS XML for a PMC open-access paper via the REST API.

        Raises ``EuropePmcNotFound`` when the paper isn't in the open-access
        set (404) or the response carries no JATS ``<article>``.
        """
        url = f"{self._base}/{pmcid}/fullTextXML"
        resp = self._client.get(url)
        if resp.status_code == 404:
            raise EuropePmcNotFound(pmcid)
        resp.raise_for_status()
        content = resp.content
        if b"<article" not in content:
            # Some non-OA records return an empty/error body with HTTP 200.
            raise EuropePmcNotFound(pmcid)
        return content
