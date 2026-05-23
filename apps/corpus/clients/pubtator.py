"""PubTator3 REST client.

Pulls pre-annotated entities (genes, chemicals, diseases, mutations) for
a PMID. We store the flattened entity list on Paper.pubtator_entities;
spec §5 calls this the "cached entity annotations" stage.
"""

from __future__ import annotations

import httpx
from django.conf import settings

from schedule.ratelimit import require_token


class PubtatorClient:
    def __init__(self, *, timeout: float = 30.0) -> None:
        self._client = httpx.Client(timeout=timeout)
        self._base = settings.PUBTATOR3_BASE_URL.rstrip("/")

    @require_token("pubtator3", cost=1)
    def get_annotations(self, *, pmid: int) -> list[dict[str, str]]:
        """Return a flat list of annotation dicts (one per entity mention)."""
        url = f"{self._base}/publications/export/biocjson"
        params = {"pmids": str(pmid)}
        resp = self._client.get(url, params=params)
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        try:
            payload = resp.json()
        except Exception:
            return []
        entities: list[dict[str, str]] = []
        for doc in payload.get("PubTator3", []):
            for passage in doc.get("passages", []):
                for ann in passage.get("annotations", []):
                    infons = ann.get("infons", {})
                    entities.append(
                        {
                            "text": ann.get("text", ""),
                            "type": infons.get("type", ""),
                            "identifier": infons.get("identifier", ""),
                            "database": infons.get("database", ""),
                        }
                    )
        return entities
