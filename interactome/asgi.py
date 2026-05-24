"""ASGI config — for future async views."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apps"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "interactome.settings.production")

from core.observability import sentry_init  # noqa: E402

sentry_init(service="web")

from django.core.asgi import get_asgi_application  # noqa: E402

application = get_asgi_application()
