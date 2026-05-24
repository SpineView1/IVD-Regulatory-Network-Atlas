"""graph Celery tasks.

graph.integrate_pending: debounced batch integration of unprocessed RawPPI rows.
Spec §4/§6: "Integration is debounced. graph.normalize_and_integrate batches
RawPPIs per (paper × model) so the Bayes update on belief scores doesn't
thrash. Batch size 10–50."

Pending detection: a RawPPI is pending if:
  - ungrounded=False  (not already flagged as ungroundable)
  - no EdgeEvidence row references it  (not already integrated)
  - parent ExtractionRun.status == 'done'  (extraction is complete)
"""

from __future__ import annotations

import logging

from django.db import transaction

from celery import shared_task

logger = logging.getLogger(__name__)

INTEGRATE_BATCH_SIZE = 50
RELEVANCE_THRESHOLD = 0.5  # mirrors Phase 1 cheap-pass relevance threshold


@shared_task(name="graph.integrate_pending")
def integrate_pending() -> dict:
    """Batch-process unintegrated RawPPIs into Edges.

    Spec §4: "Integration is debounced. graph.normalize_and_integrate
    batches RawPPIs per (paper × model) so the Bayes update on belief
    scores doesn't thrash. Batch size 10–50."

    Routes to queue q.io per spec §6 (set in CELERY_BEAT_SCHEDULE).
    """
    from extract.models import RawPPI  # noqa: PLC0415
    from graph.services import normalize_and_integrate  # noqa: PLC0415

    # Pending = not ungrounded AND no EdgeEvidence row pointing at it AND
    # parent ExtractionRun is done.
    pending_ids = list(
        RawPPI.objects.filter(
            ungrounded=False,
            run__status="done",  # canonical FK: run (not extraction_run)
            edge_evidence__isnull=True,
        )
        .order_by("pk")
        .values_list("pk", flat=True)[:INTEGRATE_BATCH_SIZE]
    )

    if not pending_ids:
        logger.info("integrate_pending: no work")
        return {"processed": 0}

    result = normalize_and_integrate(pending_ids)
    logger.info("integrate_pending: %s", result)
    return result


@shared_task(name="graph.detect_affected_networks", queue="q.io")
def detect_affected_networks(paper_id: int) -> dict:
    """For a newly-ingested paper, mark its candidate networks pending.

    Reads ``PaperRelevance`` rows produced by Phase 1's cheap-pass triage.
    For each network with score >= RELEVANCE_THRESHOLD, idempotently
    inserts a ``NetworkEdgeMembership`` row with
    ``pending_paper_id=paper_id`` and ``pending_extraction=True``.

    Once ``graph.integrate_pending`` processes the resulting RawPPIs and
    promotes them to Edges, it clears the pending flag and sets the
    network's ``pipeline_status='stale'`` (handled in Phase 3, untouched).

    Reference: spec Section 4 (per-paper pipeline) +
    Section 10 (Phase 6 — delta detection).
    """
    from corpus.models import Paper  # noqa: PLC0415 — lazy import
    from graph.models import NetworkEdgeMembership  # noqa: PLC0415
    from graph.services import affected_network_ids  # noqa: PLC0415

    paper = Paper.objects.get(pk=paper_id)
    network_ids = affected_network_ids(paper.pk, threshold=RELEVANCE_THRESHOLD)

    with transaction.atomic():
        for nid in network_ids:
            NetworkEdgeMembership.objects.get_or_create(
                network_id=nid,
                pending_paper_id=paper.pk,
                defaults={"pending_extraction": True, "edge_id": None},
            )

    logger.info(
        "detect_affected_networks: paper_id=%d affected_networks=%s",
        paper_id,
        network_ids,
    )
    return {"paper_id": paper_id, "affected_network_ids": network_ids}
