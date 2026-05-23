"""Heartbeat decorator for long-running Celery tasks.

Spec §8 mandates: ``@with_heartbeat`` updates a row's ``heartbeat``
timestamp every ``interval_sec`` so the janitor sweep
(``schedule.janitor_reset_stale_running``) can distinguish a still-alive
worker from one whose process died mid-task.

Usage::

    @shared_task
    @with_heartbeat(
        interval_sec=30,
        fetch=lambda run_id: ExtractionRun.objects.get(id=run_id),
    )
    def run_ppi(row_id: int) -> None:
        ...

The decorator spawns a daemon thread for the lifetime of the task; the
thread saves the row's ``heartbeat=timezone.now()`` every ``interval_sec``.
Stops cleanly on task return OR exception.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from functools import wraps
from typing import Any, ParamSpec, TypeVar

from django.utils import timezone

logger = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")


def _supports_update_fields(row: Any) -> bool:
    """MagicMock saves don't accept ``update_fields`` cleanly; real
    Django models do. Branch so tests with mocks still work."""
    return hasattr(row, "_meta")


def with_heartbeat(
    *,
    interval_sec: float,
    fetch: Callable[[int], Any],
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator factory.

    ``fetch`` takes the ``row_id`` (always the first positional or
    keyword argument named ``row_id``) and returns the model instance to
    update.
    """

    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        @wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            row_id_raw: Any = kwargs.get("row_id")
            if row_id_raw is None and args:
                row_id_raw = args[0]
            row = fetch(int(row_id_raw))

            # Fix 6: skip heartbeat writes for rows already in a terminal state
            # (done/failed). This avoids stomping already-done rows during
            # idempotency short-circuits in run_ppi.
            _terminal_statuses = {"done", "failed"}
            row_status = getattr(row, "status", None)
            if row_status in _terminal_statuses:
                # Don't touch heartbeat; just run the function directly.
                return fn(*args, **kwargs)

            row.heartbeat = timezone.now()
            if _supports_update_fields(row):
                row.save(update_fields=["heartbeat"])
            else:
                row.save()

            stop = threading.Event()

            def tick() -> None:
                while not stop.wait(interval_sec):
                    try:
                        row.heartbeat = timezone.now()
                        if _supports_update_fields(row):
                            row.save(update_fields=["heartbeat"])
                        else:
                            row.save()
                    except Exception as exc:
                        logger.warning("heartbeat tick failed: %s", exc)

            thread = threading.Thread(target=tick, name="heartbeat", daemon=True)
            thread.start()
            try:
                return fn(*args, **kwargs)
            finally:
                stop.set()
                thread.join(timeout=interval_sec + 1)

        return wrapper

    return decorator
