"""Tests for core.heartbeat.with_heartbeat decorator."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from core.heartbeat import with_heartbeat


@pytest.fixture
def fake_row():
    row = MagicMock()
    row.heartbeat = None
    return row


def test_heartbeat_set_at_task_start(fake_row):
    @with_heartbeat(interval_sec=60, fetch=lambda _id: fake_row)
    def my_task(row_id: int) -> str:
        return "ok"

    result = my_task(row_id=1)
    assert result == "ok"
    assert fake_row.heartbeat is not None


def test_heartbeat_saved_at_task_start(fake_row):
    @with_heartbeat(interval_sec=60, fetch=lambda _id: fake_row)
    def my_task(row_id: int) -> str:
        return "ok"

    my_task(row_id=1)
    fake_row.save.assert_called()


def test_heartbeat_thread_ticks_during_long_task(fake_row):
    @with_heartbeat(interval_sec=0.05, fetch=lambda _id: fake_row)
    def my_task(row_id: int) -> str:
        time.sleep(0.2)  # several heartbeat intervals
        return "ok"

    my_task(row_id=1)
    # Initial set + ≥2 ticks during sleep
    assert fake_row.save.call_count >= 3


def test_heartbeat_thread_stops_after_task_returns(fake_row):
    @with_heartbeat(interval_sec=0.05, fetch=lambda _id: fake_row)
    def my_task(row_id: int) -> str:
        return "ok"

    my_task(row_id=1)
    n_saves_after_return = fake_row.save.call_count
    time.sleep(0.2)
    # No more saves after the task returned.
    assert fake_row.save.call_count == n_saves_after_return


def test_heartbeat_thread_stops_after_exception(fake_row):
    @with_heartbeat(interval_sec=0.05, fetch=lambda _id: fake_row)
    def my_task(row_id: int) -> str:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        my_task(row_id=1)
    n_saves_after_raise = fake_row.save.call_count
    time.sleep(0.2)
    assert fake_row.save.call_count == n_saves_after_raise


def test_heartbeat_skips_write_for_done_status(fake_row):
    """Fix 6: If the row has status='done' or 'failed', the heartbeat decorator
    must not update its heartbeat field.  The caller (run_ppi) relies on this
    so that idempotency short-circuits don't stomp already-done rows."""
    fake_row.status = "done"
    save_count_before = fake_row.save.call_count

    @with_heartbeat(interval_sec=60, fetch=lambda _id: fake_row)
    def my_task(row_id: int) -> str:
        return "already_done"

    result = my_task(row_id=1)
    assert result == "already_done"
    # No new save calls should have occurred for a done row.
    assert fake_row.save.call_count == save_count_before, (
        "Heartbeat wrote to a done/failed row — Fix 6 requires skipping "
        "the heartbeat update when row.status is done or failed."
    )


def test_heartbeat_passes_through_kwargs(fake_row):
    captured: dict = {}

    @with_heartbeat(interval_sec=60, fetch=lambda _id: fake_row)
    def my_task(row_id: int, model_name: str) -> None:
        captured["model_name"] = model_name

    my_task(row_id=1, model_name="qwen3:8b")
    assert captured["model_name"] == "qwen3:8b"
