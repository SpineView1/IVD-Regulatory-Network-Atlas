"""Smoke tests for the Beat schedule."""

from __future__ import annotations

from schedule.beat_schedule import BEAT_SCHEDULE, PHASE_1_BEAT_SCHEDULE, PHASE_6_BEAT_SCHEDULE


def test_beat_schedule_includes_janitor():
    assert "janitor-reset-stale-running" in PHASE_1_BEAT_SCHEDULE


def test_beat_schedule_includes_pubmed_refresh():
    assert "corpus-refresh-pubmed" in PHASE_1_BEAT_SCHEDULE


def test_beat_schedule_entries_have_task_and_schedule():
    for name, entry in PHASE_1_BEAT_SCHEDULE.items():
        assert "task" in entry, name
        assert "schedule" in entry, name


def test_beat_schedule_task_names_are_unique():
    task_names = [e["task"] for e in PHASE_1_BEAT_SCHEDULE.values()]
    assert len(task_names) == len(set(task_names))


# Phase 6 Beat schedule tests
def test_phase6_healthcheck_in_beat_schedule():
    assert "monitoring-healthcheck" in PHASE_6_BEAT_SCHEDULE
    assert PHASE_6_BEAT_SCHEDULE["monitoring-healthcheck"]["schedule"] == 15 * 60


def test_phase6_sweep_open_conflicts_in_beat_schedule():
    assert "verify-sweep-open-conflicts" in PHASE_6_BEAT_SCHEDULE
    assert PHASE_6_BEAT_SCHEDULE["verify-sweep-open-conflicts"]["schedule"] == 30 * 60


def test_phase6_daily_digest_in_beat_schedule():
    assert "verify-notify-subscribers-daily-digest" in PHASE_6_BEAT_SCHEDULE


def test_phase6_entries_all_routed_to_io_queue():
    for name, entry in PHASE_6_BEAT_SCHEDULE.items():
        options = entry.get("options", {})
        assert options.get("queue") == "q.io", f"entry {name!r} not on q.io"


def test_phase6_entries_present_in_canonical_beat_schedule():
    for name in PHASE_6_BEAT_SCHEDULE:
        assert name in BEAT_SCHEDULE, f"{name!r} missing from BEAT_SCHEDULE"


def test_canonical_beat_schedule_task_names_are_unique():
    task_names = [e["task"] for e in BEAT_SCHEDULE.values()]
    assert len(task_names) == len(set(task_names))


def test_phase6_assert_beat_alive_in_beat_schedule():
    """4th mandatory Phase-6 Beat entry — liveness heartbeat every 60 s."""
    assert "schedule-assert-beat-alive" in PHASE_6_BEAT_SCHEDULE
    entry = PHASE_6_BEAT_SCHEDULE["schedule-assert-beat-alive"]
    assert entry["task"] == "schedule.tasks.assert_beat_alive"
    assert entry["schedule"] == 60
    assert entry.get("options", {}).get("queue") == "q.io"


def test_phase6_has_exactly_four_entries():
    """Phase 6 mandates exactly four Beat entries (spec §6)."""
    assert len(PHASE_6_BEAT_SCHEDULE) == 4


# ---------------------------------------------------------------------------
# Task 13: Beat schedule smoke test — all task names must be registered
# ---------------------------------------------------------------------------


def test_all_beat_schedule_tasks_are_registered():
    """Assert every task name in BEAT_SCHEDULE is registered in the Celery app.

    This catches ``celery.exceptions.NotRegistered`` at test time rather than
    at production runtime — the exact class of bug introduced by the
    ``verify.notify_subscribers_daily_digest`` stub that was in the Beat
    schedule but never implemented.

    Calls ``app.loader.import_default_modules()`` to force autodiscovery of
    all tasks.py modules before checking registration.
    """
    from interactome.celery import app  # noqa: PLC0415 — must import after Django setup

    # Force Celery to import all tasks modules (same as what a worker does on startup).
    app.loader.import_default_modules()

    registered = set(app.tasks.keys())
    missing: list[str] = []

    for entry_name, entry in BEAT_SCHEDULE.items():
        task_name = entry["task"]
        if task_name not in registered:
            missing.append(f"  Beat entry {entry_name!r} → task {task_name!r} NOT REGISTERED")

    assert not missing, (
        "The following Beat entries reference unregistered tasks "
        "(would raise NotRegistered in production):\n" + "\n".join(missing)
    )
