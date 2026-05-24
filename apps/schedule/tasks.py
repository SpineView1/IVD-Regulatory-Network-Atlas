"""schedule.tasks — Beat-driven housekeeping tasks.

`janitor_reset_stale_running`: scans every registered "long-running"
model for rows in status='running' with stale heartbeats and resets them
to status='queued'. Registry is empty in Phase 1 (no long-running tasks
yet); Phase 2 (extract.ExtractionRun) registers itself with us.

`refill_rate_limit_buckets`: calls `.refill()` on every bucket. The
buckets self-refill on access, but a periodic refill smooths out
edge cases where a provider is idle for hours.

`assert_beat_alive`: writes a "beat is alive" heartbeat every 60 s by
updating a dedicated ``Watermark`` row (source=``beat:heartbeat``).
The healthcheck task reads this row's ``updated_at`` to detect a dead
Beat scheduler (Phase 6 — fourth mandatory Beat entry).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import timedelta

from django.apps import apps
from django.db.models import F, Q
from django.utils import timezone

from celery import shared_task
from schedule.models import RateLimitBucket

logger = logging.getLogger(__name__)

# The source key used for the beat-liveness Watermark row.
BEAT_HEARTBEAT_SOURCE = "beat:heartbeat"

# Apps register their long-running model + status field here so the janitor
# can sweep them.
# Tuple is (app_label, model_name, status_field, heartbeat_field, attempts_field | None).
_JANITOR_REGISTRY: list[tuple[str, str, str, str, str | None]] = []


def register_janitor_target(
    app_label: str,
    model_name: str,
    status_field: str,
    heartbeat_field: str,
    attempts_field: str | None = None,
) -> None:
    """Register a model for janitor sweeping. Called from each app's apps.py.

    ``attempts_field`` is optional. When provided, the janitor increments it
    (via ``F(attempts_field) + 1``) each time it reclaims a stale row, so
    the spec's Task 13 assertion (``run.attempts == 1`` after sweep) holds.
    Phase 1 targets registered without ``attempts_field`` are unchanged.
    """
    entry: tuple[str, str, str, str, str | None] = (
        app_label,
        model_name,
        status_field,
        heartbeat_field,
        attempts_field,
    )
    if entry not in _JANITOR_REGISTRY:
        _JANITOR_REGISTRY.append(entry)


def _janitor_targets() -> Iterable[tuple[str, str, str, str, str | None]]:
    return list(_JANITOR_REGISTRY)


@shared_task(name="schedule.tasks.janitor_reset_stale_running")
def janitor_reset_stale_running(stale_minutes: int = 10) -> dict:
    """Sweep every registered model; reset stale running rows to queued."""
    cutoff = timezone.now() - timedelta(minutes=stale_minutes)
    summary: dict[str, int] = {}
    total = 0
    for app_label, model_name, status_field, heartbeat_field, attempts_field in _janitor_targets():
        try:
            model = apps.get_model(app_label, model_name)
        except LookupError:
            logger.warning("janitor: unknown model %s.%s", app_label, model_name)
            continue
        qs = model.objects.filter(
            Q(**{status_field: "running"})
            & (Q(**{f"{heartbeat_field}__isnull": True}) | Q(**{f"{heartbeat_field}__lt": cutoff}))
        )
        update_kwargs: dict[str, object] = {status_field: "queued", heartbeat_field: None}
        if attempts_field is not None:
            update_kwargs[attempts_field] = F(attempts_field) + 1
        count = qs.update(**update_kwargs)
        summary[f"{app_label}.{model_name}"] = count
        total += count
    summary["total_reset"] = total
    logger.info("janitor swept: %s", summary)
    return summary


@shared_task(name="schedule.tasks.refill_rate_limit_buckets")
def refill_rate_limit_buckets() -> dict:
    """Walk every bucket and call .refill()."""
    refilled = 0
    for bucket in RateLimitBucket.objects.all():
        bucket.refill()
        refilled += 1
    return {"refilled": refilled}


@shared_task(name="schedule.tasks.assert_beat_alive", queue="q.io")
def assert_beat_alive() -> dict:
    """Write a "beat is alive" heartbeat every 60 s.

    Creates or updates a ``Watermark`` row with
    ``source=BEAT_HEARTBEAT_SOURCE`` and calls ``.save()`` so that
    ``TimestampedModel.updated_at`` (auto_now) is bumped on every
    execution.

    The healthcheck task reads this row's ``updated_at`` to detect a
    dead Beat scheduler — if the row is missing or older than 5 minutes,
    a ``beat_scheduler_stale`` HealthAlert is emitted.
    """
    from schedule.models import Watermark  # noqa: PLC0415 — lazy import

    row, created = Watermark.objects.get_or_create(
        source=BEAT_HEARTBEAT_SOURCE,
        defaults={"notes": "Beat liveness heartbeat — written every 60 s by assert_beat_alive."},
    )
    if not created:
        # .save() bumps updated_at via TimestampedModel's auto_now field.
        row.save()

    logger.debug("assert_beat_alive: heartbeat written (created=%s, pk=%s)", created, row.pk)
    return {"source": BEAT_HEARTBEAT_SOURCE, "created": created, "pk": row.pk}
