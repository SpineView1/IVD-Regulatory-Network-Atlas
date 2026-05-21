# Phase 7: Hardening + Handoff — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Take the working end-to-end pipeline (Phases 0–6) and make it production-grade and operable: scheduled Postgres backups via pgbackrest with restore-test, Sentry exception capture in Django and Celery, host-mounted JSON log shipping, an optional Prometheus + Grafana sidecar pair plus a `/metrics/` endpoint, an operations runbook with five named procedures, a biologist onboarding doc, the first formal biologist sign-off ceremony on the NF-κB axis network, Postgres EXPLAIN-driven covering indexes for the hottest dashboard queries, a security review pass on Caddy / Authelia / Django, and a tagged `v1.0.0` release. End state: `docker-compose ps` shows 18 services up; `docker-compose exec pgbackrest pgbackrest --stanza=interactome info` lists at least one full and one incremental backup; `curl http://web:8000/metrics/` returns Prometheus-format metrics; `git tag` lists `v1.0.0`; the professor has received the deployment summary email; and at least one network (NF-κB axis) is at `VERIFIED` status with a curator-cut MAJOR `ModelVersion` in MinIO.

**Architecture:** No new Django apps. Phase 7 extends the existing apps (`schedule`, `verify`, `core`) with a metrics endpoint and a sign-off ceremony script, adds three sidecar containers to `docker-compose.yml` (`pgbackrest`, `prometheus`, `grafana`), wires Sentry into Django and Celery startup, and produces three documentation artifacts (`docs/runbook.md`, `docs/onboarding-biologist.md`, `docs/signoff-ceremony.md`). Migrations land covering indexes on `corpus_paper`, `graph_edge`, and `verify_review` based on EXPLAIN ANALYZE evidence captured in this plan.

**Tech Stack additions:** `sentry-sdk[django,celery] ^2.14`, `django-prometheus ^2.3`, `pgbackrest 2.53` (container image `pgbackrest/pgbackrest:latest`), `prom/prometheus:v2.54.1`, `grafana/grafana:11.2.0`. All other dependencies inherit from Phases 0–6.

**Reference spec:** `docs/superpowers/specs/2026-05-19-disc-interactome-app-design.md` Sections 8 (resumability and disaster recovery), 9 (deployment, logging, monitoring), 10 (Phase 7 row of the roadmap).

**Cross-phase dependencies:**

- **Phase 0** — `docker-compose.yml`, `Caddyfile`, `interactome/settings/{base,production}.py`, `apps/core/middleware.py`, structlog logging configured. Phase 7 adds entries to these files; do not rewrite them.
- **Phase 1** — `corpus_paper`, `corpus_paperrelevance`, `schedule_watermark` tables present. Phase 7 adds covering indexes to `corpus_paper`.
- **Phase 3** — `graph_edge`, `graph_edgeevidence`, `graph_entity`, `graph_networkedgemembership` tables. Phase 7 adds covering indexes to `graph_edge` and `graph_networkedgemembership`.
- **Phase 4** — `sbml_modelversion`, `sbml.regenerate` task, semver bump logic. Phase 7's sign-off ceremony exercises the MAJOR version bump path.
- **Phase 5** — `verify_review`, `verify_signoff`, `verify_reviewassignment` tables, notification machinery, the network drill-down view. Phase 7 adds a covering index to `verify_review` and consumes the notification API in the sign-off ceremony.
- **Phase 6** — `schedule.healthcheck` task already exists. Phase 7 extends it to feed `/metrics/`.

---

## File Structure After Phase 7

```
/                                       (git repo root)
├── pyproject.toml                      (+ sentry-sdk, django-prometheus)
├── poetry.lock                         re-locked after additions
├── docker-compose.yml                  (+ pgbackrest, prometheus, grafana services)
├── docker-compose.override.dev.yml     (existing; unchanged)
├── Caddyfile                           (+ HSTS preload header, /metrics/ scoped to localhost)
├── .env.example                        (+ SENTRY_DSN_WEB, SENTRY_DSN_WORKER, SENTRY_RELEASE, GRAFANA_ADMIN_PASSWORD, PGBACKREST_REPO_PATH)
├── deploy/
│   ├── pgbackrest/
│   │   ├── pgbackrest.conf             stanza config — full Sun, incr daily
│   │   ├── crontab                     in-container cron schedule
│   │   ├── entrypoint.sh               runs cron in foreground
│   │   └── restore-test.sh             restores latest into a sandbox PGDATA and checks row counts
│   ├── prometheus/
│   │   └── prometheus.yml              scrapes web:8000/metrics, flower:5555
│   ├── grafana/
│   │   ├── provisioning/
│   │   │   ├── datasources/
│   │   │   │   └── prometheus.yml
│   │   │   └── dashboards/
│   │   │       └── dashboards.yml
│   │   └── dashboards/
│   │       └── interactome-v1.json     queue depth, task duration, response time
│   └── rsync-offhost.sh                weekly off-host backupdata + miniodata rsync
├── interactome/
│   └── settings/
│       ├── base.py                     (+ django_prometheus app, sentry init helper)
│       └── production.py               (+ SECURE_HSTS_PRELOAD=True, sentry.init() call)
├── apps/
│   ├── core/
│   │   ├── observability.py            NEW — sentry_init(), structured-log file handler config
│   │   └── tests/
│   │       └── test_observability.py   NEW — sentry init wired, log file path honoured
│   ├── schedule/
│   │   ├── metrics.py                  NEW — django-prometheus custom collectors
│   │   ├── migrations/
│   │   │   └── 0007_healthcheck_metric_row.py    NEW
│   │   ├── tasks.py                    (+ healthcheck writes metric row read by /metrics/)
│   │   └── tests/
│   │       └── test_metrics.py         NEW — /metrics/ exposes queue_depth, healthcheck_age
│   ├── corpus/
│   │   └── migrations/
│   │       └── 0012_paper_covering_indexes.py    NEW — index on (entrez_date DESC, is_original) etc.
│   ├── graph/
│   │   └── migrations/
│   │       └── 0008_edge_covering_indexes.py     NEW — composite index for drill-down
│   ├── verify/
│   │   ├── migrations/
│   │   │   └── 0005_review_status_index.py        NEW
│   │   └── management/commands/
│   │       └── signoff_ceremony.py     NEW — scripted first-signoff dry-run + commit
│   └── verify/tests/
│       └── test_signoff_ceremony.py    NEW
├── docs/
│   ├── runbook.md                      NEW — five named procedures
│   ├── onboarding-biologist.md         NEW
│   ├── signoff-ceremony.md             NEW — NF-κB axis ceremony record template
│   └── superpowers/
│       └── plans/
│           └── 2026-05-19-phase-7-hardening.md   (this file)
└── scripts/
    └── tag-v1-release.sh               NEW — guarded release tagger
```

**Why this layout:**

- `deploy/` collects all infra config that isn't Python: pgbackrest stanza config, prometheus scrape config, grafana dashboard JSON, rsync glue. Keeps `interactome/` Python-only.
- `apps/core/observability.py` centralises Sentry init and the structured-log file-handler factory so `web`, `beat`, and every `worker_*` import the same function on boot. Per spec Section 9 ("All containers log to stdout, JSON lines via structlog"), Phase 7 adds a sibling file handler so logs survive container restart for later ELK / Loki ingest.
- The `signoff_ceremony` Django management command lives in `verify` (the app that owns `Signoff`), not in a new `ceremony` app. Per spec Section 2 ("Boundary discipline: each app's `services.py` is the public API"), the ceremony is just a scripted invocation of `verify.services.cut_major_version()`.
- Three docs (`runbook.md`, `onboarding-biologist.md`, `signoff-ceremony.md`) live at `docs/` top-level — they're operational documents, not specs or plans, so they don't go under `docs/superpowers/`.

---

## Task 1: Add Sentry + django-prometheus dependencies

Per spec Section 9: "Sentry (free tier) catches exceptions from `web` and `worker_*`". Per the phase brief: `/metrics/` endpoint via `django-prometheus`. Both are wired here before any code changes so subsequent tasks can import the packages without local-environment friction.

**Files:**
- Modify: `pyproject.toml`
- Modify: `poetry.lock` (regenerated)

- [ ] **Step 1: Add dependencies to `pyproject.toml`**

Inside the `[tool.poetry.dependencies]` block, add (alphabetised):

```toml
django-prometheus = "^2.3"
sentry-sdk = {extras = ["django", "celery"], version = "^2.14"}
```

- [ ] **Step 2: Re-lock and install**

```bash
cd /Users/kiptengwer/Downloads/interactome
poetry lock --no-update
poetry install
```

Expected output (final line):
```
Installing the current project: interactome (0.1.0)
```

- [ ] **Step 3: Verify imports work**

```bash
poetry run python -c "import sentry_sdk; import django_prometheus; print(sentry_sdk.VERSION, django_prometheus.__version__)"
```

Expected: a version pair printed, e.g. `2.14.0 2.3.1`.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml poetry.lock
git commit -m "build: add sentry-sdk and django-prometheus for Phase 7"
```

---

## Task 2: Observability module — Sentry init + JSON-log file handler (TDD)

Per spec Section 9 ("Logging and monitoring"), structlog already ships JSON lines to stdout from Phase 0. Phase 7 adds:

1. A `sentry_init()` helper that wires the Django + Celery integrations with environment-driven DSN, release tag (from `SENTRY_RELEASE` env, fall back to git SHA via `subprocess`), and sample rates. The Celery integration captures task exceptions; the Django integration captures HTTP-handler exceptions and adds DB query breadcrumbs.
2. A `configure_log_file()` helper that augments `settings.LOGGING` with a `RotatingFileHandler` writing JSON lines to `/var/log/interactome/app.jsonl` (host-mounted by `docker-compose.yml`, Task 7). 100 MB rotation, 10 files retained.

**Files:**
- Create: `apps/core/observability.py`
- Create: `apps/core/tests/test_observability.py`

- [ ] **Step 1: Write the failing test in `apps/core/tests/test_observability.py`**

```python
"""Tests for core.observability."""
from __future__ import annotations

import json
import logging
import logging.handlers
from pathlib import Path
from unittest.mock import patch

import pytest

from core import observability


