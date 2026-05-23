"""GROBID PDF → TEI XML client.

GROBID runs as a local sidecar container. We POST the raw PDF and get
back a TEI XML document with structured sections (parsed downstream by
``papers.tei`` — but for Phase 1 we mostly fall through to chunking via
JATS, since most disc papers are in PMC).

(per spec §5)
"""

from __future__ import annotations

import httpx
from django.conf import settings

from schedule.ratelimit import require_token


class GrobidFailure(RuntimeError):
    """GROBID returned a non-2xx response."""


class GrobidClient:
    def __init__(self) -> None:
        self._base_url = settings.GROBID_BASE_URL.rstrip("/")
        self._timeout = settings.GROBID_TIMEOUT
        self._client = httpx.Client(timeout=self._timeout)

    @require_token("grobid", cost=1)
    def process_pdf(self, *, pdf_bytes: bytes) -> bytes:
        url = f"{self._base_url}/api/processFulltextDocument"
        files = {"input": ("paper.pdf", pdf_bytes, "application/pdf")}
        resp = self._client.post(url, files=files)
        if not resp.is_success:
            raise GrobidFailure(f"GROBID returned {resp.status_code}: {resp.text[:200]}")
        return resp.content

    def is_alive(self) -> bool:
        try:
            resp = self._client.get(f"{self._base_url}/api/isalive", timeout=5.0)
        except httpx.HTTPError:
            return False
        return resp.is_success and resp.text.strip().lower() == "true"
