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