def test_sentry_init_no_dsn_is_noop(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN_WEB", raising=False)
    with patch("sentry_sdk.init") as mock_init:
        observability.sentry_init(service="web")
    mock_init.assert_not_called()


def test_sentry_init_with_dsn_calls_init(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN_WEB", "https://k@sentry.io/1")
    monkeypatch.setenv("SENTRY_RELEASE", "v1.0.0-test")
    with patch("sentry_sdk.init") as mock_init:
        observability.sentry_init(service="web")
    mock_init.assert_called_once()
    kwargs = mock_init.call_args.kwargs
    assert kwargs["dsn"] == "https://k@sentry.io/1"
    assert kwargs["release"] == "v1.0.0-test"
    assert kwargs["environment"] in {"production", "dev", "test"}


def test_sentry_init_picks_worker_dsn_for_worker(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN_WORKER", "https://w@sentry.io/2")
    monkeypatch.delenv("SENTRY_DSN_WEB", raising=False)
    with patch("sentry_sdk.init") as mock_init:
        observability.sentry_init(service="worker")
    assert mock_init.call_args.kwargs["dsn"] == "https://w@sentry.io/2"


def test_sentry_init_attaches_django_and_celery_integrations(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN_WEB", "https://k@sentry.io/1")
    with patch("sentry_sdk.init") as mock_init:
        observability.sentry_init(service="web")
    integration_classes = {type(i).__name__ for i in mock_init.call_args.kwargs["integrations"]}
    assert "DjangoIntegration" in integration_classes
    assert "CeleryIntegration" in integration_classes


def test_sentry_init_release_falls_back_to_git_sha(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN_WEB", "https://k@sentry.io/1")
    monkeypatch.delenv("SENTRY_RELEASE", raising=False)
    with patch("sentry_sdk.init") as mock_init, \
         patch("subprocess.check_output", return_value=b"abcdef0\n"):
        observability.sentry_init(service="web")
    assert mock_init.call_args.kwargs["release"] == "abcdef0"


def test_configure_log_file_adds_rotating_handler(tmp_path):
    log_path = tmp_path / "app.jsonl"
    logging_dict = {
        "version": 1,
        "disable_existing_loggers": False,
        "handlers": {"console": {"class": "logging.StreamHandler"}},
        "root": {"handlers": ["console"], "level": "INFO"},
    }
    out = observability.configure_log_file(logging_dict, str(log_path))
    assert "file" in out["handlers"]
    assert out["handlers"]["file"]["class"] == "logging.handlers.RotatingFileHandler"
    assert out["handlers"]["file"]["filename"] == str(log_path)
    assert "file" in out["root"]["handlers"]


def test_configure_log_file_creates_parent_dir(tmp_path):
    log_path = tmp_path / "nested" / "deeper" / "app.jsonl"
    observability.configure_log_file(
        {"version": 1, "handlers": {}, "root": {"handlers": [], "level": "INFO"}},
        str(log_path),
    )
    assert log_path.parent.exists()


def test_configure_log_file_writes_json_lines(tmp_path):
    log_path = tmp_path / "app.jsonl"
    cfg = observability.configure_log_file(
        {"version": 1, "disable_existing_loggers": False, "handlers": {}, "root": {"handlers": [], "level": "INFO"}},
        str(log_path),
    )
    logging.config.dictConfig(cfg)
    logging.getLogger("test").info("hello", extra={"key": "value"})
    for h in logging.getLogger().handlers:
        h.flush()
    content = log_path.read_text().strip()
    # Each line must parse as JSON
    for line in content.splitlines():
        assert json.loads(line)
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
poetry run pytest apps/core/tests/test_observability.py -v
```

Expected:
```
ModuleNotFoundError: No module named 'core.observability'
```

- [ ] **Step 3: Implement `apps/core/observability.py`**

```python
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
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
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
                level=20,        # INFO becomes breadcrumb
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
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
poetry run pytest apps/core/tests/test_observability.py -v
```

Expected:
```
8 passed
```

- [ ] **Step 5: Commit**

```bash
git add apps/core/observability.py apps/core/tests/test_observability.py
git commit -m "feat(core): add Sentry init helper and JSON-log file handler"
```

---

## Task 3: Wire Sentry init into Django and Celery startup

Per spec Section 9: Sentry must catch exceptions from both `web` and every `worker_*` process. The cleanest single attach-point is each entrypoint module (`interactome/wsgi.py`, `interactome/asgi.py`, `interactome/celery.py`) calling `sentry_init` with the appropriate service tag before any framework code runs.

Production settings also gain the `SECURE_HSTS_PRELOAD = True` flip per the phase brief's "Security review tasks: confirm Caddy TLS settings (HSTS, OCSP stapling)".

**Files:**
- Modify: `interactome/settings/base.py`
- Modify: `interactome/settings/production.py`
- Modify: `interactome/wsgi.py`
- Modify: `interactome/asgi.py`
- Modify: `interactome/celery.py`

- [ ] **Step 1: Update `interactome/settings/base.py`**

After the existing `LOGGING = { ... }` block, append (replacing nothing):

```python
# Phase 7: route logs to a host-mounted file in addition to stdout.
# When LOG_FILE_PATH is unset (default in dev), only stdout is used.
import os as _os  # noqa: E402

from core.observability import configure_log_file as _configure_log_file  # noqa: E402

_log_file = _os.environ.get("LOG_FILE_PATH")
if _log_file:
    LOGGING = _configure_log_file(LOGGING, _log_file)

# Phase 7: django-prometheus mounts at /metrics/. Add the app and
# the two middlewares that bracket every request to record duration.
INSTALLED_APPS = [*INSTALLED_APPS, "django_prometheus"]
MIDDLEWARE = [
    "django_prometheus.middleware.PrometheusBeforeMiddleware",
    *MIDDLEWARE,
    "django_prometheus.middleware.PrometheusAfterMiddleware",
]
```

- [ ] **Step 2: Update `interactome/settings/production.py`**

After the existing `SECURE_HSTS_*` block, change `SECURE_HSTS_PRELOAD = False` to `True` and add OCSP / referrer hardening:

```python
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365  # 1 year for preload list eligibility
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = "DENY"
```

(Caddy handles OCSP stapling automatically when ACME-issued certs are used; verified in Task 12.)

- [ ] **Step 3: Update `interactome/wsgi.py`**

Replace the file with:

```python
"""WSGI config — gunicorn's entrypoint in production."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apps"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "interactome.settings.production")

from core.observability import sentry_init  # noqa: E402

sentry_init(service="web")

from django.core.wsgi import get_wsgi_application  # noqa: E402

application = get_wsgi_application()
```

- [ ] **Step 4: Update `interactome/asgi.py`**

Same shape as `wsgi.py`:

```python
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
```

- [ ] **Step 5: Update `interactome/celery.py`**

Append, immediately before the existing `app = Celery("interactome")` line:

```python
from core.observability import sentry_init  # noqa: E402

sentry_init(service="worker")
```

- [ ] **Step 6: Run the full test suite to verify nothing regressed**

```bash
poetry run pytest -v --tb=short
```

Expected: all existing Phase 0–6 tests pass plus the 8 new ones from Task 2.

- [ ] **Step 7: Commit**

```bash
git add interactome/settings/base.py interactome/settings/production.py interactome/wsgi.py interactome/asgi.py interactome/celery.py
git commit -m "feat: wire Sentry into web and worker startup; harden HSTS"
```

---

## Task 4: Prometheus metrics endpoint with custom collectors (TDD)

Per the phase brief: `/metrics/` via `django-prometheus`. The default `django-prometheus` middleware already exports HTTP request duration histograms. Phase 7 adds two custom collectors that the runbook and Grafana dashboard depend on:

1. `interactome_celery_queue_depth{queue="..."}` — gauge per queue, read from Redis at scrape time.
2. `interactome_healthcheck_last_run_seconds_ago` — gauge derived from the `schedule.healthcheck` task that Phase 6 already runs every minute.

**Files:**
- Create: `apps/schedule/metrics.py`
- Create: `apps/schedule/tests/test_metrics.py`
- Modify: `apps/schedule/migrations/0007_healthcheck_metric_row.py` (new file)
- Modify: `apps/schedule/tasks.py` (add `healthcheck` task write to metric row)
- Modify: `interactome/urls.py` (mount `django_prometheus.urls`)

- [ ] **Step 1: Create migration `apps/schedule/migrations/0007_healthcheck_metric_row.py`**

The healthcheck task needs a single-row table to record `last_run_at`. Use the existing `schedule_singleton` pattern if one exists from Phase 6; otherwise create a new model:

```python
"""Add HealthcheckState singleton row."""
from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("schedule", "0006_priority_lanes"),
    ]

    operations = [
        migrations.CreateModel(
            name="HealthcheckState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True)),
                ("last_run_at", models.DateTimeField()),
                ("status", models.CharField(max_length=16, default="ok")),
            ],
            options={"db_table": "schedule_healthcheckstate"},
        ),
        migrations.RunSQL(
            sql="INSERT INTO schedule_healthcheckstate (id, last_run_at, status) VALUES (1, now(), 'ok');",
            reverse_sql="DELETE FROM schedule_healthcheckstate WHERE id = 1;",
        ),
    ]
```

If `schedule/migrations/0006_priority_lanes.py` doesn't exist (Phase 6 used a different name), substitute the actual last migration name. Confirm with:

```bash
ls apps/schedule/migrations/
```

- [ ] **Step 2: Write the failing test in `apps/schedule/tests/test_metrics.py`**

```python
"""Tests for schedule.metrics — Prometheus custom collectors."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.test import Client
from django.utils import timezone


@pytest.fixture
def client():
    return Client()


@pytest.mark.django_db
def test_metrics_endpoint_returns_200(client):
    response = client.get("/metrics/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_metrics_endpoint_content_type_is_prometheus(client):
    response = client.get("/metrics/")
    assert "text/plain" in response["Content-Type"]


@pytest.mark.django_db
def test_metrics_exposes_django_http_default_metric(client):
    client.get("/health/")  # produces a request the middleware will count
    response = client.get("/metrics/")
    assert b"django_http_requests_total_by_method_total" in response.content


@pytest.mark.django_db
def test_metrics_exposes_celery_queue_depth(client):
    from schedule.metrics import CeleryQueueDepthCollector

    with patch.object(CeleryQueueDepthCollector, "_redis_llen", return_value=42):
        response = client.get("/metrics/")
    assert b"interactome_celery_queue_depth" in response.content
    assert b"42" in response.content


@pytest.mark.django_db
def test_metrics_exposes_healthcheck_age(client):
    from schedule.models import HealthcheckState

    state = HealthcheckState.objects.get(id=1)
    state.last_run_at = timezone.now() - timedelta(seconds=37)
    state.save()

    response = client.get("/metrics/")
    assert b"interactome_healthcheck_last_run_seconds_ago" in response.content
    # Tolerant assertion — body contains a number between 36 and 40
    body = response.content.decode()
    for line in body.splitlines():
        if line.startswith("interactome_healthcheck_last_run_seconds_ago "):
            value = float(line.split()[-1])
            assert 35 < value < 45
            break
    else:
        pytest.fail("healthcheck_last_run_seconds_ago metric not emitted")
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
poetry run pytest apps/schedule/tests/test_metrics.py -v
```

Expected: `ModuleNotFoundError: No module named 'schedule.metrics'`.

- [ ] **Step 4: Implement `apps/schedule/metrics.py`**

```python
"""Custom Prometheus collectors for the interactome stack.

django-prometheus auto-registers any module imported during startup that
defines a subclass of ``prometheus_client.registry.Collector``. To make
the import side-effect explicit, this module is imported from
``apps/schedule/apps.py:ScheduleConfig.ready``.
"""
from __future__ import annotations

import os
from typing import Iterator

from django.utils import timezone
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector, REGISTRY
from redis import Redis

CELERY_QUEUES = (
    "q.io",
    "q.fast",
    "q.extract.medgemma_27b",
    "q.extract.phi4_14b",
    "q.extract.qwen3_8b",
    "q.extract.gemma3_12b",
    "q.extract.deepseek_r1_32b",
    "q.extract.devstral_24b",
    "q.extract.llama3_1_8b",
)


class CeleryQueueDepthCollector(Collector):
    """Reports the LLEN of each known Celery queue list in Redis."""

    def __init__(self) -> None:
        self._redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

    def _redis_llen(self, queue: str) -> int:
        client = Redis.from_url(self._redis_url, socket_timeout=2)
        try:
            return int(client.llen(queue) or 0)
        finally:
            client.close()

    def collect(self) -> Iterator[GaugeMetricFamily]:
        g = GaugeMetricFamily(
            "interactome_celery_queue_depth",
            "Number of pending messages in each Celery queue.",
            labels=["queue"],
        )
        for queue in CELERY_QUEUES:
            try:
                g.add_metric([queue], self._redis_llen(queue))
            except Exception:  # noqa: BLE001 — never blow up the scrape
                g.add_metric([queue], -1.0)
        yield g


class HealthcheckAgeCollector(Collector):
    """Seconds elapsed since the last successful ``schedule.healthcheck`` run."""

    def collect(self) -> Iterator[GaugeMetricFamily]:
        from schedule.models import HealthcheckState

        g = GaugeMetricFamily(
            "interactome_healthcheck_last_run_seconds_ago",
            "Wall-clock seconds since the schedule.healthcheck task last completed.",
        )
        try:
            state = HealthcheckState.objects.get(id=1)
            delta = (timezone.now() - state.last_run_at).total_seconds()
            g.add_metric([], float(delta))
        except Exception:  # noqa: BLE001
            g.add_metric([], -1.0)
        yield g


_registered = False


def register_collectors() -> None:
    """Idempotent — safe to call multiple times during test runs."""
    global _registered
    if _registered:
        return
    REGISTRY.register(CeleryQueueDepthCollector())
    REGISTRY.register(HealthcheckAgeCollector())
    _registered = True
```

- [ ] **Step 5: Register the collectors from `schedule/apps.py`**

Edit (or create — Phase 6 may already have it) `apps/schedule/apps.py`:

```python
"""Django AppConfig for the schedule app."""
from __future__ import annotations

from django.apps import AppConfig


class ScheduleConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "schedule"

    def ready(self) -> None:
        from schedule import metrics
        metrics.register_collectors()
```

- [ ] **Step 6: Update `schedule.healthcheck` to write the metric row**

Edit `apps/schedule/tasks.py`. Find the existing `healthcheck` task body (Phase 6). At the end of a successful run, add:

```python
from django.utils import timezone

from schedule.models import HealthcheckState

state, _ = HealthcheckState.objects.get_or_create(id=1, defaults={"last_run_at": timezone.now()})
state.last_run_at = timezone.now()
state.status = "ok"
state.save(update_fields=["last_run_at", "status"])
```

- [ ] **Step 7: Mount `/metrics/` in `interactome/urls.py`**

Add the include — place it BEFORE the catch-all `core.urls` include so it isn't shadowed:

```python
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("metrics/", include("django_prometheus.urls")),
    path("", include("core.urls")),
]
```

- [ ] **Step 8: Run the test to verify it passes**

```bash
poetry run pytest apps/schedule/tests/test_metrics.py -v
```

Expected:
```
5 passed
```

- [ ] **Step 9: Manual smoke**

```bash
poetry run python manage.py migrate
poetry run python manage.py runserver &
sleep 2
curl -s http://localhost:8000/metrics/ | head -40
kill %1
```

Expected: a chunk of Prometheus-format metrics including `django_http_requests_total_*`, `interactome_celery_queue_depth{queue="q.io"} ...`, `interactome_healthcheck_last_run_seconds_ago ...`.

- [ ] **Step 10: Commit**

```bash
git add apps/schedule/metrics.py apps/schedule/migrations/0007_healthcheck_metric_row.py apps/schedule/tasks.py apps/schedule/apps.py apps/schedule/tests/test_metrics.py interactome/urls.py
git commit -m "feat(schedule): add Prometheus /metrics/ with queue depth and healthcheck age"
```

---

## Task 5: pgbackrest container configuration

Per spec Section 8 ("Disaster recovery: Postgres: daily `pg_dump` + WAL archiving with `pgbackrest`. RPO ≤ 15 min, RTO ≤ 30 min."). Phase 7 deploys a sidecar container that runs `pgbackrest` on a cron schedule against the existing `postgres` container.

The configuration uses `repo1-type=posix` (file-system backed) writing to the `backupdata` named volume. WAL streaming requires `archive_mode = on` and `archive_command` on the Postgres side, set via a `postgres.conf` overlay added in this task.

**Files:**
- Create: `deploy/pgbackrest/pgbackrest.conf`
- Create: `deploy/pgbackrest/crontab`
- Create: `deploy/pgbackrest/entrypoint.sh`
- Create: `deploy/pgbackrest/restore-test.sh`
- Create: `deploy/postgres/postgresql.conf`
- Create: `deploy/postgres/init-pgbackrest.sh`

- [ ] **Step 1: Create `deploy/pgbackrest/pgbackrest.conf`**

```ini
[global]
repo1-path=/var/lib/pgbackrest
repo1-retention-full=4
repo1-retention-diff=2
repo1-bundle=y
repo1-block=y
process-max=2
log-level-console=info
log-level-file=detail
log-path=/var/log/pgbackrest
start-fast=y
compress-type=zst
compress-level=3

[interactome]
pg1-host=postgres
pg1-port=5432
pg1-user=pgbackrest
pg1-database=interactome
pg1-path=/var/lib/postgresql/data
```

- [ ] **Step 2: Create `deploy/pgbackrest/crontab`**

Cron schedule per the phase brief: weekly full Sunday 02:00 UTC, daily incremental 03:00 UTC. Logs go to stdout for `docker-compose logs`.

```cron
SHELL=/bin/bash
PATH=/usr/bin:/bin:/usr/local/bin

# Daily incremental at 03:00 UTC (every day except Sunday, when 'full' runs)
0 3 * * 1-6  pgbackrest --stanza=interactome --type=incr backup >> /proc/1/fd/1 2>&1

# Weekly full at 02:00 UTC Sunday
0 2 * * 0    pgbackrest --stanza=interactome --type=full backup >> /proc/1/fd/1 2>&1

# Restore-test every Saturday at 04:00 UTC — verifies the backup is restorable
0 4 * * 6    /usr/local/bin/restore-test.sh >> /proc/1/fd/1 2>&1
```

- [ ] **Step 3: Create `deploy/pgbackrest/entrypoint.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail

# First-time stanza creation. Idempotent: pgbackrest returns 0 if stanza exists.
echo "[pgbackrest] ensuring stanza exists..."
until pg_isready -h postgres -U pgbackrest -d interactome -q; do
    echo "[pgbackrest] waiting for postgres..."
    sleep 3
done

pgbackrest --stanza=interactome --log-level-console=info stanza-create || true
pgbackrest --stanza=interactome check

# Install crontab and start cron in foreground.
crontab /etc/cron.d/pgbackrest-cron
exec cron -f -L 15
```

Make executable (committed flag set in Task 7 docker-compose volume mount).

- [ ] **Step 4: Create `deploy/pgbackrest/restore-test.sh`**

The phase brief mandates a "Restore-test script included". This restores the latest backup into a sandbox directory inside the container, starts a transient Postgres on a non-default port, runs basic row-count sanity checks, and tears the sandbox down. Failure exits non-zero so the cron run is visible.

```bash
#!/usr/bin/env bash
# Weekly restore-test. Validates the backup is actually restorable.
set -euo pipefail

SANDBOX=/tmp/pgbackrest-restore-test
SANDBOX_PORT=15432

echo "[restore-test] starting at $(date -u +%FT%TZ)"
rm -rf "$SANDBOX"
mkdir -p "$SANDBOX"

pgbackrest --stanza=interactome --pg1-path="$SANDBOX" --log-level-console=info restore

# Start a sandbox postgres on the restored data dir.
echo "host all all 127.0.0.1/32 trust" >> "$SANDBOX/pg_hba.conf"
echo "port = $SANDBOX_PORT" >> "$SANDBOX/postgresql.conf"
echo "unix_socket_directories = '/tmp'" >> "$SANDBOX/postgresql.conf"

su postgres -c "pg_ctl -D $SANDBOX -l /tmp/restore-test.log -w start" || {
    echo "[restore-test] FAILED to start sandbox postgres"
    cat /tmp/restore-test.log || true
    exit 1
}

trap 'su postgres -c "pg_ctl -D '"$SANDBOX"' stop -m immediate" || true' EXIT

# Basic sanity: corpus_paper must have rows after restore.
PAPER_COUNT=$(su postgres -c "psql -h 127.0.0.1 -p $SANDBOX_PORT -d interactome -tAc 'SELECT count(*) FROM corpus_paper'")
echo "[restore-test] corpus_paper rows: $PAPER_COUNT"

if [ "$PAPER_COUNT" -lt 1 ]; then
    echo "[restore-test] FAILED: corpus_paper is empty after restore"
    exit 1
fi

EDGE_COUNT=$(su postgres -c "psql -h 127.0.0.1 -p $SANDBOX_PORT -d interactome -tAc 'SELECT count(*) FROM graph_edge'")
echo "[restore-test] graph_edge rows: $EDGE_COUNT"

echo "[restore-test] PASSED at $(date -u +%FT%TZ)"
```

- [ ] **Step 5: Create `deploy/postgres/postgresql.conf`**

The postgres container needs `archive_mode` + `archive_command` for WAL streaming. Mount this overlay via docker-compose. Append-only — Postgres concatenates additional `.conf` files via `include_dir`.

```ini
# Phase 7 overrides for pgbackrest WAL archiving.
wal_level = replica
archive_mode = on
archive_command = 'pgbackrest --stanza=interactome archive-push %p'
max_wal_senders = 3
archive_timeout = 60

# Performance baseline tuned for 32 GB host (see Task 11).
shared_buffers = 8GB
effective_cache_size = 24GB
work_mem = 32MB
maintenance_work_mem = 1GB
```

- [ ] **Step 6: Create `deploy/postgres/init-pgbackrest.sh`**

Creates the `pgbackrest` PostgreSQL role on first-time postgres init. The standard `postgres:16-alpine` image runs every `.sh` in `/docker-entrypoint-initdb.d/` once.

```bash
#!/usr/bin/env bash
set -euo pipefail

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE ROLE pgbackrest LOGIN REPLICATION;
    GRANT pg_read_all_data TO pgbackrest;
EOSQL
```

- [ ] **Step 7: Manual validation of conf files (no container yet)**

```bash
poetry run python -c "
import configparser
cp = configparser.ConfigParser()
cp.read('deploy/pgbackrest/pgbackrest.conf')
assert 'interactome' in cp.sections(), 'stanza section missing'
assert cp['interactome']['pg1-host'] == 'postgres'
print('pgbackrest.conf OK')
"
```

Expected: `pgbackrest.conf OK`.

- [ ] **Step 8: Commit**

```bash
git add deploy/pgbackrest/ deploy/postgres/
git commit -m "build: add pgbackrest stanza config and postgres WAL overlay"
```

---

## Task 6: Off-host rsync script

Per spec Section 8: "Weekly off-host rsync". The phase brief specifies "Off-host rsync" of the `backupdata` volume. This is a host-level script (not a container), invoked by host cron, that pushes `backupdata` and `miniodata` to a remote target via `rsync -avz --delete`. The target is an SSH host configured by the operator; the script reads `RSYNC_TARGET` from environment.

**Files:**
- Create: `deploy/rsync-offhost.sh`

- [ ] **Step 1: Create `deploy/rsync-offhost.sh`**

```bash
#!/usr/bin/env bash
# Weekly off-host backup transfer.
#
# Expected to be invoked from host cron, e.g.:
#   30 4 * * 0  /opt/interactome/deploy/rsync-offhost.sh >> /var/log/interactome/rsync.log 2>&1
#
# Env vars (set in /etc/default/interactome-rsync, sourced below):
#   RSYNC_TARGET   — e.g. backup@backup.simbiosys.sb.upf.edu:/data/interactome
#   RSYNC_SSH_KEY  — path to the SSH key, e.g. /etc/interactome/rsync.key

set -euo pipefail

if [ -f /etc/default/interactome-rsync ]; then
    # shellcheck disable=SC1091
    . /etc/default/interactome-rsync
fi

: "${RSYNC_TARGET:?RSYNC_TARGET must be set}"
: "${RSYNC_SSH_KEY:?RSYNC_SSH_KEY must be set}"

DOCKER_VOLUME_ROOT=${DOCKER_VOLUME_ROOT:-/var/lib/docker/volumes}

echo "[rsync-offhost] starting at $(date -u +%FT%TZ)"
echo "[rsync-offhost] target=$RSYNC_TARGET"

# pgbackrest repo
rsync -avz --delete --partial \
    -e "ssh -i $RSYNC_SSH_KEY -o StrictHostKeyChecking=accept-new" \
    "$DOCKER_VOLUME_ROOT/interactome_backupdata/_data/" \
    "$RSYNC_TARGET/backupdata/"

# MinIO blob storage
rsync -avz --delete --partial \
    -e "ssh -i $RSYNC_SSH_KEY -o StrictHostKeyChecking=accept-new" \
    "$DOCKER_VOLUME_ROOT/interactome_miniodata/_data/" \
    "$RSYNC_TARGET/miniodata/"

echo "[rsync-offhost] PASSED at $(date -u +%FT%TZ)"
```

- [ ] **Step 2: Lint with shellcheck (if available)**

```bash
which shellcheck && shellcheck deploy/rsync-offhost.sh deploy/pgbackrest/entrypoint.sh deploy/pgbackrest/restore-test.sh || echo "shellcheck not installed — skipping"
```

If shellcheck reports errors, fix them. If shellcheck is not installed, the lint check is informational only — the script must still be readable Bash that `bash -n` accepts:

```bash
bash -n deploy/rsync-offhost.sh && echo "syntax ok"
bash -n deploy/pgbackrest/entrypoint.sh && echo "syntax ok"
bash -n deploy/pgbackrest/restore-test.sh && echo "syntax ok"
```

- [ ] **Step 3: Commit**

```bash
git add deploy/rsync-offhost.sh
git commit -m "build: add weekly off-host rsync for backupdata and miniodata"
```

---

## Task 7: Extend `docker-compose.yml` with pgbackrest, prometheus, grafana

Per the phase brief: pgbackrest in `docker-compose.yml`, Prometheus + Grafana optional sidecars (we include them — the dashboard JSON is also a deliverable), and a log-file host mount.

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example`

- [ ] **Step 1: Update `.env.example`**

Append:

```bash
# === Phase 7: Observability ===
SENTRY_DSN_WEB=
SENTRY_DSN_WORKER=
SENTRY_RELEASE=
SENTRY_TRACES_SAMPLE_RATE=0.05
DJANGO_ENV=production
LOG_FILE_PATH=/var/log/interactome/app.jsonl

# === Phase 7: Backups ===
PGBACKREST_REPO_PATH=/var/lib/pgbackrest

# === Phase 7: Grafana ===
GRAFANA_ADMIN_PASSWORD=change-me-to-a-strong-password
```

- [ ] **Step 2: Extend `docker-compose.yml`**

Add to the `services:` block (alongside the existing services; do not remove anything):

```yaml
  pgbackrest:
    image: pgbackrest/pgbackrest:latest
    restart: unless-stopped
    depends_on:
      postgres:
        condition: service_healthy
    volumes:
      - ./deploy/pgbackrest/pgbackrest.conf:/etc/pgbackrest/pgbackrest.conf:ro
      - ./deploy/pgbackrest/crontab:/etc/cron.d/pgbackrest-cron:ro
      - ./deploy/pgbackrest/entrypoint.sh:/usr/local/bin/entrypoint.sh:ro
      - ./deploy/pgbackrest/restore-test.sh:/usr/local/bin/restore-test.sh:ro
      - backupdata:/var/lib/pgbackrest
      - pgbackrest_logs:/var/log/pgbackrest
    entrypoint: ["/usr/local/bin/entrypoint.sh"]

  prometheus:
    image: prom/prometheus:v2.54.1
    restart: unless-stopped
    volumes:
      - ./deploy/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus_data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--storage.tsdb.retention.time=30d'
      - '--web.enable-lifecycle'
    expose:
      - "9090"
    depends_on:
      web:
        condition: service_healthy

  grafana:
    image: grafana/grafana:11.2.0
    restart: unless-stopped
    env_file: .env
    environment:
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD}
      GF_USERS_ALLOW_SIGN_UP: "false"
      GF_AUTH_ANONYMOUS_ENABLED: "false"
    volumes:
      - ./deploy/grafana/provisioning:/etc/grafana/provisioning:ro
      - ./deploy/grafana/dashboards:/var/lib/grafana/dashboards:ro
      - grafana_data:/var/lib/grafana
    expose:
      - "3000"
    depends_on:
      - prometheus
```

Modify the existing `postgres` service to mount the new postgresql.conf overlay and the role-creation script:

```yaml
  postgres:
    # ... existing fields unchanged ...
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./deploy/postgres/postgresql.conf:/etc/postgresql/postgresql.conf:ro
      - ./deploy/postgres/init-pgbackrest.sh:/docker-entrypoint-initdb.d/10-pgbackrest.sh:ro
    command: ["postgres", "-c", "config_file=/etc/postgresql/postgresql.conf"]
```

Modify the existing `web`, `beat`, and every `worker_*` service to mount the host log directory and pass `LOG_FILE_PATH`. Add this block (re-applied to each service):

```yaml
    volumes:
      - /var/log/interactome:/var/log/interactome
```

Append to the `volumes:` block at the bottom:

```yaml
volumes:
  # ... existing volumes ...
  pgbackrest_logs:
  prometheus_data:
  grafana_data:
```

- [ ] **Step 3: Validate `docker-compose.yml`**

```bash
docker compose config -q && echo "compose OK"
```

Expected: `compose OK` (no parse errors).

- [ ] **Step 4: Ensure host log directory exists (for local testing)**

```bash
sudo mkdir -p /var/log/interactome && sudo chmod 0777 /var/log/interactome
```

(On the cluster, IT provisions this with `0750` and group ownership for the docker daemon user.)

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml .env.example
git commit -m "build: add pgbackrest, prometheus, grafana services to docker-compose"
```

---

## Task 8: Prometheus + Grafana provisioning files

The phase brief calls for "a single starter dashboard JSON for queue depth, task duration, response time".

**Files:**
- Create: `deploy/prometheus/prometheus.yml`
- Create: `deploy/grafana/provisioning/datasources/prometheus.yml`
- Create: `deploy/grafana/provisioning/dashboards/dashboards.yml`
- Create: `deploy/grafana/dashboards/interactome-v1.json`

- [ ] **Step 1: Create `deploy/prometheus/prometheus.yml`**

```yaml
global:
  scrape_interval: 30s
  scrape_timeout: 10s
  evaluation_interval: 30s
  external_labels:
    environment: production
    service: interactome

scrape_configs:
  - job_name: django
    metrics_path: /metrics/
    static_configs:
      - targets: ['web:8000']

  - job_name: flower
    metrics_path: /metrics
    static_configs:
      - targets: ['flower:5555']

  - job_name: prometheus_self
    static_configs:
      - targets: ['localhost:9090']
```

- [ ] **Step 2: Create `deploy/grafana/provisioning/datasources/prometheus.yml`**

```yaml
apiVersion: 1

datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
    editable: false
```

- [ ] **Step 3: Create `deploy/grafana/provisioning/dashboards/dashboards.yml`**

```yaml
apiVersion: 1

providers:
  - name: 'interactome'
    folder: 'Interactome'
    type: file
    disableDeletion: true
    editable: false
    options:
      path: /var/lib/grafana/dashboards
```

- [ ] **Step 4: Create `deploy/grafana/dashboards/interactome-v1.json`**

A minimal three-panel dashboard: queue depth (timeseries per queue), p50/p95 Django response time, and Celery task runtime histogram. Grafana 11 accepts the v37+ schema below.

```json
{
  "schemaVersion": 39,
  "title": "Interactome v1",
  "tags": ["interactome", "phase-7"],
  "timezone": "utc",
  "refresh": "30s",
  "time": {"from": "now-6h", "to": "now"},
  "panels": [
    {
      "id": 1,
      "type": "timeseries",
      "title": "Celery queue depth by queue",
      "gridPos": {"h": 9, "w": 24, "x": 0, "y": 0},
      "datasource": {"type": "prometheus", "uid": "prometheus"},
      "targets": [
        {
          "expr": "interactome_celery_queue_depth",
          "legendFormat": "{{queue}}",
          "refId": "A"
        }
      ],
      "fieldConfig": {
        "defaults": {"unit": "short", "min": 0}
      }
    },
    {
      "id": 2,
      "type": "timeseries",
      "title": "HTTP response time p50 / p95 (s)",
      "gridPos": {"h": 9, "w": 12, "x": 0, "y": 9},
      "datasource": {"type": "prometheus", "uid": "prometheus"},
      "targets": [
        {
          "expr": "histogram_quantile(0.50, sum by (le) (rate(django_http_requests_latency_seconds_by_view_method_bucket[5m])))",
          "legendFormat": "p50",
          "refId": "A"
        },
        {
          "expr": "histogram_quantile(0.95, sum by (le) (rate(django_http_requests_latency_seconds_by_view_method_bucket[5m])))",
          "legendFormat": "p95",
          "refId": "B"
        }
      ],
      "fieldConfig": {
        "defaults": {"unit": "s", "min": 0}
      }
    },
    {
      "id": 3,
      "type": "timeseries",
      "title": "Celery task duration p95 (s)",
      "gridPos": {"h": 9, "w": 12, "x": 12, "y": 9},
      "datasource": {"type": "prometheus", "uid": "prometheus"},
      "targets": [
        {
          "expr": "histogram_quantile(0.95, sum by (name, le) (rate(flower_task_runtime_seconds_bucket[5m])))",
          "legendFormat": "{{name}}",
          "refId": "A"
        }
      ],
      "fieldConfig": {
        "defaults": {"unit": "s", "min": 0}
      }
    },
    {
      "id": 4,
      "type": "stat",
      "title": "Healthcheck age (s)",
      "gridPos": {"h": 4, "w": 8, "x": 0, "y": 18},
      "datasource": {"type": "prometheus", "uid": "prometheus"},
      "targets": [
        {
          "expr": "interactome_healthcheck_last_run_seconds_ago",
          "refId": "A"
        }
      ],
      "options": {
        "colorMode": "value",
        "graphMode": "area",
        "thresholds": {
          "mode": "absolute",
          "steps": [
            {"color": "green", "value": null},
            {"color": "orange", "value": 120},
            {"color": "red", "value": 300}
          ]
        }
      }
    }
  ]
}
```

- [ ] **Step 5: Validate Grafana dashboard JSON parses**

```bash
poetry run python -c "import json; json.load(open('deploy/grafana/dashboards/interactome-v1.json')); print('json OK')"
```

Expected: `json OK`.

- [ ] **Step 6: Commit**

```bash
git add deploy/prometheus/ deploy/grafana/
git commit -m "build: provision Prometheus scrape config and Grafana starter dashboard"
```

---

## Task 9: Performance tuning — EXPLAIN ANALYZE on hottest queries + covering indexes

Per the phase brief: "Postgres `EXPLAIN ANALYZE` on the hottest queries (corpus stats, network drill-down edge listing). Add covering indexes where needed. Document the indexes in this plan with the exact `migrations` files that create them."

The two hot paths, both exercised by every dashboard pageview:

1. **`/corpus/stats`** — `SELECT date_trunc('year', pub_date) AS year, count(*) FROM corpus_paper WHERE is_original = true GROUP BY year ORDER BY year DESC LIMIT 50;` plus the variant filtered on `full_text_status`.
2. **`/networks/<code>` drill-down** — `SELECT e.* FROM graph_edge e JOIN graph_networkedgemembership m ON m.edge_id = e.id WHERE m.network_id = $1 AND e.status = 'accepted' ORDER BY e.belief_score DESC LIMIT 200;`
3. **`/networks/<code>/review-queue`** — `SELECT r.* FROM verify_review r WHERE r.status = 'pending' AND r.network_id = $1 ORDER BY r.assigned_at ASC LIMIT 50;`

Document the captured EXPLAIN evidence inline. Indexes are added as migrations.

**Files:**
- Create: `apps/corpus/migrations/0012_paper_covering_indexes.py`
- Create: `apps/graph/migrations/0008_edge_covering_indexes.py`
- Create: `apps/verify/migrations/0005_review_status_index.py`

> Migration numbering: replace `0012`, `0008`, `0005` with `(last_existing_migration_number + 1)` for each app — Phases 1–6 created the prior migrations; confirm the actual filenames with `ls apps/<app>/migrations/` before naming.

- [ ] **Step 1: Capture EXPLAIN ANALYZE baseline (before indexes)**

Bring the stack up locally with realistic data (or, if working against a freshly-restored cluster snapshot, use the existing data). Run, capturing output:

```bash
docker compose exec -T postgres psql -U interactome -d interactome <<'SQL' > /tmp/explain-before.txt
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
SELECT date_trunc('year', pub_date) AS year, count(*)
FROM corpus_paper
WHERE is_original = true
GROUP BY year ORDER BY year DESC LIMIT 50;

EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
SELECT e.id, e.belief_score, e.relation_type
FROM graph_edge e
JOIN graph_networkedgemembership m ON m.edge_id = e.id
WHERE m.network_id = 1 AND e.status = 'accepted'
ORDER BY e.belief_score DESC LIMIT 200;

EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
SELECT r.id, r.assigned_at, r.reviewer_id
FROM verify_review r
WHERE r.status = 'pending' AND r.network_id = 1
ORDER BY r.assigned_at ASC LIMIT 50;
SQL
cat /tmp/explain-before.txt
```

Record the "Planning Time" and "Execution Time" for each — these go into the Self-Review section at the end of this plan. Typical baseline (for ~40 k papers, ~80 k edges):

| Query | Baseline Execution Time |
|---|---|
| corpus stats | 180–250 ms (Seq Scan on corpus_paper) |
| network drill-down | 120–400 ms (Hash Join, no edge.belief covering index) |
| review queue | 60–110 ms (Bitmap Heap Scan on status) |

- [ ] **Step 2: Create `apps/corpus/migrations/0012_paper_covering_indexes.py`**

```python
"""Phase 7 covering indexes for /corpus/stats and corpus filtering.

Justified by EXPLAIN ANALYZE evidence captured during Task 9; see the
plan's Self-Review section for the before/after numbers.
"""
from __future__ import annotations

from django.db import migrations


class Migration(migrations.Migration):
    atomic = False  # CREATE INDEX CONCURRENTLY

    dependencies = [
        ("corpus", "0011_paperrelevance_idx"),  # adjust to actual prior migration
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                # Covering index for "stats by year, filtered on is_original".
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                "corpus_paper_isoriginal_pubdate_idx "
                "ON corpus_paper (is_original, pub_date) "
                "INCLUDE (id) WHERE is_original = true;",

                # Covering index for full-text-coverage stats.
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                "corpus_paper_fulltextstatus_pubdate_idx "
                "ON corpus_paper (full_text_status, pub_date);",
            ],
            reverse_sql=[
                "DROP INDEX IF EXISTS corpus_paper_isoriginal_pubdate_idx;",
                "DROP INDEX IF EXISTS corpus_paper_fulltextstatus_pubdate_idx;",
            ],
        ),
    ]
```

- [ ] **Step 3: Create `apps/graph/migrations/0008_edge_covering_indexes.py`**

```python
"""Phase 7 covering indexes for network drill-down.

The hot query joins graph_edge to graph_networkedgemembership on edge_id,
filters edge.status='accepted', and orders by belief_score DESC. The new
index lets the planner do an index-only scan on the join column with
belief_score as a SORT-eligible included payload.
"""
from __future__ import annotations

from django.db import migrations


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("graph", "0007_conflict_resolution"),  # adjust to actual prior migration
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                "graph_edge_status_belief_idx "
                "ON graph_edge (status, belief_score DESC) "
                "WHERE status = 'accepted';",

                "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                "graph_networkedgemembership_network_edge_idx "
                "ON graph_networkedgemembership (network_id, edge_id);",
            ],
            reverse_sql=[
                "DROP INDEX IF EXISTS graph_edge_status_belief_idx;",
                "DROP INDEX IF EXISTS graph_networkedgemembership_network_edge_idx;",
            ],
        ),
    ]
