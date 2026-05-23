"""Tests for Celery task routing configuration (Task 17).

Verifies that extract.tasks.enqueue_pending_chunks and
extract.tasks.smoke_all_models are explicitly routed in
CELERY_TASK_ROUTES so they land on q.io even if dispatched
via .delay() rather than apply_async(queue=...).
"""

from __future__ import annotations

import pytest
from django.conf import settings


def test_enqueue_pending_chunks_routed_to_io():
    routes = settings.CELERY_TASK_ROUTES
    assert "extract.tasks.enqueue_pending_chunks" in routes, (
        "extract.tasks.enqueue_pending_chunks must be explicitly routed"
    )
    assert routes["extract.tasks.enqueue_pending_chunks"]["queue"] == "q.io"


def test_smoke_all_models_routed_to_io():
    routes = settings.CELERY_TASK_ROUTES
    assert "extract.tasks.smoke_all_models" in routes, (
        "extract.tasks.smoke_all_models must be explicitly routed"
    )
    assert routes["extract.tasks.smoke_all_models"]["queue"] == "q.io"


def test_run_ppi_not_statically_routed():
    """run_ppi is routed dynamically by enqueue_pending_chunks via
    apply_async(queue=queue_for_model(...)). A static route would
    silently override the per-model queue, so it must not exist.
    """
    routes = settings.CELERY_TASK_ROUTES
    assert "extract.tasks.run_ppi" not in routes, (
        "extract.tasks.run_ppi must NOT have a static route; "
        "it is routed dynamically per model"
    )
