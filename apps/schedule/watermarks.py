"""Watermark helpers — transactional read / advance / reset.

Watermarks track the high-water mark per external source so daily
ingestion picks up exactly where it left off. (per spec §5)
"""

from __future__ import annotations

from datetime import date

from django.db import transaction

from schedule.models import Watermark


def get_watermark(source: str) -> Watermark:
    """Get or create a watermark row for ``source``."""
    wm, _ = Watermark.objects.get_or_create(source=source)
    return wm


@transaction.atomic
def advance_watermark(
    source: str,
    *,
    last_pmid_seen: int | None = None,
    last_entrez_date: date | None = None,
    resumption_token: str | None = None,
) -> Watermark:
    """Move the watermark forward. Never regresses."""
    wm = Watermark.objects.select_for_update().get_or_create(source=source)[0]
    if last_pmid_seen is not None and (
        wm.last_pmid_seen is None or last_pmid_seen > wm.last_pmid_seen
    ):
        wm.last_pmid_seen = last_pmid_seen
    if last_entrez_date is not None and (
        wm.last_entrez_date is None or last_entrez_date > wm.last_entrez_date
    ):
        wm.last_entrez_date = last_entrez_date
    if resumption_token is not None:
        wm.resumption_token = resumption_token
    wm.save()
    return wm


@transaction.atomic
def reset_watermark(source: str) -> None:
    """Clear a watermark — used for full re-sweeps."""
    Watermark.objects.filter(source=source).update(
        last_pmid_seen=None,
        last_entrez_date=None,
        resumption_token="",
    )
