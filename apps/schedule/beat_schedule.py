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

# Phase 3: graph integration (per spec §6 Beat schedule).
PHASE_3_BEAT_SCHEDULE: dict[str, dict] = {
    "graph-integrate-pending": {
        "task": "graph.integrate_pending",
        "schedule": 60 * 10,  # every 10 min — spec §6
        "options": {"queue": "q.io"},
    },
}

# Phase 4: SBML artifact regeneration (per spec §6 Beat schedule).
PHASE_4_BEAT_SCHEDULE: dict[str, dict] = {
    "sbml-regenerate-stale-networks": {
        "task": "sbml.regenerate_stale_networks",
        "schedule": crontab(minute=0, hour=2),  # daily 02:00 UTC, per spec §6
        "options": {"queue": "q.io"},
    },
}

# Phase 5: reviewer-assignment reminders (per spec §6 Beat schedule).
PHASE_5_BEAT_SCHEDULE: dict[str, dict] = {
    "verify-dispatch-review-assignments": {
        "task": "verify.dispatch_review_assignments",
        "schedule": crontab(minute=0),  # hourly, per spec §6
        "options": {"queue": "q.io"},
    },
}

# Phase 8: Neo4j reconciliation (nightly rebuild sweep — spec §6 Beat schedule).
PHASE_8_BEAT_SCHEDULE: dict[str, dict] = {
    "analysis-reconcile-neo4j": {
        "task": "analysis.tasks.reconcile_neo4j",
        "schedule": crontab(minute=0, hour=4),  # daily 04:00 UTC, per spec §6
        "options": {"queue": "q.io"},
    },
}

# Phase 6: Continuous monitoring — health checks, conflict sweeper, digest notifier.
PHASE_6_BEAT_SCHEDULE: dict[str, dict] = {
    "monitoring-healthcheck": {
        "task": "schedule.healthcheck",
        "schedule": 15 * 60,  # every 15 min, per spec §6
        "options": {"queue": "q.io"},
    },
    "verify-sweep-open-conflicts": {
        "task": "verify.sweep_open_conflicts",
        "schedule": 30 * 60,  # every 30 min, per spec §6
        "options": {"queue": "q.io"},
    },
    "verify-notify-subscribers-daily-digest": {
        "task": "verify.notify_subscribers_daily_digest",
        "schedule": crontab(hour=9, minute=0),  # daily 09:00 UTC, per spec §6
        "options": {"queue": "q.io"},
    },
}

# Canonical merged schedule — wired into CELERY_BEAT_SCHEDULE in settings.base.
BEAT_SCHEDULE: dict[str, dict] = {
    **PHASE_1_BEAT_SCHEDULE,
    **PHASE_2_BEAT_SCHEDULE,
    **PHASE_3_BEAT_SCHEDULE,
    **PHASE_4_BEAT_SCHEDULE,
    **PHASE_5_BEAT_SCHEDULE,
    **PHASE_6_BEAT_SCHEDULE,
    **PHASE_8_BEAT_SCHEDULE,
}
