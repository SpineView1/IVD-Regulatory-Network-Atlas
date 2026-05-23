"""Tests for core.tasks."""

from __future__ import annotations

from core.tasks import smoke_ping


def test_smoke_ping_returns_pong_eagerly(settings):
    """Run in eager mode (no broker) — just verifies the task body."""
    settings.CELERY_TASK_ALWAYS_EAGER = True
    result = smoke_ping.delay("hello")
    assert result.get(timeout=1) == "pong: hello"


def test_smoke_ping_handles_empty_input(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    result = smoke_ping.delay("")
    assert result.get(timeout=1) == "pong: "
