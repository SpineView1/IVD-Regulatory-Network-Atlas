"""Observability glue: Sentry initialisation and log-file handler config.

This module is imported once per process at startup. ``sentry_init`` is a
no-op when the appropriate DSN env var is unset (typical in dev).

``configure_log_file`` mutates a Django ``LOGGING`` dict to add a rotating
file handler alongside the existing stdout handler. The file path is
host-mounted by docker-compose (see Task 7) so logs survive container
restart for downstream Loki / ELK ingest.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import sentry_sdk
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.logging import LoggingIntegration


def _resolve_release() -> str:
    explicit = os.environ.get("SENTRY_RELEASE")
    if explicit:
        return explicit
    try:
        sha = subprocess.check_output(  # noqa: S603
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
            stderr=subprocess.DEVNULL,
        )
        return sha.decode().strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def _resolve_environment() -> str:
    return os.environ.get("DJANGO_ENV", "production")


def sentry_init(*, service: str) -> None:
    """Initialise Sentry for either ``web`` or ``worker``.

    Reads the DSN from ``SENTRY_DSN_WEB`` or ``SENTRY_DSN_WORKER``
    depending on ``service``. If the relevant DSN is unset, returns
    without calling ``sentry_sdk.init`` — Phase 7 makes Sentry optional
    in dev.
    """
    dsn_key = "SENTRY_DSN_WORKER" if service == "worker" else "SENTRY_DSN_WEB"
    dsn = os.environ.get(dsn_key)
    if not dsn:
        return

    sentry_sdk.init(
        dsn=dsn,
        release=_resolve_release(),
        environment=_resolve_environment(),
        traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.05")),
        send_default_pii=False,
        integrations=[
            DjangoIntegration(
                transaction_style="url",
                middleware_spans=True,
                signals_spans=False,
            ),
            CeleryIntegration(
                monitor_beat_tasks=True,
                propagate_traces=True,
            ),
            LoggingIntegration(
                level=20,  # INFO becomes breadcrumb
                event_level=40,  # ERROR becomes event
            ),
        ],
    )


def configure_log_file(logging_dict: dict[str, Any], log_path: str) -> dict[str, Any]:
    """Augment ``LOGGING`` with a rotating JSON-line file handler.

    100 MB per file, 10 backups retained ≈ 1 GB total disk footprint per
    container. The handler is appended to the root logger's handler list
    so existing console-bound loggers also write to file.
    """
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)

    handlers = logging_dict.setdefault("handlers", {})
    handlers["file"] = {
        "class": "logging.handlers.RotatingFileHandler",
        "filename": log_path,
        "maxBytes": 100 * 1024 * 1024,
        "backupCount": 10,
        "formatter": "json",
        "encoding": "utf-8",
    }

    # Ensure a "json" formatter exists; reuse Phase 0's structlog formatter if present.
    formatters = logging_dict.setdefault("formatters", {})
    formatters.setdefault(
        "json",
        {
            "()": "structlog.stdlib.ProcessorFormatter",
            "processor": "structlog.processors.JSONRenderer",
        },
    )

    root = logging_dict.setdefault("root", {"handlers": [], "level": "INFO"})
    if "file" not in root["handlers"]:
        root["handlers"].append("file")

    return logging_dict