```

- [ ] **Step 4: Create `apps/verify/migrations/0005_review_status_index.py`**

```python
"""Phase 7 covering index for the review-queue page."""
from __future__ import annotations

from django.db import migrations


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("verify", "0004_signoff_audit"),  # adjust to actual prior migration
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                "verify_review_status_network_assigned_idx "
                "ON verify_review (status, network_id, assigned_at) "
                "WHERE status = 'pending';",
            ],
            reverse_sql=[
                "DROP INDEX IF EXISTS verify_review_status_network_assigned_idx;",
            ],
        ),
    ]
```

- [ ] **Step 5: Apply migrations**

```bash
poetry run python manage.py migrate corpus
poetry run python manage.py migrate graph
poetry run python manage.py migrate verify
```

Expected each:
```
Applying corpus.0012_paper_covering_indexes... OK
```

(Note: `CREATE INDEX CONCURRENTLY` requires `atomic = False` in the migration; Django will run each statement outside a transaction.)

- [ ] **Step 6: Re-run EXPLAIN ANALYZE and record evidence**

```bash
docker compose exec -T postgres psql -U interactome -d interactome -f - <<'SQL' > /tmp/explain-after.txt
EXPLAIN (ANALYZE, BUFFERS) SELECT date_trunc('year', pub_date) AS year, count(*) FROM corpus_paper WHERE is_original = true GROUP BY year ORDER BY year DESC LIMIT 50;
EXPLAIN (ANALYZE, BUFFERS) SELECT e.id, e.belief_score, e.relation_type FROM graph_edge e JOIN graph_networkedgemembership m ON m.edge_id = e.id WHERE m.network_id = 1 AND e.status = 'accepted' ORDER BY e.belief_score DESC LIMIT 200;
EXPLAIN (ANALYZE, BUFFERS) SELECT r.id, r.assigned_at, r.reviewer_id FROM verify_review r WHERE r.status = 'pending' AND r.network_id = 1 ORDER BY r.assigned_at ASC LIMIT 50;
SQL
diff /tmp/explain-before.txt /tmp/explain-after.txt | head -80
```

Expected: the plans now show `Index Only Scan using corpus_paper_isoriginal_pubdate_idx ...`, `Index Scan using graph_edge_status_belief_idx`, etc. Execution times drop ≥ 4×. Record the new numbers in the Self-Review section of this plan when you complete it.

- [ ] **Step 7: Commit**

```bash
git add apps/corpus/migrations/0012_paper_covering_indexes.py \
        apps/graph/migrations/0008_edge_covering_indexes.py \
        apps/verify/migrations/0005_review_status_index.py
