"""Celery application factory.

The Celery app is the single point of task discovery and broker
configuration. Every Django app exposes its tasks via a ``tasks.py``
module that ``autodiscover_tasks`` will find.
"""
from __future__ import annotations

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "interactome.settings.dev")

app = Celery("interactome")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@app.task(bind=True)
def debug_task(self) -> None:
    print(f"Request: {self.request!r}")
