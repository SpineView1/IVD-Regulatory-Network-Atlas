"""monitoring services — the public API of the monitoring app.

Other apps import from here, never from ``monitoring.models``.
"""
from __future__ import annotations

from django.db import transaction

from monitoring.models import FeatureFlag

INGESTION_PAUSED_FLAG = "INGESTION_PAUSED"
DEFAULT_EXTRACT_BACKPRESSURE_THRESHOLD = 10_000


def is_ingestion_paused() -> bool:
    """Return True iff the global ``INGESTION_PAUSED`` flag is set.

    Cheap to call (one indexed Postgres lookup). Beat tasks call this
    on every tick before doing real work.
    """
    try:
        return FeatureFlag.objects.get(name=INGESTION_PAUSED_FLAG).value
    except FeatureFlag.DoesNotExist:
        return False


def set_ingestion_paused(value: bool, *, by: str, reason: str) -> None:
    """Atomically set the ``INGESTION_PAUSED`` flag with audit info."""
    with transaction.atomic():
        flag, _ = FeatureFlag.objects.select_for_update().get_or_create(
            name=INGESTION_PAUSED_FLAG,
            defaults={"value": False},
        )
        flag.value = value
        flag.last_changed_by = by
        flag.last_changed_reason = reason
        flag.save()


def _extract_queue_depth() -> int:
    """Count pending (Chunk × Model) extraction work.

    Implemented as a SQL aggregate over ``extract.ExtractionRun`` rows
    in ``status='queued'`` or ``status='running'``.

    Separated into its own function so tests can mock it.
    """
    # Lazy import to keep monitoring.services free of cross-app DB-import cycles.
    from extract.models import ExtractionRun

    return ExtractionRun.objects.filter(status__in=["queued", "running"]).count()


def extract_queue_depth() -> int:
    """Public wrapper around the queue-depth probe."""
    return _extract_queue_depth()


def is_backpressured(threshold: int = DEFAULT_EXTRACT_BACKPRESSURE_THRESHOLD) -> bool:
    """Return True if the extraction queue is at or above ``threshold``.

    Called by ``corpus.refresh_pubmed`` before pulling new PMIDs from
    NCBI. If True, the refresh short-circuits this tick; PubMed metadata
    is incremental, so deferring one hour is safe.
    """
    return _extract_queue_depth() >= threshold