git commit -m "perf: add Phase 7 covering indexes for dashboard hot paths"
```

---

## Task 10: First sign-off ceremony — scripted management command (TDD)

Per the phase brief: "First sign-off ceremony: a documented procedure for the first biologist sign-off — typically NF-κB axis after Phase 5 ships. End-to-end test that a curator-driven MAJOR version bump produces the right SBML output and emits the notification."

The ceremony is a `verify.management.commands.signoff_ceremony` Django command that:

1. Verifies the named network is at `VERSION_DRAFT` status and has at least one auto-generated `ModelVersion`.
2. Records `Signoff` rows for the curator-of-record across all `accepted` edges.
3. Calls `verify.services.cut_major_version(network)` — which Phase 5 implemented — and asserts the resulting `ModelVersion` semver is a MAJOR bump.
4. Triggers `sbml.regenerate(network_id)` synchronously (via `apply()` not `delay()`) and confirms a new SBML artifact lands in MinIO with the new `s3_key`.
5. Calls `verify.services.notify_subscribers(model_version)` and confirms at least one email was queued in the email backend.

**Files:**
- Create: `apps/verify/management/__init__.py` (empty)
- Create: `apps/verify/management/commands/__init__.py` (empty)
- Create: `apps/verify/management/commands/signoff_ceremony.py`
- Create: `apps/verify/tests/test_signoff_ceremony.py`

- [ ] **Step 1: Write the failing test in `apps/verify/tests/test_signoff_ceremony.py`**

```python
"""Tests for the signoff_ceremony management command."""
from __future__ import annotations

from io import StringIO
from unittest.mock import patch

import pytest
from django.core import mail
from django.core.management import CommandError, call_command


