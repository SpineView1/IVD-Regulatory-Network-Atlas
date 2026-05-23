"""Celery Beat schedules — Phase 1 and Phase 2.

Each entry maps a Celery task name to its run cadence. Beat hot-reloads
this via django_celery_beat's DatabaseScheduler in production; for dev
the schedule is read directly from this Python dict.

(per spec §6 Beat schedule table)

The canonical merged schedule is ``BEAT_SCHEDULE`` — a merge of all
phase dicts. Later phases (3+) extend by importing and merging here.
``settings.base`` sets ``CELERY_BEAT_SCHEDULE = BEAT_SCHEDULE``.
"""

from __future__ import annotations

from celery.schedules import crontab

PHASE_1_BEAT_SCHEDULE: dict[str, dict] = {
    "janitor-reset-stale-running": {
        "task": "schedule.tasks.janitor_reset_stale_running",
        "schedule": crontab(minute="*/5"),
    },
    "refill-rate-limit-buckets": {
        "task": "schedule.tasks.refill_rate_limit_buckets",
        "schedule": crontab(minute="*"),
    },
    "corpus-refresh-pubmed": {
        "task": "corpus.tasks.refresh_pubmed",
        "schedule": crontab(minute=0),  # every hour
    },
    "corpus-refresh-pubmed-full": {
        "task": "corpus.tasks.refresh_pubmed_full",
        "schedule": crontab(minute=0, hour=3, day_of_week=0),  # Sun 03:00 UTC
    },
    "papers-classify-pending": {
        "task": "papers.tasks.classify_pending",
        "schedule": crontab(minute="*/15"),
    },
    "papers-fetch-fulltext-pending": {
        "task": "papers.tasks.fetch_fulltext_pending",
        "schedule": crontab(minute="*/10"),
    },
    "papers-section-pending": {
        "task": "papers.tasks.section_pending",
        "schedule": crontab(minute="*/10"),
    },
    "corpus-triage-pending": {
        "task": "corpus.tasks.triage_pending",
        "schedule": crontab(minute="*/20"),
    },
}

# Phase 2: extraction fan-out (per spec §6 Beat schedule).
PHASE_2_BEAT_SCHEDULE: dict[str, dict] = {
    "extract-enqueue-pending-chunks": {
        "task": "extract.tasks.enqueue_pending_chunks",
        "schedule": crontab(minute="*/5"),
        "options": {"queue": "q.io"},
    },
}

# Canonical merged schedule — wired into CELERY_BEAT_SCHEDULE in settings.base.
BEAT_SCHEDULE: dict[str, dict] = {
    **PHASE_1_BEAT_SCHEDULE,
    **PHASE_2_BEAT_SCHEDULE,
}
