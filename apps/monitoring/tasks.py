"""monitoring Celery tasks.

All tasks here run on the ``q.io`` queue (cheap HTTP + Postgres). The
``healthcheck`` task is Beat-scheduled every 15 min (see
``schedule.beat_schedule``).
"""

from __future__ import annotations

import logging
import time
from datetime import timedelta

import requests
from django.conf import settings
from django.db import connection
from django.utils import timezone

from celery import shared_task
from monitoring.models import HealthAlert

logger = logging.getLogger(__name__)

PUBMED_FRESHNESS_THRESHOLD_HOURS = 2
POSTGRES_LATENCY_WARN_MS = 200.0
OLLAMA_PROBE_TIMEOUT_SECONDS = 5.0
BEAT_HEARTBEAT_STALE_MINUTES = 5


def _probe_ollama() -> bool:
    """Return True if Ollama gateway responds 2xx to /api/tags."""
    url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/tags"
    try:
        r = requests.get(url, timeout=OLLAMA_PROBE_TIMEOUT_SECONDS)
        return r.ok
    except requests.RequestException:
        return False


def _probe_postgres_latency() -> float:
    """Return the wall-clock duration of one ``SELECT 1`` in milliseconds."""
    started = time.monotonic()
    with connection.cursor() as cur:
        cur.execute("SELECT 1")
        cur.fetchone()
    return (time.monotonic() - started) * 1000.0


def _emit_alert(*, check_name: str, severity: str, message: str, context: dict) -> HealthAlert:
    alert = HealthAlert.objects.create(
        check_name=check_name,
        severity=severity,
        message=message,
        context=context,
    )
    if severity in ("error", "critical"):
        notify_admins(severity=severity, check_name=check_name, message=message)
    return alert


def notify_admins(*, severity: str, check_name: str, message: str) -> None:
    """Send an email to all users in the ``health-admins`` group.

    Kept as a module-level function so tests can patch it without
    monkey-patching Celery internals.
    """
    from django.contrib.auth.models import Group
    from django.core.mail import send_mail

    try:
        admins = Group.objects.get(name="health-admins").user_set.exclude(email="")
    except Group.DoesNotExist:
        logger.warning("health-admins group does not exist; skipping alert email")
        return
    recipients = list(admins.values_list("email", flat=True))
    if not recipients:
        return
    send_mail(
        subject=f"[interactome] {severity.upper()}: {check_name}",
        message=message,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "interactome@localhost"),
        recipient_list=recipients,
        fail_silently=True,
    )


@shared_task(queue="q.io", name="schedule.healthcheck")
def healthcheck() -> dict:
    """Run all four health probes; emit one HealthAlert per failure.

    Returns a small dict summarising the run, so Flower / task logs
    are searchable.

    Uses ``Watermark.updated_at`` as a proxy for the last successful
    PubMed advance (``advance_watermark`` calls ``save()``, so
    ``updated_at`` is set by ``TimestampedModel.auto_now``).

    Also reads the beat-liveness Watermark row (source=``beat:heartbeat``)
    written every 60 s by ``schedule.tasks.assert_beat_alive`` to detect
    a dead Beat scheduler.
    """
    # Lazy import: ``schedule`` depends on ``monitoring`` at import time.
    from schedule.models import Watermark
    from schedule.tasks import BEAT_HEARTBEAT_SOURCE  # noqa: PLC0415

    result = {
        "pubmed_refresh_stale": False,
        "ollama_unreachable": False,
        "postgres_slow": False,
        "beat_scheduler_stale": False,
    }

    # (a) PubMed freshness — use watermark.updated_at as last-advance proxy.
    try:
        watermark = Watermark.objects.get(source="pubmed")
        age = timezone.now() - watermark.updated_at
        if age > timedelta(hours=PUBMED_FRESHNESS_THRESHOLD_HOURS):
            _emit_alert(
                check_name="pubmed_refresh_stale",
                severity="error",
                message=(
                    f"No successful corpus.refresh_pubmed in "
                    f"{age.total_seconds() / 3600:.1f}h "
                    f"(threshold {PUBMED_FRESHNESS_THRESHOLD_HOURS}h)"
                ),
                context={"age_hours": age.total_seconds() / 3600},
            )
            result["pubmed_refresh_stale"] = True
    except Watermark.DoesNotExist:
        _emit_alert(
            check_name="pubmed_refresh_stale",
            severity="error",
            message="No pubmed watermark row exists",
            context={},
        )
        result["pubmed_refresh_stale"] = True

    # (b) Ollama reachability
    if not _probe_ollama():
        _emit_alert(
            check_name="ollama_unreachable",
            severity="critical",
            message=(
                f"Ollama gateway {settings.OLLAMA_BASE_URL} did not respond "
                f"within {OLLAMA_PROBE_TIMEOUT_SECONDS}s"
            ),
            context={"ollama_base_url": settings.OLLAMA_BASE_URL},
        )
        result["ollama_unreachable"] = True

    # (c) Postgres latency
    latency_ms = _probe_postgres_latency()
    if latency_ms > POSTGRES_LATENCY_WARN_MS:
        _emit_alert(
            check_name="postgres_slow",
            severity="warning",
            message=(
                f"SELECT 1 took {latency_ms:.0f} ms "
                f"(threshold {POSTGRES_LATENCY_WARN_MS:.0f} ms)"
            ),
            context={"latency_ms": latency_ms},
        )
        result["postgres_slow"] = True

    # (d) Beat scheduler liveness — probe the heartbeat Watermark row.
    try:
        beat_wm = Watermark.objects.get(source=BEAT_HEARTBEAT_SOURCE)
        beat_age = timezone.now() - beat_wm.updated_at
        if beat_age > timedelta(minutes=BEAT_HEARTBEAT_STALE_MINUTES):
            _emit_alert(
                check_name="beat_scheduler_stale",
                severity="critical",
                message=(
                    f"Beat scheduler heartbeat is {beat_age.total_seconds() / 60:.1f} min old "
                    f"(threshold {BEAT_HEARTBEAT_STALE_MINUTES} min). "
                    f"assert_beat_alive may not be running."
                ),
                context={"age_minutes": beat_age.total_seconds() / 60},
            )
            result["beat_scheduler_stale"] = True
    except Watermark.DoesNotExist:
        _emit_alert(
            check_name="beat_scheduler_stale",
            severity="critical",
            message=(
                f"Beat scheduler heartbeat row ({BEAT_HEARTBEAT_SOURCE!r}) does not exist. "
                f"Beat scheduler has never run or assert_beat_alive is not registered."
            ),
            context={},
        )
        result["beat_scheduler_stale"] = True

    return result
