"""Smoke tests for the Beat schedule."""

from __future__ import annotations

from schedule.beat_schedule import PHASE_1_BEAT_SCHEDULE


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