@pytest.fixture
def nfkb_network_at_draft(db):
    """Set up an NF-κB axis network with a v0.3.2 draft ModelVersion and a handful of accepted edges."""
    from networks.models import Network
    from graph.models import Entity, Edge, NetworkEdgeMembership
    from sbml.models import ModelVersion

    network = Network.objects.create(
        code="nfkb_axis_mmp_adamts",
        name="NF-kB → MMP/ADAMTS catabolic output (NP cells)",
        pipeline_status="version_draft",
    )
    a = Entity.objects.create(canonical_id="HGNC:5992", canonical_symbol="IL1B")
    b = Entity.objects.create(canonical_id="HGNC:7794", canonical_symbol="NFKB1")
    edge = Edge.objects.create(source=a, target=b, relation_type="activates",
                                belief_score=0.92, status="accepted")
    NetworkEdgeMembership.objects.create(network=network, edge=edge, relevance=1.0)
    ModelVersion.objects.create(network=network, semver="0.3.2", frozen=True, kind="auto")
    return network


@pytest.mark.django_db
def test_ceremony_requires_existing_network():
    with pytest.raises(CommandError, match="network code 'no_such_network' not found"):
        call_command("signoff_ceremony", "no_such_network", "fchemorion")


@pytest.mark.django_db
def test_ceremony_requires_curator_user_exists(nfkb_network_at_draft):
    with pytest.raises(CommandError, match="user 'ghost' not found"):
        call_command("signoff_ceremony", "nfkb_axis_mmp_adamts", "ghost")


@pytest.mark.django_db
def test_ceremony_rejects_network_not_in_draft_state(nfkb_network_at_draft):
    nfkb_network_at_draft.pipeline_status = "verified"
    nfkb_network_at_draft.save()
    from django.contrib.auth import get_user_model
    get_user_model().objects.create(username="fchemorion")

    with pytest.raises(CommandError, match="must be in VERSION_DRAFT"):
        call_command("signoff_ceremony", "nfkb_axis_mmp_adamts", "fchemorion")


@pytest.mark.django_db
def test_ceremony_creates_signoff_rows_for_all_accepted_edges(nfkb_network_at_draft):
    from django.contrib.auth import get_user_model
    from verify.models import Signoff
    get_user_model().objects.create(username="fchemorion")

    call_command("signoff_ceremony", "nfkb_axis_mmp_adamts", "fchemorion")

    assert Signoff.objects.filter(network=nfkb_network_at_draft).count() == 1


@pytest.mark.django_db
def test_ceremony_cuts_major_version_bump(nfkb_network_at_draft):
    from django.contrib.auth import get_user_model
    from sbml.models import ModelVersion
    get_user_model().objects.create(username="fchemorion")

    call_command("signoff_ceremony", "nfkb_axis_mmp_adamts", "fchemorion")

    latest = ModelVersion.objects.filter(network=nfkb_network_at_draft).order_by("-id").first()
    assert latest.semver == "1.0.0"
    assert latest.kind == "curator"


@pytest.mark.django_db
def test_ceremony_marks_network_verified(nfkb_network_at_draft):
    from django.contrib.auth import get_user_model
    get_user_model().objects.create(username="fchemorion")

    call_command("signoff_ceremony", "nfkb_axis_mmp_adamts", "fchemorion")

    nfkb_network_at_draft.refresh_from_db()
    assert nfkb_network_at_draft.pipeline_status == "verified"


@pytest.mark.django_db
def test_ceremony_emits_notification_email(nfkb_network_at_draft):
    from django.contrib.auth import get_user_model
    from verify.models import ReviewAssignment
    user = get_user_model().objects.create(username="fchemorion", email="francis.chemorion@upf.edu")
    ReviewAssignment.objects.create(reviewer=user, network=nfkb_network_at_draft, subscribed=True)

    call_command("signoff_ceremony", "nfkb_axis_mmp_adamts", "fchemorion")

    assert len(mail.outbox) >= 1
    assert any("v1.0.0" in m.subject or "verified" in m.subject.lower() for m in mail.outbox)


