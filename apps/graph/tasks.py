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

from celery import shared_task

logger = logging.getLogger(__name__)

INTEGRATE_BATCH_SIZE = 50


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
