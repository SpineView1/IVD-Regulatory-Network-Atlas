"""sbml Celery tasks."""
from __future__ import annotations

import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from networks.models import Network
from sbml.services import regenerate_network

log = logging.getLogger(__name__)


@shared_task(
    name="sbml.regenerate",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
    queue="q.io",
)
def regenerate(self, network_id: int, triggered_by_curator: bool = False) -> dict:
    """Regenerate the SBML/CSV/ZIP artifacts for one network.

    Errors are retried with exponential backoff up to 3 times; persistent
    failures leave the prior ModelVersion in place and flip the network
    back to idle so the next stale cycle can retry.
    """
    log.info("sbml.regenerate starting for network_id=%s", network_id)
    try:
        result = regenerate_network(
            network_id=network_id,
            triggered_by_curator=triggered_by_curator,
        )
    except Exception as exc:
        log.exception("sbml.regenerate failed for network_id=%s", network_id)
        with transaction.atomic():
            try:
                n = Network.objects.select_for_update().get(pk=network_id)
                n.pipeline_status = "idle"
                n.save(update_fields=["pipeline_status", "updated_at"])
            except Network.DoesNotExist:
                pass
        raise

    return {
        "network_code": result.network_code,
        "semver": result.semver,
        "created_new_version": result.created_new_version,
        "n_species": result.n_species,
        "n_reactions": result.n_reactions,
        "n_edges": result.n_edges,
    }


@shared_task(name="sbml.regenerate_stale_networks", queue="q.io")
def regenerate_stale_networks() -> dict:
    """Beat task: enqueue ``sbml.regenerate`` for every stale network.

    Schedule: daily at 02:00 UTC (spec §6). Returns a summary dict for
    Flower readability.
    """
    stale = Network.objects.filter(pipeline_status="stale").values_list("pk", flat=True)
    pks = list(stale)
    for pk in pks:
        regenerate.delay(pk)
    log.info("regenerate_stale_networks enqueued %d networks", len(pks))
    return {
        "enqueued": len(pks),
        "network_ids": pks,
        "at": timezone.now().isoformat(),
    }
