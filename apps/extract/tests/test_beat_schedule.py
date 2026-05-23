"""Tests for Phase 2 Beat schedule entry."""

from __future__ import annotations

from django.conf import settings


def test_enqueue_pending_chunks_in_beat_schedule():
    """enqueue_pending_chunks must have a Beat entry."""
    schedule = settings.CELERY_BEAT_SCHEDULE
    task_names = {entry["task"] for entry in schedule.values()}
    assert "extract.tasks.enqueue_pending_chunks" in task_names


def test_enqueue_pending_chunks_schedule_is_five_minutes():
    """The Beat entry for enqueue_pending_chunks must fire every 5 minutes."""
    from celery.schedules import crontab

    schedule = settings.CELERY_BEAT_SCHEDULE
    entry = next(
        v
        for v in schedule.values()
        if v["task"] == "extract.tasks.enqueue_pending_chunks"
    )
    assert isinstance(entry["schedule"], crontab)
    # crontab(minute="*/5") has minute='*/5' in its human_seconds repr
    assert "*/5" in str(entry["schedule"])


def test_beat_schedule_entries_all_have_task_and_schedule():
    """Every entry in the merged schedule must have task + schedule keys."""
    for name, entry in settings.CELERY_BEAT_SCHEDULE.items():
        assert "task" in entry, f"Entry '{name}' missing 'task'"
        assert "schedule" in entry, f"Entry '{name}' missing 'schedule'"
