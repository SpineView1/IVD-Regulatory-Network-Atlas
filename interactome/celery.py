"""Celery application factory.

The Celery app is the single point of task discovery and broker
configuration. Every Django app exposes its tasks via a ``tasks.py``
module that ``autodiscover_tasks`` will find.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure the apps/ directory is on sys.path before importing any local module.
# wsgi.py / asgi.py do this explicitly; celery.py must mirror them because
# Celery workers start without going through wsgi.
_APPS_DIR = str(Path(__file__).resolve().parent.parent / "apps")
if _APPS_DIR not in sys.path:
    sys.path.insert(0, _APPS_DIR)

from celery import Celery, Task  # noqa: E402

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "interactome.settings.dev")

from core.observability import sentry_init  # noqa: E402

sentry_init(service="worker")

app = Celery("interactome")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@app.task(bind=True)
def debug_task(self: Task) -> None:
    print(f"Request: {self.request!r}")
