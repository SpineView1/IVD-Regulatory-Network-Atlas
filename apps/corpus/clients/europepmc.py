"""Europe PMC OAI-PMH full-text client.

Returns the raw JATS XML bytes for a PMCID. The caller (papers.jats)
parses the structure; this layer only does HTTP + error mapping.

(per spec §5: "Europe PMC OAI-PMH | Full-text JATS XML for PMC
open-access papers")
"""

from __future__ import annotations

import httpx
from django.conf import settings

from schedule.ratelimit import require_token


class EuropePmcNotFound(Exception):
    """Raised when the PMCID isn't in Europe PMC's open-access set."""


class EuropePmcClient:
    def __init__(self, *, timeout: float = 60.0) -> None:
        self._client = httpx.Client(timeout=timeout)
        self._oai_url = settings.EUROPE_PMC_OAI_URL

    @require_token("europe_pmc_oai", cost=1)
    def get_jats_for_pmcid(self, pmcid: str) -> bytes:
        """GET the JATS XML for a PMC open-access paper."""
        identifier = f"oai:europepmc.org:{pmcid}"
        params = {
            "verb": "GetRecord",
            "identifier": identifier,
            "metadataPrefix": "pmc",
        }
        resp = self._client.get(self._oai_url, params=params)
        resp.raise_for_status()
        content = resp.content
        if b"idDoesNotExist" in content or b"cannotDisseminateFormat" in content:
            raise EuropePmcNotFound(pmcid)
        return content