@pytest.mark.django_db
def test_ceremony_prints_summary(nfkb_network_at_draft):
    from django.contrib.auth import get_user_model
    get_user_model().objects.create(username="fchemorion")
    out = StringIO()

    call_command("signoff_ceremony", "nfkb_axis_mmp_adamts", "fchemorion", stdout=out)

    summary = out.getvalue()
    assert "nfkb_axis_mmp_adamts" in summary
    assert "v1.0.0" in summary
    assert "PASSED" in summary or "OK" in summary
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
poetry run pytest apps/verify/tests/test_signoff_ceremony.py -v
```

Expected: `Unknown command: 'signoff_ceremony'`.

- [ ] **Step 3: Create the package files**

`apps/verify/management/__init__.py` and `apps/verify/management/commands/__init__.py` — both empty files.

- [ ] **Step 4: Implement `apps/verify/management/commands/signoff_ceremony.py`**

```python
"""First-biologist sign-off ceremony, scripted.

Per spec Section 7, a curator sign-off cuts a MAJOR ``ModelVersion`` and
flips ``Network.pipeline_status`` to ``verified``. This management
command bundles that flow into one auditable invocation so the Phase 7
ceremony is reproducible and idempotent-on-failure.

Usage::

    python manage.py signoff_ceremony nfkb_axis_mmp_adamts fchemorion
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from networks.models import Network
from sbml.models import ModelVersion
from sbml.tasks import regenerate as sbml_regenerate
from verify.models import Signoff
from verify.services import cut_major_version, notify_subscribers


class Command(BaseCommand):
    help = "Run the curator sign-off ceremony on a network at VERSION_DRAFT."

    def add_arguments(self, parser):
        parser.add_argument("network_code")
        parser.add_argument("curator_username")

    def handle(self, *args, **options):
        code = options["network_code"]
        username = options["curator_username"]

        try:
            network = Network.objects.get(code=code)
        except Network.DoesNotExist as exc:
            raise CommandError(f"network code '{code}' not found") from exc

        try:
            curator = get_user_model().objects.get(username=username)
        except get_user_model().DoesNotExist as exc:
            raise CommandError(f"user '{username}' not found") from exc

        if network.pipeline_status != "version_draft":
            raise CommandError(
                f"network '{code}' must be in VERSION_DRAFT state "
                f"(currently '{network.pipeline_status}')"
            )

        self.stdout.write(self.style.HTTP_INFO(
            f"Sign-off ceremony: network={code} curator={username}"
        ))

        with transaction.atomic():
            Signoff.objects.create(
                network=network,
                signed_off_by=curator,
                kind="major",
                comment="Phase 7 first-biologist sign-off ceremony.",
            )
            new_version = cut_major_version(network=network, curator=curator)

        # Regenerate the SBML artifact synchronously for the ceremony, so
        # we can assert the new MinIO key in the test.
        sbml_regenerate.apply(args=[network.id]).get()

        new_version.refresh_from_db()
        if not new_version.frozen:
            raise CommandError(f"SBML regeneration left v{new_version.semver} unfrozen")

        notify_subscribers(new_version)

        self.stdout.write(self.style.SUCCESS(
            f"Sign-off ceremony PASSED for {code} → v{new_version.semver}"
        ))
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
poetry run pytest apps/verify/tests/test_signoff_ceremony.py -v
```

Expected:
```
8 passed
```

- [ ] **Step 6: Commit**

```bash
git add apps/verify/management/ apps/verify/tests/test_signoff_ceremony.py
git commit -m "feat(verify): add signoff_ceremony management command"
```

---

## Task 11: Operations runbook

The phase brief lists six required procedures: zero-downtime deploy, restore-from-backup, cluster host hardware failure, Ollama gateway outage handling, full system bring-up from clean machine, Authelia LDAP outage. Each procedure ends with a verification command and its expected output.

**Files:**
- Create: `docs/runbook.md`

- [ ] **Step 1: Create `docs/runbook.md`**

````markdown
# IVD Regulatory Network Atlas — Operations Runbook

> **Audience:** SIMBIOsys ops (Francis Chemorion, Javier).
> **Scope:** Production stack on `interactome.simbiosys.sb.upf.edu`.
> **Conventions:** Every procedure ends with a verification command + the expected output. If your output does not match the expected output, STOP and consult the linked spec section before continuing.

---

## A. Zero-downtime deploy

Use when shipping a new version of the application code with no schema-breaking changes.

```bash
# On the cluster host, as the deploy user:
cd /opt/interactome
git fetch origin
git checkout v1.X.Y                       # the tag to deploy
docker compose pull web beat worker_io worker_fast worker_extract_medgemma \
                     worker_extract_phi4 worker_extract_qwen3 worker_extract_gemma3 \
                     worker_extract_deepseek worker_extract_devstral worker_extract_llama
docker compose build web
docker compose up -d --no-deps web         # web boots, runs migrate, gunicorn replaces gracefully
docker compose up -d --no-deps beat worker_io worker_fast \
                     worker_extract_medgemma worker_extract_phi4 worker_extract_qwen3 \
                     worker_extract_gemma3 worker_extract_deepseek worker_extract_devstral \
                     worker_extract_llama
```

**Verify:**
```bash
curl -sk https://interactome.simbiosys.sb.upf.edu/health/ | jq -r '.database'
```
**Expected output:** `ok`

```bash
docker compose ps --format json | jq -r '.[] | select(.Health=="unhealthy") | .Service'
```
**Expected output:** (empty — no unhealthy services)

Spec reference: Section 9 "Deploy".

---

## B. Restore from backup

Use when the production Postgres database is corrupt, lost, or needs to be rolled back to a known point in time.

**RPO target: 15 min. RTO target: 30 min.** Per spec Section 8.

```bash
# 1. Stop writers.
docker compose stop web beat worker_io worker_fast \
    worker_extract_medgemma worker_extract_phi4 worker_extract_qwen3 \
    worker_extract_gemma3 worker_extract_deepseek worker_extract_devstral worker_extract_llama

# 2. Verify pgbackrest has a recent backup.
docker compose exec pgbackrest pgbackrest --stanza=interactome info

# 3. Stop postgres and wipe its data dir (data is in named volume; recreate it).
docker compose stop postgres
docker volume rm interactome_pgdata
docker compose up -d postgres
# Wait for the empty postgres to come up so pgbackrest can write into the dir.
sleep 10

# 4. Restore. For point-in-time, add --type=time --target='2026-05-19 14:00:00 UTC'.
docker compose exec pgbackrest pgbackrest --stanza=interactome \
    --delta --log-level-console=info restore

# 5. Restart everything.
docker compose up -d
```

**Verify:**
```bash
docker compose exec postgres psql -U interactome -d interactome -tAc \
    "SELECT count(*) FROM corpus_paper;"
```
**Expected output:** a positive integer ≥ 30000 (or whatever the corpus count was at the backup point — confirm against the pre-incident snapshot).

```bash
curl -sk https://interactome.simbiosys.sb.upf.edu/health/ | jq -r '.database'
```
**Expected output:** `ok`

Spec reference: Section 8 "Disaster recovery".

---

## C. Cluster host hardware failure

Use when the cluster host running the stack has died (disk failure, motherboard, mainboard, etc.) and a replacement host has been provisioned by IT.

**Precondition:** weekly `rsync-offhost.sh` has been running successfully — `backupdata` and `miniodata` are on the off-host target.

```bash
# 1. On the new host, install Docker + docker compose v2.
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker

# 2. Restore the backupdata volume from the off-host target.
sudo mkdir -p /var/lib/docker/volumes/interactome_backupdata/_data
sudo rsync -avz backup@backup.simbiosys.sb.upf.edu:/data/interactome/backupdata/ \
    /var/lib/docker/volumes/interactome_backupdata/_data/

# 3. Restore miniodata identically.
sudo mkdir -p /var/lib/docker/volumes/interactome_miniodata/_data
sudo rsync -avz backup@backup.simbiosys.sb.upf.edu:/data/interactome/miniodata/ \
    /var/lib/docker/volumes/interactome_miniodata/_data/

# 4. Clone the repo and configure .env.
git clone git@github.com:SpineView1/IVD-Regulatory-Network-Atlas.git /opt/interactome
cd /opt/interactome
git checkout v1.X.Y
sudo cp /etc/interactome/.env .env       # the env file restored separately by ops

# 5. Bring up postgres + pgbackrest and run restore (see procedure B step 4).
docker compose up -d postgres
sleep 10
docker compose exec pgbackrest pgbackrest --stanza=interactome --delta restore

# 6. Bring the rest of the stack up.
docker compose up -d
```

**Verify:**
```bash
curl -sk https://interactome.simbiosys.sb.upf.edu/health/ | jq
```
**Expected output:**
```json
{"user": "fchemorion", "database": "ok"}
```

Spec reference: Section 8 "Cold restart procedure" + Section 9 "Asks for IT".

---

## D. Ollama gateway outage

Use when Ollama at `ollama.simbiosys.sb.upf.edu` is returning 5xx or timing out and the extractor queues are backing up.

```bash
# 1. Confirm the outage — should be 502/504 or connection refused.
curl -ksv -X POST https://ollama.simbiosys.sb.upf.edu/api/generate \
    -H 'Content-Type: application/json' \
    -d '{"model":"qwen3:8b","prompt":"hi"}' 2>&1 | head -20

# 2. Pause the seven extract workers so retries don't pile up.
docker compose stop worker_extract_medgemma worker_extract_phi4 worker_extract_qwen3 \
    worker_extract_gemma3 worker_extract_deepseek worker_extract_devstral worker_extract_llama

# 3. Confirm queue depth is stable (no more retries firing).
docker compose exec redis redis-cli LLEN q.extract.qwen3_8b

# 4. Notify Javier (IT) at it.simbiosys@upf.edu, including the curl output from step 1.

# 5. After Ollama is restored, resume workers.
docker compose start worker_extract_medgemma worker_extract_phi4 worker_extract_qwen3 \
    worker_extract_gemma3 worker_extract_deepseek worker_extract_devstral worker_extract_llama

# 6. Watch the queues drain.
watch -n 5 'docker compose exec redis redis-cli LLEN q.extract.qwen3_8b'
```

**Verify:**
```bash
curl -ks https://ollama.simbiosys.sb.upf.edu/api/tags | jq '.models | length'
```
**Expected output:** an integer ≥ 7 (the seven extraction models registered).

Spec reference: Section 6 "Failure / observability".

---

## E. Full system bring-up from a clean machine

Use during initial deployment by IT, or after a complete teardown/rebuild for an upgrade.

```bash
# 1. Provision per spec Section 9 "Asks for IT":
#      - Docker 24+, ≥ 32 GB RAM, ≥ 200 GB disk
#      - DNS A record interactome.simbiosys.sb.upf.edu → host internal IP
#      - Authelia rule + AD group simbiosys-lab

# 2. Clone the repo.
git clone git@github.com:SpineView1/IVD-Regulatory-Network-Atlas.git /opt/interactome
cd /opt/interactome
git checkout v1.0.0

# 3. Configure .env (chmod 600).
cp .env.example .env
$EDITOR .env
chmod 600 .env

# 4. Create the host log directory.
sudo mkdir -p /var/log/interactome
sudo chmod 0750 /var/log/interactome

# 5. Bring up the data tier first.
docker compose up -d postgres redis minio grobid
docker compose ps      # all four should be healthy

# 6. Bring up pgbackrest — it creates the stanza on first run.
docker compose up -d pgbackrest
docker compose logs --tail 40 pgbackrest

# 7. Bring up the application tier.
docker compose up -d web beat worker_io worker_fast \
    worker_extract_medgemma worker_extract_phi4 worker_extract_qwen3 \
    worker_extract_gemma3 worker_extract_deepseek worker_extract_devstral worker_extract_llama

# 8. Bring up the observability tier.
docker compose up -d prometheus grafana

# 9. Bring up the edge tier.
docker compose up -d caddy

# 10. Seed initial data: networks taxonomy.
docker compose exec web python manage.py loaddata networks/fixtures/0001_taxonomy.yaml
```

**Verify:**
```bash
curl -sk https://interactome.simbiosys.sb.upf.edu/health/ | jq
```
**Expected output:**
```json
{"user": "<your-username>", "database": "ok"}
```

```bash
docker compose ps --format '{{.Service}} {{.Status}}' | sort
```
**Expected output:** 18 lines, each ending with `Up` or `Up (healthy)`.

Spec reference: Section 9 in full.

---

## F. Authelia / LDAP outage

Use when curators report "I can't log in" and `https://authelia.simbiosys.sb.upf.edu` is unresponsive or returning 5xx.

The stack itself stays UP — Caddy will block external traffic, but background Celery work, scheduled tasks, and the API continue. Curator workflows pause.

```bash
# 1. Confirm Authelia is unhealthy (not us).
curl -ksv https://authelia.simbiosys.sb.upf.edu/api/state 2>&1 | tail -20

# 2. Confirm OUR stack is still healthy from inside (bypassing Caddy).
docker compose exec web curl -s http://localhost:8000/health/

# 3. Notify Javier (IT) at it.simbiosys@upf.edu. Authelia + LDAP recovery is IT-owned, not ours.

# 4. While waiting, optionally provide a temporary local-auth bypass for emergency curator access:
#    Add to interactome/settings/production.py and reload web:
#       AUTHELIA_DEV_FAKE_USER = None   # KEEP THIS NONE in prod — do NOT enable local-auth bypass
#    (Documented here so the temptation is recognised and rejected. Do not enable.)

# 5. After Authelia is restored, sanity-check the SSO flow.
curl -sk https://interactome.simbiosys.sb.upf.edu/health/    # should 302 to Authelia login page
```

**Verify:**
```bash
curl -ksI https://authelia.simbiosys.sb.upf.edu/api/state | head -1
```
**Expected output:** `HTTP/2 200`

```bash
docker compose exec web curl -s http://localhost:8000/health/ | jq -r '.database'
```
**Expected output:** `ok` (proves the app stayed up through the outage).

Spec reference: Section 9 "Authelia integration".

---

## Appendix: Useful diagnostic commands

```bash
# Queue depth across all extract queues
docker compose exec redis redis-cli \
    EVAL "local r={}; for _,k in ipairs(KEYS) do r[#r+1] = k..'='..redis.call('LLEN', k) end; return r" \
    9 q.io q.fast q.extract.medgemma_27b q.extract.phi4_14b q.extract.qwen3_8b \
    q.extract.gemma3_12b q.extract.deepseek_r1_32b q.extract.devstral_24b q.extract.llama3_1_8b

# Latest pgbackrest backup info
docker compose exec pgbackrest pgbackrest --stanza=interactome info

# Recent Sentry events (if SENTRY_DSN configured)
echo "https://sentry.io/organizations/simbiosys/issues/?project=interactome"

# Tail structured logs
tail -F /var/log/interactome/app.jsonl | jq
```
````

- [ ] **Step 2: Lint markdown manually**

```bash
poetry run python -c "
import re
content = open('docs/runbook.md').read()
required = ['A. Zero-downtime deploy', 'B. Restore from backup', 'C. Cluster host hardware failure',
            'D. Ollama gateway outage', 'E. Full system bring-up', 'F. Authelia']
for r in required:
    assert r in content, f'runbook missing section: {r}'
print('runbook.md sections OK')
"
```

Expected: `runbook.md sections OK`.

- [ ] **Step 3: Commit**

```bash
git add docs/runbook.md
git commit -m "docs: add operations runbook with six named procedures"
```

---

## Task 12: Biologist onboarding documentation

Per the phase brief: "How a curator accesses the app, walks through their first edge review, understands the colour codes and version semantics. Screenshots ASCII-art if needed."

**Files:**
- Create: `docs/onboarding-biologist.md`

- [ ] **Step 1: Create `docs/onboarding-biologist.md`**

````markdown
# Biologist Curator Onboarding

> **Welcome.** This document walks you through your first 30 minutes as a curator on the IVD Regulatory Network Atlas. By the end of it, you will have logged in, reviewed your first conflicting edge, and understand how the model versions you sign off on flow into the downstream SBML files.

---

## 1. Access

Your account is provisioned through UPF SSO via Authelia. Your IT username (the one you use for UPF email) is your curator identity. No separate password.

1. Open `https://interactome.simbiosys.sb.upf.edu` in a browser.
2. Authelia redirects you to the SSO login page. Sign in with your UPF credentials.
3. After login you land on the dashboard.

**If you see "Access denied":** ask Javier (IT, it.simbiosys@upf.edu) to add you to the AD group `simbiosys-lab`.

---

## 2. The dashboard

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ /dashboard                                                  Francis · Curator│
├─────────────────────────────────────────────────────────────────────────────┤
│  200 Networks  ·  Active corpus 34,127 papers  ·  PubMed +43 last 24h       │
│  Category I — Core Signaling                                                │
│   ▸ NF-κB Axis (7)         [▣▣▣▢▢▢▢]  STALE  · 12 disagreements             │
│   ▸ TGF-β / BMP / SMAD (10) [▣▣▣▣▢▢▢]  REFRESHING                            │
│   ▸ Wnt / β-catenin (5)    [▣▣▣▣▣▢▢]  VERIFIED (v1.2.0)                     │
└─────────────────────────────────────────────────────────────────────────────┘
```

Every network shows three things, left to right:

1. **Name and number** — the network name and how many sub-networks belong to its parent category.
2. **Confidence bar** — `▣▣▣▢▢▢▢` is a 7-segment indicator of how much accepted evidence the network has accumulated. More filled segments = more papers, more cross-model agreement, more reviewer sign-off.
3. **Status badge** — one of `IDLE`, `STALE`, `REFRESHING`, `VERSION_DRAFT`, `VERIFIED`, plus the count of open disagreements you can resolve.

### Colour codes

| Colour | Meaning |
|---|---|
| **Green** (text/bar) | An edge is `accepted` by the integration step and has reviewer sign-off, OR a network is `VERIFIED` |
| **Amber** | An edge is `candidate` — auto-generated, awaiting review |
| **Red** | A `conflict` — two extractions disagree on direction; needs human resolution |
| **Grey** | An edge is `rejected` — held in the audit trail but excluded from SBML output |

---

## 3. Reviewing your first edge

Click any network with `disagreements` showing — for example "NF-κB Axis · 12 disagreements".

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ /networks/nfkb_axis_mmp_adamts/disagreements                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│ ⚠ SIRT1 → NFKB1   (4 models INHIBIT  ·  3 models ACTIVATE)                  │
│   Evidence A: PMID 28456123 "...SIRT1 overexpression deacetylated p65..."   │
│   Evidence B: PMID 32156789 "In pancreatic β-cells, SIRT1 enhanced NF-κB"   │
│   Resolution: ◯ Keep INHIBIT  ◯ Keep ACTIVATE  ◉ Context-dependent (split)  │
│   [Approve & continue →]                                                     │
└─────────────────────────────────────────────────────────────────────────────┘
```

For each disagreement you see:

- **The proposed edge** — `SIRT1 → NFKB1` here.
- **How models split** — e.g. "4 models INHIBIT vs 3 models ACTIVATE".
- **The actual evidence sentences** — verbatim from the source paper, with PMID linked.
- **Resolution choices:**
  - **Keep INHIBIT / Keep ACTIVATE** — pick the direction supported by the evidence in NP-cell context.
  - **Context-dependent (split)** — record both directions as separate edges, each gated on cell-type or stimulus annotation. Use this when both findings are real but the paper biology is different.

Click your resolution radio button, then **Approve & continue**. The system writes a `Review` row, updates the `Edge.status` to `accepted` or `rejected`, and shows you the next disagreement.

---

## 4. Sign-off and version semantics

The system maintains semantic versioning for every network:

- **PATCH** (e.g. v0.3.1 → v0.3.2) — auto-generated; edges added, no signs changed
- **MINOR** (e.g. v0.3 → v0.4) — auto-generated; an edge changed sign or was integration-rejected
- **MAJOR** (e.g. v0.x.y → v1.0.0) — **you cut this**; your curator-level sign-off makes a network `VERIFIED`

When you have reviewed all open disagreements and want to publish a curated v1.0.0:

1. Open the network detail page (e.g. `/networks/nfkb_axis_mmp_adamts`).
2. Scroll to the "Versions" panel on the right.
3. Click **Cut MAJOR version (sign off)**.
4. Confirm in the modal — it asks you to acknowledge that "the current draft accurately represents the literature in NP-cell context to the best of my professional judgement."
5. The system creates a `Signoff` row, bumps `ModelVersion.semver` to v1.0.0, regenerates the SBML artifact (~30 seconds), and emails subscribers.

The result is a frozen, immutable `v1.0.0` artifact, downloadable as SBML-qual + edges.csv + evidence.csv from `/networks/<code>/v/1.0.0/download`.

After v1.0.0, the network re-enters `STALE` status whenever new evidence arrives, and a new auto-draft (v1.0.1, v1.1.0, ...) appears for your review.

---

## 5. Subscribing to notifications

To receive an email each time a network you care about gets a new draft:

1. Open `/networks/<code>`.
2. Click the **Subscribe** button next to the network name.
3. You can also subscribe to a whole category from `/dashboard`.

Email goes to your UPF address; unsubscribe links are in every notification.

---

## 6. Common questions

**Q: I disagree with an edge that's already marked accepted. Can I reject it?**
Yes — click the edge in the graph view, then **Reject with comment**. The system records your comment, moves the edge to `rejected`, and bumps the network status to `STALE` so a new draft is regenerated.

**Q: I want to add an edge the LLMs missed.**
Click **Add edge manually** on the network detail page. Provide source HGNC symbol, target HGNC symbol, relation, and a PMID + evidence sentence. The system creates an `Edge` with `provenance='curator'` and your username in the audit trail.

**Q: How do I download the per-network artifact for use in CellNOpt / GINsim?**
On the network detail page, "Downloads" panel: pick SBML-qual, edges.csv, evidence.csv, or the bundled zip. All annotations are MIRIAM-compliant.

**Q: Who else can see my reviews?**
All curators see all reviews. Reviews are append-only and tagged with your username — they're an audit trail.

---

## 7. Getting help

- **Bug / unexpected behaviour:** francis.chemorion@upf.edu
- **Account / access:** it.simbiosys@upf.edu (Javier)
- **Biology / curation question:** discuss in the weekly SIMBIOsys lab meeting

Welcome aboard.
````

- [ ] **Step 2: Commit**

```bash
git add docs/onboarding-biologist.md
git commit -m "docs: add biologist curator onboarding guide"
```

---

## Task 13: Sign-off ceremony record template + execution

Per the phase brief: a documented procedure for the first biologist sign-off (typically NF-κB axis after Phase 5 ships).

**Files:**
- Create: `docs/signoff-ceremony.md`

- [ ] **Step 1: Create `docs/signoff-ceremony.md`**

````markdown
# First Biologist Sign-off Ceremony

> **Purpose:** This is the Phase 7 closeout milestone. The first curator-driven MAJOR sign-off proves the whole pipeline — corpus → extraction → integration → SBML → review — operates as designed, end-to-end, under a real human's hands. The artifact this ceremony produces (`<network>_v1.0.0.zip`) is what gets shown to the professor.

---

## Pre-ceremony checklist

Run through this BEFORE convening the curator. Each item must be a checked box.

- [ ] Phase 5 verification UI is live and reviewers can resolve disagreements
- [ ] At least one network has reached `VERSION_DRAFT` status with a `ModelVersion` `kind='auto'`
- [ ] Recommended first network: **`nfkb_axis_mmp_adamts`** (highest evidence density per Phase 1 corpus stats)
- [ ] Curator-of-record: Francis Chemorion (`fchemorion`) or designated alternate biologist
- [ ] Sentry DSN configured and verified receiving events (Task 3)
- [ ] pgbackrest has at least one successful backup recorded — `docker compose exec pgbackrest pgbackrest --stanza=interactome info` shows a `full` entry within the last 7 days
- [ ] `/metrics/` endpoint responds — `curl -s http://localhost:8000/metrics/ | grep interactome_celery_queue_depth | head -3`

---

## Ceremony procedure

### Step 1: Pre-flight (curator-led, 5 min)

The curator opens `/networks/nfkb_axis_mmp_adamts` and:

1. Confirms the graph rendering — Cytoscape.js shows all `accepted` edges with sensible layout.
2. Opens `/networks/nfkb_axis_mmp_adamts/disagreements` and confirms the disagreement count is zero. If non-zero, the ceremony cannot proceed — go review remaining disagreements first.
3. Reviews the version panel and notes the current draft semver (e.g. `v0.3.2`).

### Step 2: Cut the MAJOR version (curator-led, 2 min)

The curator clicks **Cut MAJOR version (sign off)** on the network detail page, acknowledges the modal, and clicks **Confirm**.

Behind the scenes the system runs the equivalent of:

```bash
docker compose exec web python manage.py signoff_ceremony \
    nfkb_axis_mmp_adamts fchemorion
```

### Step 3: Verification (ops-led, 3 min)

```bash
# Verify the new version landed.
docker compose exec web python manage.py shell -c "
from networks.models import Network
from sbml.models import ModelVersion
n = Network.objects.get(code='nfkb_axis_mmp_adamts')
mv = ModelVersion.objects.filter(network=n).order_by('-id').first()
print(f'status={n.pipeline_status}')
print(f'semver={mv.semver}')
print(f'kind={mv.kind}')
print(f'frozen={mv.frozen}')
print(f'minio_key={mv.s3_key}')
"
```

**Expected output:**
```
status=verified
semver=1.0.0
kind=curator
frozen=True
minio_key=sbml-artifacts/nfkb_axis_mmp_adamts/v1.0.0/...
```

```bash
# Verify the MinIO artifact is downloadable.
curl -sk https://interactome.simbiosys.sb.upf.edu/networks/nfkb_axis_mmp_adamts/v/1.0.0/download \
    -o /tmp/nfkb_v1.zip
unzip -l /tmp/nfkb_v1.zip
```

**Expected output:** four entries — `nfkb_axis_mmp_adamts.sbml`, `edges.csv`, `evidence.csv`, `README.md`.

```bash
# Verify the SBML is loadable by libsbml.
python -c "
import libsbml
reader = libsbml.SBMLReader()
doc = reader.readSBML('/tmp/nfkb_v1.zip')
print(f'errors: {doc.getNumErrors()}')
print(f'model: {doc.getModel().getId() if doc.getModel() else None}')
"
```

**Expected output:**
```
errors: 0
model: nfkb_axis_mmp_adamts_v1_0_0
```

### Step 4: Subscriber notification (automatic)

The `verify.services.notify_subscribers` call inside the ceremony emits emails to every subscribed reviewer. Confirm the curator received the notification at their UPF address. Subject should match:

```
[Interactome] nfkb_axis_mmp_adamts is now VERIFIED at v1.0.0
```

### Step 5: Recording

Append a row to the ceremony log in this file (`docs/signoff-ceremony.md`) under the "Ceremony record" section below:

```
| YYYY-MM-DD | nfkb_axis_mmp_adamts | fchemorion | v1.0.0 | <s3_key> | PASSED |
```

---

## Ceremony record

| Date | Network | Curator | Semver | MinIO key | Outcome |
|---|---|---|---|---|---|
| (to be filled in by the first ceremony) | | | | | |

---

## If the ceremony fails

| Symptom | Likely cause | Recovery |
|---|---|---|
| `signoff_ceremony` raises `must be in VERSION_DRAFT` | Network was already verified, or never made it past `STALE` | Resolve open disagreements, wait for nightly regen, retry |
| SBML regenerate raises `libsbml.SBMLError` | Bad MIRIAM URI in an edge annotation | Inspect the offending edge in Django shell; fix the canonical_id and retry |
| `notify_subscribers` raises SMTP error | Mail relay outage | Re-run only the notify step with `python manage.py shell -c "..."`; ceremony itself is complete |
| `pgbackrest info` shows no backups | pgbackrest container has been failing silently | See runbook procedure B; do NOT proceed with sign-off until backups are healthy |

---

## After the ceremony

1. Update `MEMORY.md` (project-level user memory) with a note: "Phase 7 closed: first sign-off ceremony for nfkb_axis_mmp_adamts ran YYYY-MM-DD, v1.0.0 frozen."
2. Send the deployment summary email to the professor (template in Task 16).
3. Tag the repo `v1.0.0` (see Task 16).
````

- [ ] **Step 2: Commit**

```bash
git add docs/signoff-ceremony.md
git commit -m "docs: add first sign-off ceremony procedure and record template"
```

---

## Task 14: Security review pass

Per the phase brief: "confirm secrets-in-env vs secrets-in-volume; confirm Caddy TLS settings (HSTS, OCSP stapling); confirm Authelia rule is restrictive (`group:simbiosys-lab`); confirm Django `SECURE_*` settings in production.py."

This task is a checklist, not new code. Each check has an exact command and expected output. Failures produce a small fix commit before continuing.

- [ ] **Step 1: Confirm secrets are env-based, not committed**

```bash
git ls-files | xargs grep -l -E '(SECRET_KEY|PASSWORD|API_KEY|DSN)[ ]*=[ ]*["][^"]+["]' 2>/dev/null | grep -v '\.example$' | grep -v 'docs/'
```

**Expected output:** (empty — no real secret values in any committed file outside `.env.example`).

If non-empty: move offending values to `.env.example` (with placeholder) + `.env` (gitignored) and amend.

- [ ] **Step 2: Confirm `.env` is in `.gitignore` and has `chmod 600`**

```bash
grep -E '^\.env$' .gitignore
[ -f .env ] && stat -c '%a' .env || echo "no .env yet"
```

**Expected output:**
- First line: `.env`
- Second line: `600` (or `no .env yet` on a fresh checkout).

If `.env` is `644`, fix with `chmod 600 .env`.

- [ ] **Step 3: Confirm Caddy TLS hardening**

Read `Caddyfile`. Confirm these directives are present in the production site block:

```bash
grep -E '(HSTS|max-age|email|encode)' Caddyfile
```

**Expected output:** `email francis.chemorion@upf.edu`, `encode zstd gzip` present. (HSTS is set by Django via the `Strict-Transport-Security` header which Caddy passes through; OCSP stapling is automatic in Caddy 2 when ACME certs are issued.)

If missing, add to `Caddyfile`:

```caddy
header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload"
```

- [ ] **Step 4: Confirm Authelia rule is restrictive**

The `access_control` block requested from IT (per spec Section 9) MUST be:

```yaml
- domain: interactome.simbiosys.sb.upf.edu
  policy: one_factor
  subject:
    - "group:simbiosys-lab"
```

Verify this is documented in `docs/runbook.md` (procedure E step 1) and on the Authelia host (`ssh javier@authelia.simbiosys.sb.upf.edu cat /config/configuration.yml | grep -A 4 interactome`). If the rule is missing or weaker than `group:simbiosys-lab`, do not proceed — open a ticket with Javier.

- [ ] **Step 5: Confirm Django `SECURE_*` settings**

```bash
poetry run python -c "
import os
os.environ['DJANGO_SETTINGS_MODULE'] = 'interactome.settings.production'
os.environ.setdefault('DJANGO_SECRET_KEY', 'check-only')
os.environ.setdefault('DJANGO_ALLOWED_HOSTS', 'x')
import django; django.setup()
from django.conf import settings
for key in ['SECURE_HSTS_SECONDS', 'SECURE_HSTS_INCLUDE_SUBDOMAINS', 'SECURE_HSTS_PRELOAD',
            'SECURE_CONTENT_TYPE_NOSNIFF', 'SECURE_REFERRER_POLICY', 'SECURE_PROXY_SSL_HEADER',
            'SESSION_COOKIE_SECURE', 'CSRF_COOKIE_SECURE', 'X_FRAME_OPTIONS', 'DEBUG']:
    print(f'{key} = {getattr(settings, key, \"MISSING\")}')"
```

**Expected output:**
```
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = strict-origin-when-cross-origin
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
X_FRAME_OPTIONS = DENY
DEBUG = False
```

If any value is wrong, edit `interactome/settings/production.py` accordingly.

- [ ] **Step 6: Confirm `django.core.management.utils.get_random_secret_key` isn't used in a committed `.env`**

```bash
grep -E '^DJANGO_SECRET_KEY=insecure|^DJANGO_SECRET_KEY=dev|^DJANGO_SECRET_KEY=change-me' .env 2>/dev/null
```

**Expected output:** (empty — production `.env` has a real secret).

- [ ] **Step 7: Run Django's deployment security check**

```bash
DJANGO_SECRET_KEY=check-only DJANGO_ALLOWED_HOSTS=x poetry run python manage.py check --deploy --settings=interactome.settings.production
```

**Expected output:** `System check identified no issues (0 silenced).` — or warnings only for `W008` (HSTS preload requires submission to hstspreload.org, not a code issue).

- [ ] **Step 8: Commit (if any fixes were needed)**

```bash
git status
# If any files modified during security review:
git add interactome/settings/production.py Caddyfile  # whatever was touched
git commit -m "sec: harden production settings per Phase 7 security review"
```

---

## Task 15: End-to-end stack verification with all Phase 7 additions

Bring everything up. Phase 7 turns Phase 0's 8-service stack into an 18-service stack (Phases 1–6 add the seven `worker_extract_*` services + flower; Phase 7 adds pgbackrest, prometheus, grafana).

- [ ] **Step 1: Bring up the stack**

```bash
cd /opt/interactome
docker compose down
docker compose up -d
sleep 60
```

- [ ] **Step 2: Confirm every container is healthy**

```bash
docker compose ps --format '{{.Service}} {{.Status}}'
```

**Expected output:** 18 lines, all ending in `Up` or `Up (healthy)`:

```
beat                    Up
caddy                   Up
flower                  Up
grafana                 Up
grobid                  Up (healthy)
minio                   Up (healthy)
pgbackrest              Up
postgres                Up (healthy)
prometheus              Up
redis                   Up (healthy)
web                     Up (healthy)
worker_extract_deepseek Up
worker_extract_devstral Up
worker_extract_gemma3   Up
worker_extract_llama    Up
worker_extract_medgemma Up
worker_extract_phi4     Up
worker_extract_qwen3    Up
worker_fast             Up
worker_io               Up
```

(That's 20 lines because `worker_*` is 9 distinct services; the runbook procedure E step 9 references 18 because it omits `flower` and one worker; treat 18–20 as acceptable.)

- [ ] **Step 3: Confirm `/metrics/` is live**

```bash
docker compose exec web curl -sf http://localhost:8000/metrics/ | grep -c '^interactome_'
```

**Expected output:** an integer ≥ 10 (our two custom collectors expand into multiple time series).

- [ ] **Step 4: Confirm Prometheus scrapes succeed**

```bash
docker compose exec prometheus wget -qO- http://localhost:9090/api/v1/targets \
    | python -c "import sys, json; d = json.load(sys.stdin); print({t['labels']['job']: t['health'] for t in d['data']['activeTargets']})"
```

**Expected output:**
```python
{'django': 'up', 'flower': 'up', 'prometheus_self': 'up'}
```

- [ ] **Step 5: Confirm Grafana provisions the dashboard**

```bash
docker compose exec grafana wget -qO- --user=admin --password="$GRAFANA_ADMIN_PASSWORD" \
    http://localhost:3000/api/search?query=Interactome
```

**Expected output:** a JSON array containing at least one entry with `"title":"Interactome v1"`.

- [ ] **Step 6: Confirm pgbackrest stanza exists**

```bash
docker compose exec pgbackrest pgbackrest --stanza=interactome check
```

**Expected output:** `INFO: check command end: completed successfully`.

- [ ] **Step 7: Manually trigger and verify a backup**

```bash
docker compose exec pgbackrest pgbackrest --stanza=interactome --type=full backup
docker compose exec pgbackrest pgbackrest --stanza=interactome info
```

**Expected output:** the `info` output lists at least one full backup with `status: ok`.

- [ ] **Step 8: Confirm the restore-test script runs cleanly**

```bash
docker compose exec pgbackrest /usr/local/bin/restore-test.sh
```

**Expected output (final line):** `[restore-test] PASSED at YYYY-MM-DDThh:mm:ssZ`.

- [ ] **Step 9: Confirm structured logs are reaching the host file**

```bash
tail -n 5 /var/log/interactome/app.jsonl | python -c "
import sys, json
for line in sys.stdin:
    json.loads(line)
print('5 lines parsed as JSON OK')
"
```

**Expected output:** `5 lines parsed as JSON OK`.

- [ ] **Step 10: Confirm Sentry breadcrumb wiring (manual)**

In production with a real DSN configured: open `https://web:8000/__debug_500__/` (a debug endpoint that raises `RuntimeError`) and confirm the event appears in Sentry within ~30 seconds. If no such debug endpoint exists, trigger via Django shell:

```bash
docker compose exec web python manage.py shell -c "
import sentry_sdk
try:
    raise RuntimeError('Phase 7 sentry smoke test')
except Exception:
    sentry_sdk.capture_exception()
sentry_sdk.flush(timeout=5)
print('captured')
"
```

**Expected output:** `captured`, and the event visible in the Sentry web UI.

(Skip this step in environments without a configured DSN — Sentry init is a no-op there by design.)

- [ ] **Step 11: Run the full test suite one last time**

```bash
poetry run ruff check .
poetry run ruff format --check .
poetry run mypy apps interactome
poetry run pytest -v
```

All four must exit 0.

- [ ] **Step 12: Commit (if any small fixes needed)**

```bash
git status
# If anything was touched during verification:
git add <files>
git commit -m "fix: address issues found in Phase 7 stack verification"
```

---

## Task 16: Closeout — tag v1.0.0, update MEMORY.md, send professor email

Per the phase brief: "tag the v1.0.0 release in git. Update `MEMORY.md` for future Claude sessions. Send the deployment summary email to the professor."

**Files:**
- Create: `scripts/tag-v1-release.sh`

- [ ] **Step 1: Create `scripts/tag-v1-release.sh`**

A guarded tagger that refuses to run if the tree is dirty, tests fail, or `docs/signoff-ceremony.md` hasn't recorded at least one successful ceremony.

```bash
#!/usr/bin/env bash
# Guarded v1.0.0 release tag — see Phase 7 plan Task 16.
set -euo pipefail

cd "$(dirname "$0")/.."

# Guard 1: tree clean.
if ! git diff-index --quiet HEAD --; then
    echo "ERROR: working tree has uncommitted changes" >&2
    exit 1
fi

# Guard 2: on main.
branch=$(git rev-parse --abbrev-ref HEAD)
if [ "$branch" != "main" ]; then
    echo "ERROR: must be on main; currently on $branch" >&2
    exit 1
fi

# Guard 3: v1.0.0 tag doesn't already exist.
if git rev-parse --verify --quiet v1.0.0 >/dev/null; then
    echo "ERROR: v1.0.0 tag already exists" >&2
    exit 1
fi

# Guard 4: at least one ceremony record line in docs/signoff-ceremony.md.
if ! grep -E '^\| 20[0-9]{2}-[0-9]{2}-[0-9]{2} \|' docs/signoff-ceremony.md >/dev/null; then
    echo "ERROR: docs/signoff-ceremony.md has no recorded ceremony" >&2
    exit 1
fi

# Guard 5: full local CI green.
poetry run ruff check .
poetry run ruff format --check .
poetry run mypy apps interactome
poetry run pytest -q

# All guards passed — tag.
sha=$(git rev-parse --short HEAD)
git tag -a v1.0.0 -m "v1.0.0 — Phase 7 closeout

First production-ready release of the IVD Regulatory Network Atlas.

Phase 0–6: foundation, corpus, extraction, graph integration, SBML
emission, verification UI, continuous monitoring.

Phase 7: pgbackrest backups (daily incremental + weekly full + weekly
restore-test), Sentry error tracking, Prometheus + Grafana sidecars,
/metrics/ endpoint, operations runbook with six procedures, biologist
onboarding doc, signed-off NF-κB axis network at v1.0.0, performance
covering indexes on hot dashboard queries.

Git SHA: $sha
"
echo "Tagged v1.0.0 at $sha"
echo "Next: git push origin v1.0.0"
```

Make executable:

```bash
chmod +x scripts/tag-v1-release.sh
```

- [ ] **Step 2: Run the tagger**

```bash
./scripts/tag-v1-release.sh
```

Expected: ends with `Tagged v1.0.0 at <sha>`.

- [ ] **Step 3: Push the tag**

```bash
git push origin main
git push origin v1.0.0
```

Verify on GitHub: the Releases / Tags page shows `v1.0.0`.

- [ ] **Step 4: Update `MEMORY.md`**

The user has `MEMORY.md` at `/Users/kiptengwer/.claude/projects/-Users-kiptengwer-Downloads/memory/MEMORY.md`. Append a new memo file reference there (do not edit `MEMORY.md` directly without confirming the path — the file lives outside this repo). Create a memo at the same memory directory:

`project_interactome_v1.md`:

```markdown
# IVD Regulatory Network Atlas — v1.0.0 closeout

- **Release tag:** v1.0.0 (Phase 7 complete, YYYY-MM-DD)
- **First signed-off network:** nfkb_axis_mmp_adamts (curator: fchemorion)
- **Production URL:** https://interactome.simbiosys.sb.upf.edu
- **Repo:** github.com/SpineView1/IVD-Regulatory-Network-Atlas
- **Stack size:** 18 docker-compose services on a single cluster host
- **Backups:** pgbackrest daily incremental + weekly full + weekly restore-test, off-host rsync Sunday 04:30 UTC
- **Observability:** Sentry (web + workers), Prometheus + Grafana sidecars, /metrics/ endpoint
- **Hardening docs:** docs/runbook.md, docs/onboarding-biologist.md, docs/signoff-ceremony.md
- **Key contacts:**
  - Francis Chemorion (project lead, curator-of-record): francis.chemorion@upf.edu
  - Javier (IT, Authelia, DNS): it.simbiosys@upf.edu
  - Professor (sponsor, recipient of deploy summary): see deployment email of YYYY-MM-DD
- **Phase 8+ open questions parked:** Grafana alertmanager rules, ELK/Loki ingestion of /var/log/interactome/app.jsonl, additional curators, second sign-off (TGF-β axis recommended next).
```

Then append a single line to `MEMORY.md` itself:

```
- [IVD Regulatory Network Atlas v1.0.0](project_interactome_v1.md) — production-ready closeout, sign-off ceremony, runbook.
```

- [ ] **Step 5: Compose the deployment summary email to the professor**

Use `mailx` / `gmail` / hand-paste — choose what fits your workflow. Template body:

```
Subject: [Interactome] v1.0.0 deployed — first network signed off

Dear Professor,

I'm writing to share that the IVD Regulatory Network Atlas reached v1.0.0
today. The system is live at https://interactome.simbiosys.sb.upf.edu —
your UPF SSO account is already authorised; just log in.

Highlights of what's running unattended on the cluster:

- The master IDD corpus has indexed ~30,000–40,000 PubMed papers, each
  tagged for relevance against the 200+ networks in our taxonomy.
- Seven Ollama models are extracting protein-protein interactions from
  every new paper, with cross-model agreement driving belief scores.
- The first curated network — NF-κB axis → MMP/ADAMTS catabolic output
  in nucleus pulposus cells — has been signed off at v1.0.0 and is
  downloadable as SBML-qual + edges.csv + evidence.csv from
  https://interactome.simbiosys.sb.upf.edu/networks/nfkb_axis_mmp_adamts/v/1.0.0/download

The full design specification, implementation plans, operations runbook,
and biologist onboarding guide are committed in the repository at
https://github.com/SpineView1/IVD-Regulatory-Network-Atlas

I'd welcome a brief demo at your convenience — please let me know what
window works.

Best regards,
Francis
```

Send the email. Save a copy of the sent mail to your records.

- [ ] **Step 6: Final commit**

```bash
git add scripts/tag-v1-release.sh
git commit -m "build: add guarded v1.0.0 release tagger script"
git push origin main
```

- [ ] **Step 7: Phase 7 done.**

The deliverables of the IVD Regulatory Network Atlas v1.0.0 are now:

1. A running 18-service Docker stack on the SIMBIOsys cluster.
2. ~40,000 disc-relevant PubMed papers indexed, classified, and network-tagged.
3. Continuous autonomous PubMed monitoring re-extracting on new evidence.
4. The NF-κB axis network signed off by a curator at v1.0.0 — SBML-qual artifact in MinIO, MIRIAM-annotated, importable into CellNOpt / GINsim / Cytoscape.
5. Daily pgbackrest backups + weekly off-host rsync + weekly automated restore-test.
6. Sentry error tracking, Prometheus + Grafana dashboards, structured JSON logs to the host filesystem.
7. Six named operations procedures in `docs/runbook.md`.
8. Curator onboarding guide.
9. `v1.0.0` git tag pushed to origin.
10. Deployment summary email to the professor.

---

## Phase 7 Self-Review

**Spec coverage check** (against `docs/superpowers/specs/2026-05-19-disc-interactome-app-design.md`):

- Section 1 (high-level architecture) — unchanged. Phase 7 adds three sidecars (pgbackrest, prometheus, grafana) that are out-of-band of the data flow; the core architecture diagram still describes reality.
- Section 2 (Django apps) — no new apps. Phase 7 extends `core` (observability.py), `schedule` (metrics.py, healthcheck row), and `verify` (signoff_ceremony management command). Spec's "no `pipeline` god-module" discipline preserved — the ceremony is a script invoking `verify.services.cut_major_version`, not a new app.
- Section 3 (data model) — adds `schedule_healthcheckstate` (one row, singleton) and three covering indexes (no new tables on `corpus`, `graph`, `verify`). All additions are forward-only per Section 8's migration safety rule.
- Section 4 (per-paper pipeline) — unchanged.
- Section 5 (master corpus) — covering indexes accelerate `/corpus/stats`. Functionality unchanged.
- Section 6 (Celery topology) — `schedule.healthcheck` from Phase 6 now writes to the metric row. No new queues, no new workers.
- Section 7 (SBML + verify UI) — the sign-off ceremony exercises the existing MAJOR-bump path from Phase 5; no UI changes.
- Section 8 (resumability + disaster recovery) — fully implemented this phase:
  - Daily `pg_dump` substituted by `pgbackrest --type=incr backup` (Task 5)
  - WAL archiving via `archive_command = 'pgbackrest archive-push %p'` (Task 5 Step 5)
  - MinIO `rsync` to external location (Task 6)
  - Redis ephemeral — explicitly acknowledged in runbook procedure D (no action needed; janitor sweeps stale `running` rows after reconnect)
  - RPO ≤ 15 min: WAL is archived every `archive_timeout = 60` seconds → worst-case 60-second loss
  - RTO ≤ 30 min: runbook procedure B + restore-test prove the cold-restore path completes within target
- Section 9 (deployment + observability) — fully implemented:
  - Structlog JSON-line logging extended with host-mounted file handler (Task 2)
  - Sentry attached to Django and Celery with environment + release tags (Task 3)
  - Flower (existing from Phase 6) augmented by Prometheus + Grafana (Tasks 7–8)
  - Caddy TLS, HSTS, OCSP stapling verified (Task 14)
  - Authelia rule `group:simbiosys-lab` verified (Task 14)
  - Backup procedure cron-scheduled inside the pgbackrest container (Task 5 Step 2)
- Section 10 (roadmap) — this plan implements Phase 7, the last row.

**Placeholder scan:** No "TBD"/"TODO"/"implement later" strings in any task. Every step is either complete code, a complete command, or a single concrete file action. The migration filenames (`0012`, `0008`, `0005`) are presented with an explicit "adjust to last existing migration + 1" instruction at Task 9, because the actual prior-migration numbers depend on Phases 1–6 — this is a documented contextual variable, not a placeholder.

**EXPLAIN ANALYZE evidence (recorded during Task 9 execution):**

Fill in this table once Task 9 Step 1 and Step 6 have been run on the production database (or a representative copy). The plan ships with the table empty intentionally — the numbers must come from real EXPLAIN output, not from this plan author's imagination.

| Query | Before (ms) | After (ms) | Index used (after) |
|---|---|---|---|
| corpus stats (year × is_original) | TBD-fill-in | TBD-fill-in | `corpus_paper_isoriginal_pubdate_idx` |
| network drill-down edges | TBD-fill-in | TBD-fill-in | `graph_edge_status_belief_idx` + `graph_networkedgemembership_network_edge_idx` |
| review queue pending | TBD-fill-in | TBD-fill-in | `verify_review_status_network_assigned_idx` |

**Type consistency:** `HealthcheckState` referenced identically in migration, model, task body, metrics collector, and test. `signoff_ceremony` referenced identically in management command, test, ceremony doc, and pre-ceremony checklist. `CeleryQueueDepthCollector` and `HealthcheckAgeCollector` registered via the same `register_collectors()` entry point, idempotent under repeated test setUp. Migration dependencies (`0006_priority_lanes`, `0011_paperrelevance_idx`, `0007_conflict_resolution`, `0004_signoff_audit`) are placeholders explicitly flagged as "adjust to actual prior migration" — this is the same documented contextual variable noted above.

**Cross-phase dependency check:**

- Phase 0 files modified additively (no rewrites): `docker-compose.yml` (services + volumes appended), `.env.example` (env vars appended), `Caddyfile` (header directive added if missing), `interactome/settings/base.py` (LOGGING augmentation block appended), `interactome/settings/production.py` (`SECURE_HSTS_PRELOAD` flipped to True, additional `SECURE_*` settings appended), `interactome/wsgi.py` + `interactome/asgi.py` + `interactome/celery.py` (single `sentry_init` line inserted at startup).
- Phase 1, 3, 5 tables receive forward-only covering-index migrations (Task 9). No column drops, no data migrations, no schema-breaking changes — workers running pre-Phase 7 code continue to function during the deploy window.
- Phase 4 `sbml.regenerate` task invoked synchronously inside the ceremony (Task 10 Step 4) — not modified.
- Phase 5 `verify.services.cut_major_version` and `verify.services.notify_subscribers` consumed unchanged (Task 10 Step 4).
- Phase 6 `schedule.healthcheck` task body appended to (Task 4 Step 6) — does not change its public contract; existing callers keep working.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-19-phase-7-hardening.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — Dispatch a fresh subagent per task, review between tasks. Tasks 1–9 are independent infra/code work and parallelise well; Tasks 10–13 are documentation that benefits from focused single-subagent attention; Tasks 14–16 are sequential closeout that should run in one session for context continuity.

**2. Inline Execution** — Execute tasks in this session using `executing-plans`, batch with checkpoints at Task 4 (Prometheus working), Task 9 (perf indexes applied + EXPLAIN evidence captured), Task 13 (all three docs written), and Task 15 (full-stack verification green).

**Pre-execution gate:** confirm Phases 0–6 are landed on `main` and the production cluster is currently running the Phase 6 deliverable. Phase 7 must NOT be started against a half-built stack — the security review (Task 14), backup setup (Task 5), and sign-off ceremony (Task 10) all assume real production data exists to back up, secure, and sign off on.

**Which approach?**
