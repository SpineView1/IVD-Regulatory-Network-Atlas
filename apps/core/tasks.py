"""Core Celery tasks — shared utility tasks like janitor sweeps."""
from __future__ import annotations

from celery import shared_task


@shared_task
def smoke_ping(message: str) -> str:
    """Sanity-check task: prove Celery routing works end-to-end."""
    return f"pong: {message}"
