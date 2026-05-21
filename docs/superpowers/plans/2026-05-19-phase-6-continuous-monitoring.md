# Phase 6: Continuous Monitoring — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the already-built Phase 1–5 components into a continuously-running loop. After Phase 6, the system runs unattended: PubMed deltas arrive hourly, affected networks are marked stale, conflicts are auto-resolved when models agree, subscribers are notified, backpressure prevents queue overflow, and a global pause switch is available for ops. End state: a synthetic Paper inserted at one end of the pipeline propagates all the way to a notification email at the other end with zero human intervention.

**Architecture:** Phase 6 is glue, not new architecture. It adds three things on top of the existing apps: (1) a new internal app `monitoring` that owns health checks, the global ingestion-paused feature flag, and the admin pause/resume UI; (2) a new `conflict.auto_resolve` task and Beat sweeper in the existing `verify` app; (3) a delta-detection task `graph.detect_affected_networks` in the existing `graph` app that runs on the Celery `paper_ingested` signal. Beat schedule grows by four entries; no new Celery queues, no new worker processes — auto-resolve runs on the existing `q.extract.medgemma_27b` queue (re-uses the hot model), health checks and pause-flag reads run on `q.io`. Subscription notifications layer on top of `verify.notify` from Phase 5.

**Tech Stack:** Same as prior phases — Python 3.12, Django 5.0, Celery 5.3, django-celery-beat 2.6, PostgreSQL 16, Redis 7. No new third-party libraries.

**Reference spec:** `docs/superpowers/specs/2026-05-19-disc-interactome-app-design.md` Sections 1 (architectural invariants — "continuous service" runtime mode), 4 (per-paper pipeline — STALE network propagation), 6 (Celery topology, Beat schedule), 8 (resumability — janitor patterns extended to monitoring), and 10 (Phase 6 row).

**Phase dependencies:** This plan assumes Phases 1–5 are merged and operational:
- Phase 1: `corpus.refresh_pubmed`, `Paper`/`PaperRelevance` models, per-network triage exist.
- Phase 2: `extract.enqueue_pending_chunks`, `ExtractionRun`, `RawPPI` exist.
- Phase 3: `graph.integrate_pending`, `NetworkEdgeMembership`, `Conflict` exist.
- Phase 4: `sbml.regenerate_stale_networks`, `ModelVersion` exist; Network status state machine.
- Phase 5: `verify.dispatch_review_assignments`, `verify.notify`, `Subscription`, `Review` exist.

---

## File Structure After Phase 6

```
/                                       (git repo root)
└── apps/
    ├── monitoring/                     NEW app — health checks, pause flag, admin UI
    │   ├── __init__.py
    │   ├── apps.py                     MonitoringConfig
    │   ├── models.py                   HealthAlert, FeatureFlag
    │   ├── services.py                 is_ingestion_paused(), set_ingestion_paused(), queue_depth()
    │   ├── tasks.py                    schedule.healthcheck, monitoring.notify_admins
    │   ├── views.py                    admin pause/resume button view
    │   ├── urls.py                     /admin/monitoring/pause/, /admin/monitoring/resume/
    │   ├── templates/monitoring/
    │   │   └── pause_panel.html        HTMX panel for the dashboard nav
    │   ├── migrations/
    │   │   ├── __init__.py
    │   │   └── 0001_initial.py         HealthAlert + FeatureFlag tables
    │   └── tests/
    │       ├── __init__.py
    │       ├── test_services.py        pause flag round-trip, queue_depth math
    │       ├── test_healthcheck.py     healthcheck task asserts thresholds
    │       ├── test_views.py           pause/resume HTTP endpoint
    │       └── test_backpressure.py    refresh_pubmed short-circuits when paused
    ├── graph/                          MODIFIED — add delta-detection task
    │   ├── tasks.py                    + detect_affected_networks(paper_id)
    │   ├── services.py                 + affected_network_ids(paper_id)
    │   └── tests/
    │       └── test_detect_affected.py NEW test file
    ├── verify/                         MODIFIED — auto-resolver + subscription notifications
    │   ├── tasks.py                    + conflict.auto_resolve, + verify.notify_subscribers_stale,
    │   │                                + verify.notify_subscribers_daily_digest,
    │   │                                + verify.sweep_open_conflicts
    │   ├── prompts.py                  + CONFLICT_REREAD_PROMPT, CONFLICT_REREAD_SCHEMA
    │   ├── services.py                 + notify_for_state_transition(),
    │   │                                + queue_subscribers_for_disagreements()
    │   └── tests/
    │       ├── test_auto_resolve.py    NEW — auto_resolve mocked-LLM round-trip
    │       ├── test_subscription_notify.py NEW
    │       └── test_disagreement_digest.py NEW
    ├── corpus/                         MODIFIED — emit paper_ingested signal, honour pause flag
    │   ├── signals.py                  NEW — paper_ingested signal definition
    │   ├── tasks.py                    refresh_pubmed: short-circuit on pause flag,
    │   │                                ingest_paper: fires paper_ingested signal
    │   └── tests/
    │       └── test_paper_ingested_signal.py NEW
    ├── extract/                        MODIFIED — honour pause flag
    │   └── tasks.py                    enqueue_pending_chunks: short-circuit on pause flag,
    │                                    plus backpressure threshold check
    ├── schedule/                       MODIFIED — Beat schedule grows by 4 entries
    │   ├── beat_schedule.py            + 4 new entries (see Task 9)
    │   └── tests/
    │       └── test_beat_schedule.py   + assertions for new entries
    └── dashboard/                      MODIFIED — pause panel + health alerts widget
        ├── templates/dashboard/
        │   ├── base.html               + include monitoring/pause_panel.html
        │   └── partials/
        │       └── health_alerts.html  HTMX-polled alert list
        ├── views.py                    + health_alerts_panel view
        └── urls.py                     + /dashboard/health-alerts/

tests/
└── integration/
    └── test_new_paper_end_to_end.py    NEW — synthetic Paper → notification chain
```

**Why this layout:**
- A dedicated `monitoring` app (not a sub-module of `schedule`) because health alerts and feature flags need their own models, views, templates, and admin URLs. Per the spec's boundary discipline (Section 2), giving them their own app keeps `schedule` focused on cron/beat/rate-limit concerns and avoids growing it into a god-module.
- The auto-resolver lives in `verify` (not `graph`) because it is a *review action* — the LLM is performing the work a curator would otherwise do. `verify` already owns `Conflict` resolution semantics via `Review`/`Signoff`. Reusing the existing review audit trail is cheaper than inventing new tables.
- Delta detection (`graph.detect_affected_networks`) lives in `graph` because it touches `NetworkEdgeMembership` — that's `graph`'s table.
- The integration test lives in `tests/integration/` (not `apps/*/tests/`) because it spans 5 apps. App-local tests stay in `apps/<app>/tests/`.

---

## Task 1: Scaffold the `monitoring` app

The spec (Section 9) lists Sentry/Flower/Grafana as deferred to v2; for v1 we need in-app health monitoring that writes Postgres rows so the cluster's existing alerting can scrape them.

**Files:**
- Create: `apps/monitoring/__init__.py`
- Create: `apps/monitoring/apps.py`
- Create: `apps/monitoring/models.py`
- Create: `apps/monitoring/services.py`
- Create: `apps/monitoring/tasks.py`
- Create: `apps/monitoring/views.py`
- Create: `apps/monitoring/urls.py`
- Create: `apps/monitoring/templates/monitoring/pause_panel.html`
- Create: `apps/monitoring/migrations/__init__.py`
- Create: `apps/monitoring/tests/__init__.py`
- Modify: `interactome/settings/base.py` (add `"monitoring"` to `INSTALLED_APPS`)
- Modify: `interactome/urls.py` (include `monitoring.urls`)

- [ ] **Step 1: Create `apps/monitoring/__init__.py`**

```python
"""monitoring — health alerts, feature flags, admin pause/resume.

This app is the operational nervous system of the continuous-service
runtime. It owns three concerns:

1. ``HealthAlert`` — every health-check failure becomes one row, never
   updated, so the alert history is its own audit trail.
2. ``FeatureFlag`` — single-row global toggles read by Beat tasks
   before they fire (e.g. ``INGESTION_PAUSED``).
3. The pause/resume admin UI — two POST endpoints behind the curator
   role group, wired into the dashboard nav.

Depends on: ``core``. Depended on by: ``corpus``, ``extract``,
``schedule``, ``dashboard``.
"""
```

- [ ] **Step 2: Create `apps/monitoring/apps.py`**

```python
"""Django AppConfig for the monitoring app."""
from __future__ import annotations

from django.apps import AppConfig


class MonitoringConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "monitoring"
    verbose_name = "Monitoring (health + feature flags)"
```

- [ ] **Step 3: Create `apps/monitoring/migrations/__init__.py`** (empty file).

- [ ] **Step 4: Create `apps/monitoring/tests/__init__.py`** (empty file).

- [ ] **Step 5: Add `"monitoring"` to `INSTALLED_APPS` in `interactome/settings/base.py`**

Locate the `INSTALLED_APPS` list and append `"monitoring",` after the
last local app. The list should now read (showing only the local-apps tail):

```python
INSTALLED_APPS = [
    # ... django.contrib.* ...
    "django_celery_beat",
    "django_celery_results",
    # Local apps
    "core",
    "networks",
    "corpus",
    "papers",
    "extract",
    "graph",
    "sbml",
    "verify",
    "schedule",
    "dashboard",
    "monitoring",
]
```

- [ ] **Step 6: Include `monitoring.urls` in `interactome/urls.py`**

Add inside `urlpatterns`:

```python
    path("admin/monitoring/", include("monitoring.urls")),
```

- [ ] **Step 7: Verify Django still boots**

```bash
poetry run python manage.py check
```

Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 8: Commit**

```bash
git add apps/monitoring/__init__.py apps/monitoring/apps.py \
        apps/monitoring/migrations/__init__.py \
        apps/monitoring/tests/__init__.py \
        interactome/settings/base.py interactome/urls.py
git commit -m "feat(monitoring): scaffold monitoring app"
```

---

## Task 2: `HealthAlert` and `FeatureFlag` models (TDD)

Per spec Section 8, every persistent unit of state lives in Postgres. The
global pause switch and the health-alert history must therefore be DB
rows, not Redis keys or in-memory globals.

**Files:**
- Create: `apps/monitoring/tests/test_models.py`
- Modify: `apps/monitoring/models.py`

- [ ] **Step 1: Write the failing test in `apps/monitoring/tests/test_models.py`**

```python
"""Tests for monitoring.models."""
from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from monitoring.models import FeatureFlag, HealthAlert


def test_feature_flag_singleton_per_name(db):
    FeatureFlag.objects.create(name="INGESTION_PAUSED", value=False)
    with pytest.raises(Exception):  # IntegrityError, but stays portable
        FeatureFlag.objects.create(name="INGESTION_PAUSED", value=True)


def test_feature_flag_defaults_to_false(db):
    flag = FeatureFlag.objects.create(name="EXTRACT_PAUSED")
    assert flag.value is False


def test_feature_flag_records_change_metadata(db):
    flag = FeatureFlag.objects.create(name="INGESTION_PAUSED", value=False)
    flag.value = True
    flag.last_changed_by = "fchemorion"
    flag.last_changed_reason = "cluster maintenance"
    flag.save()
    flag.refresh_from_db()
    assert flag.last_changed_by == "fchemorion"
    assert flag.last_changed_reason == "cluster maintenance"


def test_healthalert_severity_choices(db):
    a = HealthAlert.objects.create(
        check_name="corpus.refresh_pubmed_stale",
        severity="error",
        message="No successful refresh in 3h",
    )
    assert a.severity == "error"


def test_healthalert_resolved_at_defaults_null(db):
    a = HealthAlert.objects.create(
        check_name="ollama_unreachable",
        severity="critical",
        message="Connection refused",
    )
    assert a.resolved_at is None
    assert a.is_open is True


def test_healthalert_mark_resolved(db):
    a = HealthAlert.objects.create(
        check_name="ollama_unreachable",
        severity="critical",
        message="Connection refused",
    )
    a.resolve(by="fchemorion", note="restarted ollama container")
    a.refresh_from_db()
    assert a.is_open is False
    assert a.resolved_at is not None
    assert (timezone.now() - a.resolved_at) < timedelta(seconds=5)
    assert a.resolved_by == "fchemorion"
    assert a.resolution_note == "restarted ollama container"


def test_healthalert_audit_trail_append_only(db):
    """Same check_name firing twice produces two rows, never an UPDATE."""
    HealthAlert.objects.create(check_name="x", severity="warning", message="m1")
    HealthAlert.objects.create(check_name="x", severity="warning", message="m2")
    assert HealthAlert.objects.filter(check_name="x").count() == 2
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
poetry run pytest apps/monitoring/tests/test_models.py -v
```

Expected: `ImportError: cannot import name 'FeatureFlag' from 'monitoring.models'`.

- [ ] **Step 3: Implement the models in `apps/monitoring/models.py`**

```python
"""monitoring models — HealthAlert and FeatureFlag.

Both tables are tiny (≤ hundreds of rows in steady state) and have no
foreign-key relationships outside this app. They are read by Beat tasks
on every tick, so primary-key lookups and a partial index on
``HealthAlert(is_open)`` are the only performance considerations.
"""
from __future__ import annotations

from django.db import models
from django.utils import timezone

from core.models import TimestampedModel


class FeatureFlag(TimestampedModel):
    """Single-row global toggle, keyed by ``name``.

    Beat tasks read ``FeatureFlag.objects.get(name='INGESTION_PAUSED').value``
    before doing real work. ``select_related`` is unnecessary; the row
    is cached in the worker memory by Django's query cache within a
    request/task.
    """

    name = models.CharField(max_length=64, unique=True)
    value = models.BooleanField(default=False)
    last_changed_by = models.CharField(max_length=150, blank=True, default="")
    last_changed_reason = models.TextField(blank=True, default="")

    class Meta:
        indexes = [models.Index(fields=["name"])]

    def __str__(self) -> str:
        return f"{self.name}={self.value}"


class HealthAlert(TimestampedModel):
    """One row per health-check failure. Append-only audit trail."""

    SEVERITY_CHOICES = [
        ("info", "Info"),
        ("warning", "Warning"),
        ("error", "Error"),
        ("critical", "Critical"),
    ]

    check_name = models.CharField(max_length=128, db_index=True)
    severity = models.CharField(max_length=16, choices=SEVERITY_CHOICES)
    message = models.TextField()
    context = models.JSONField(default=dict, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True, db_index=True)
    resolved_by = models.CharField(max_length=150, blank=True, default="")
    resolution_note = models.TextField(blank=True, default="")

    class Meta:
        indexes = [
            models.Index(
                fields=["check_name", "-created_at"],
                name="health_check_recent_idx",
            ),
        ]

    @property
    def is_open(self) -> bool:
        return self.resolved_at is None

    def resolve(self, *, by: str, note: str = "") -> None:
        self.resolved_at = timezone.now()
        self.resolved_by = by
        self.resolution_note = note
        self.save(update_fields=["resolved_at", "resolved_by", "resolution_note", "updated_at"])
```

- [ ] **Step 4: Generate the migration**

```bash
poetry run python manage.py makemigrations monitoring
```

Expected:
```
Migrations for 'monitoring':
  apps/monitoring/migrations/0001_initial.py
    - Create model FeatureFlag
    - Create model HealthAlert
```

- [ ] **Step 5: Run the migration in the test DB**

```bash
poetry run pytest apps/monitoring/tests/test_models.py -v --create-db
```

Expected: all 7 tests pass.

- [ ] **Step 6: Commit**

```bash
git add apps/monitoring/models.py apps/monitoring/migrations/0001_initial.py \
        apps/monitoring/tests/test_models.py
git commit -m "feat(monitoring): add FeatureFlag and HealthAlert models"
```

---

## Task 3: `monitoring.services` — pause flag + queue depth (TDD)

This is the public API of the `monitoring` app. Other apps call
`monitoring.services.is_ingestion_paused()` etc. They never touch the
`FeatureFlag` model directly — keeps the boundary clean per spec
Section 2.

**Files:**
- Create: `apps/monitoring/tests/test_services.py`
- Create: `apps/monitoring/services.py`

- [ ] **Step 1: Write the failing test in `apps/monitoring/tests/test_services.py`**

```python
"""Tests for monitoring.services."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from monitoring import services
from monitoring.models import FeatureFlag


@pytest.mark.django_db
class TestIngestionPauseFlag:
    def test_unset_flag_returns_false(self):
        assert services.is_ingestion_paused() is False

    def test_set_and_read_paused(self):
        services.set_ingestion_paused(True, by="fchemorion", reason="testing")
        assert services.is_ingestion_paused() is True

    def test_set_paused_persists_audit_info(self):
        services.set_ingestion_paused(True, by="fchemorion", reason="cluster maintenance")
        flag = FeatureFlag.objects.get(name="INGESTION_PAUSED")
        assert flag.last_changed_by == "fchemorion"
        assert flag.last_changed_reason == "cluster maintenance"

    def test_toggle_back_to_false(self):
        services.set_ingestion_paused(True, by="x", reason="y")
        services.set_ingestion_paused(False, by="x", reason="resumed")
        assert services.is_ingestion_paused() is False


@pytest.mark.django_db
class TestQueueDepth:
    @patch("monitoring.services._extract_queue_depth")
    def test_queue_depth_returns_int(self, mock_depth):
        mock_depth.return_value = 1234
        assert services.extract_queue_depth() == 1234

    @patch("monitoring.services._extract_queue_depth")
    def test_backpressure_at_threshold(self, mock_depth):
        mock_depth.return_value = 10_000
        assert services.is_backpressured(threshold=10_000) is True

    @patch("monitoring.services._extract_queue_depth")
    def test_below_threshold_no_backpressure(self, mock_depth):
        mock_depth.return_value = 9_999
        assert services.is_backpressured(threshold=10_000) is False
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
poetry run pytest apps/monitoring/tests/test_services.py -v
```

Expected: `ImportError: cannot import name 'is_ingestion_paused'`.

- [ ] **Step 3: Implement `apps/monitoring/services.py`**

```python
"""monitoring services — the public API of the monitoring app.

Other apps import from here, never from ``monitoring.models``.
"""
from __future__ import annotations

from django.db import transaction
from django.db.models import Count, Q

from monitoring.models import FeatureFlag

INGESTION_PAUSED_FLAG = "INGESTION_PAUSED"
DEFAULT_EXTRACT_BACKPRESSURE_THRESHOLD = 10_000


def is_ingestion_paused() -> bool:
    """Return True iff the global ``INGESTION_PAUSED`` flag is set.

    Cheap to call (one indexed Postgres lookup). Beat tasks call this
    on every tick before doing real work.
    """
    try:
        return FeatureFlag.objects.get(name=INGESTION_PAUSED_FLAG).value
    except FeatureFlag.DoesNotExist:
        return False


def set_ingestion_paused(value: bool, *, by: str, reason: str) -> None:
    """Atomically set the ``INGESTION_PAUSED`` flag with audit info."""
    with transaction.atomic():
        flag, _ = FeatureFlag.objects.select_for_update().get_or_create(
            name=INGESTION_PAUSED_FLAG,
            defaults={"value": False},
        )
        flag.value = value
        flag.last_changed_by = by
        flag.last_changed_reason = reason
        flag.save()


def _extract_queue_depth() -> int:
    """Count pending (Chunk × Model) extraction work.

    Implemented as a SQL aggregate over ``extract.ExtractionRun`` rows
    in ``status='queued'`` plus the chunks that have no ExtractionRun
    row yet for at least one active model.

    Separated into its own function so tests can mock it.
    """
    # Lazy import to keep monitoring.services free of cross-app DB-import cycles.
    from extract.models import ExtractionRun

    return (
        ExtractionRun.objects.filter(status__in=["queued", "running"]).count()
    )


def extract_queue_depth() -> int:
    """Public wrapper around the queue-depth probe."""
    return _extract_queue_depth()


def is_backpressured(threshold: int = DEFAULT_EXTRACT_BACKPRESSURE_THRESHOLD) -> bool:
    """Return True if the extraction queue is at or above ``threshold``.

    Called by ``corpus.refresh_pubmed`` before pulling new PMIDs from
    NCBI. If True, the refresh short-circuits this tick; PubMed metadata
    is incremental, so deferring one hour is safe.
    """
    return _extract_queue_depth() >= threshold
```

- [ ] **Step 4: Run the test to confirm it passes**

```bash
poetry run pytest apps/monitoring/tests/test_services.py -v
```

Expected: `9 passed`.

- [ ] **Step 5: Commit**

```bash
git add apps/monitoring/services.py apps/monitoring/tests/test_services.py
git commit -m "feat(monitoring): add pause flag and queue-depth services"
```

---

## Task 4: `schedule.healthcheck` periodic task (TDD)

Per spec Section 6 Beat schedule + spec Section 9 ("Logging and monitoring"),
the system needs in-process health verification because the Grafana/Prometheus
stack is deferred to v2. The check is cheap (one SQL count, one HTTP HEAD)
and runs every 15 min on `q.io`.

Checks performed:
- **(a)** `corpus.refresh_pubmed`'s last successful watermark advance < 2h ago
- **(b)** Ollama gateway returns 2xx on `GET /api/tags` within 5s
- **(c)** A `SELECT 1` round-trip completes in under 200 ms

Each failure is one new `HealthAlert` row.

**Files:**
- Create: `apps/monitoring/tests/test_healthcheck.py`
- Modify: `apps/monitoring/tasks.py`

- [ ] **Step 1: Create `apps/monitoring/tests/test_healthcheck.py`**

```python
"""Tests for monitoring.tasks.healthcheck."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from monitoring.models import HealthAlert
from monitoring.tasks import healthcheck


@pytest.fixture
def watermark_recent(db):
    from schedule.models import Watermark

    Watermark.objects.update_or_create(
        source="pubmed",
        defaults={"last_success_at": timezone.now() - timedelta(minutes=30)},
    )


@pytest.fixture
def watermark_stale(db):
    from schedule.models import Watermark

    Watermark.objects.update_or_create(
        source="pubmed",
        defaults={"last_success_at": timezone.now() - timedelta(hours=3)},
    )


@pytest.mark.django_db
class TestPubMedFreshnessCheck:
    @patch("monitoring.tasks._probe_ollama", return_value=True)
    @patch("monitoring.tasks._probe_postgres_latency", return_value=10.0)
    def test_recent_pubmed_emits_no_alert(self, _pg, _oll, watermark_recent):
        healthcheck()
        assert not HealthAlert.objects.filter(check_name="pubmed_refresh_stale").exists()

    @patch("monitoring.tasks._probe_ollama", return_value=True)
    @patch("monitoring.tasks._probe_postgres_latency", return_value=10.0)
    def test_stale_pubmed_emits_alert(self, _pg, _oll, watermark_stale):
        healthcheck()
        alerts = HealthAlert.objects.filter(check_name="pubmed_refresh_stale")
        assert alerts.count() == 1
        assert alerts.first().severity == "error"


@pytest.mark.django_db
class TestOllamaReachabilityCheck:
    @patch("monitoring.tasks._probe_ollama", return_value=False)
    @patch("monitoring.tasks._probe_postgres_latency", return_value=10.0)
    def test_ollama_unreachable_emits_critical_alert(self, _pg, _oll, watermark_recent):
        healthcheck()
        alerts = HealthAlert.objects.filter(check_name="ollama_unreachable")
        assert alerts.count() == 1
        assert alerts.first().severity == "critical"


@pytest.mark.django_db
class TestPostgresLatencyCheck:
    @patch("monitoring.tasks._probe_ollama", return_value=True)
    @patch("monitoring.tasks._probe_postgres_latency", return_value=350.0)
    def test_slow_postgres_emits_warning(self, _pg, _oll, watermark_recent):
        healthcheck()
        alerts = HealthAlert.objects.filter(check_name="postgres_slow")
        assert alerts.count() == 1
        assert alerts.first().severity == "warning"

    @patch("monitoring.tasks._probe_ollama", return_value=True)
    @patch("monitoring.tasks._probe_postgres_latency", return_value=50.0)
    def test_fast_postgres_emits_no_alert(self, _pg, _oll, watermark_recent):
        healthcheck()
        assert not HealthAlert.objects.filter(check_name="postgres_slow").exists()


@pytest.mark.django_db
class TestHealthcheckNotifiesAdmins:
    @patch("monitoring.tasks.notify_admins")
    @patch("monitoring.tasks._probe_ollama", return_value=False)
    @patch("monitoring.tasks._probe_postgres_latency", return_value=10.0)
    def test_critical_alert_triggers_admin_notification(
        self, _pg, _oll, mock_notify, watermark_recent
    ):
        healthcheck()
        assert mock_notify.called
        call_args = mock_notify.call_args[1]
        assert call_args["severity"] == "critical"
```

- [ ] **Step 2: Implement `apps/monitoring/tasks.py`**

```python
"""monitoring Celery tasks.

All tasks here run on the ``q.io`` queue (cheap HTTP + Postgres). The
``healthcheck`` task is Beat-scheduled every 15 min (see
``schedule.beat_schedule``).
"""
from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Iterable

import requests
from celery import shared_task
from django.conf import settings
from django.db import connection
from django.utils import timezone

from monitoring.models import HealthAlert

logger = logging.getLogger(__name__)

PUBMED_FRESHNESS_THRESHOLD_HOURS = 2
POSTGRES_LATENCY_WARN_MS = 200.0
OLLAMA_PROBE_TIMEOUT_SECONDS = 5.0


def _probe_ollama() -> bool:
    """Return True if Ollama gateway responds 2xx to /api/tags."""
    url = f"{settings.OLLAMA_BASE.rstrip('/')}/api/tags"
    try:
        r = requests.get(url, timeout=OLLAMA_PROBE_TIMEOUT_SECONDS)
        return r.ok
    except requests.RequestException:
        return False


def _probe_postgres_latency() -> float:
    """Return the wall-clock duration of one ``SELECT 1`` in milliseconds."""
    started = time.monotonic()
    with connection.cursor() as cur:
        cur.execute("SELECT 1")
        cur.fetchone()
    return (time.monotonic() - started) * 1000.0


def _emit_alert(*, check_name: str, severity: str, message: str, context: dict) -> HealthAlert:
    alert = HealthAlert.objects.create(
        check_name=check_name,
        severity=severity,
        message=message,
        context=context,
    )
    if severity in ("error", "critical"):
        notify_admins(severity=severity, check_name=check_name, message=message)
    return alert


def notify_admins(*, severity: str, check_name: str, message: str) -> None:
    """Send an email to all users in the ``health-admins`` group.

    Kept as a module-level function so tests can patch it without
    monkey-patching Celery internals.
    """
    from django.contrib.auth.models import Group
    from django.core.mail import send_mail

    try:
        admins = Group.objects.get(name="health-admins").user_set.exclude(email="")
    except Group.DoesNotExist:
        logger.warning("health-admins group does not exist; skipping alert email")
        return
    recipients = list(admins.values_list("email", flat=True))
    if not recipients:
        return
    send_mail(
        subject=f"[interactome] {severity.upper()}: {check_name}",
        message=message,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "interactome@localhost"),
        recipient_list=recipients,
        fail_silently=True,
    )


@shared_task(queue="q.io")
def healthcheck() -> dict:
    """Run all three health probes; emit one HealthAlert per failure.

    Returns a small dict summarising the run, so Flower / task logs
    are searchable.
    """
    # Lazy import: ``schedule`` depends on ``monitoring`` at import time.
    from schedule.models import Watermark

    result = {
        "pubmed_refresh_stale": False,
        "ollama_unreachable": False,
        "postgres_slow": False,
    }

    # (a) PubMed freshness
    try:
        watermark = Watermark.objects.get(source="pubmed")
        age = timezone.now() - watermark.last_success_at
        if age > timedelta(hours=PUBMED_FRESHNESS_THRESHOLD_HOURS):
            _emit_alert(
                check_name="pubmed_refresh_stale",
                severity="error",
                message=(
                    f"No successful corpus.refresh_pubmed in {age.total_seconds() / 3600:.1f}h "
                    f"(threshold {PUBMED_FRESHNESS_THRESHOLD_HOURS}h)"
                ),
                context={"age_hours": age.total_seconds() / 3600},
            )
            result["pubmed_refresh_stale"] = True
    except Watermark.DoesNotExist:
        _emit_alert(
            check_name="pubmed_refresh_stale",
            severity="error",
            message="No pubmed watermark row exists",
            context={},
        )
        result["pubmed_refresh_stale"] = True

    # (b) Ollama reachability
    if not _probe_ollama():
        _emit_alert(
            check_name="ollama_unreachable",
            severity="critical",
            message=f"Ollama gateway {settings.OLLAMA_BASE} did not respond within "
            f"{OLLAMA_PROBE_TIMEOUT_SECONDS}s",
            context={"ollama_base": settings.OLLAMA_BASE},
        )
        result["ollama_unreachable"] = True

    # (c) Postgres latency
    latency_ms = _probe_postgres_latency()
    if latency_ms > POSTGRES_LATENCY_WARN_MS:
        _emit_alert(
            check_name="postgres_slow",
            severity="warning",
            message=f"SELECT 1 took {latency_ms:.0f} ms (threshold {POSTGRES_LATENCY_WARN_MS:.0f} ms)",
            context={"latency_ms": latency_ms},
        )
        result["postgres_slow"] = True

    return result
```

- [ ] **Step 3: Run the test to confirm it passes**

```bash
poetry run pytest apps/monitoring/tests/test_healthcheck.py -v
```

Expected: `5 passed`.

- [ ] **Step 4: Commit**

```bash
git add apps/monitoring/tasks.py apps/monitoring/tests/test_healthcheck.py
git commit -m "feat(monitoring): add 15-min healthcheck task with pubmed/ollama/postgres probes"
```

---

## Task 5: Admin pause/resume views (TDD)

A two-button HTMX panel on the dashboard nav that posts to
`/admin/monitoring/pause/` or `/admin/monitoring/resume/`. Only users in
the `curators` group can hit these endpoints (the spec doesn't define a
finer role model; reusing `curators` keeps it simple).

**Files:**
- Create: `apps/monitoring/tests/test_views.py`
- Modify: `apps/monitoring/views.py`
- Modify: `apps/monitoring/urls.py`
- Create: `apps/monitoring/templates/monitoring/pause_panel.html`

- [ ] **Step 1: Create the test in `apps/monitoring/tests/test_views.py`**

```python
"""Tests for monitoring.views — pause/resume admin endpoints."""
from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client

from monitoring import services
from monitoring.models import FeatureFlag

User = get_user_model()


@pytest.fixture
def curator_client(db) -> Client:
    user, _ = User.objects.get_or_create(username="curator", defaults={"email": "c@x.com"})
    group, _ = Group.objects.get_or_create(name="curators")
    user.groups.add(group)
    client = Client(HTTP_REMOTE_USER="curator", HTTP_REMOTE_GROUPS="curators")
    return client


@pytest.fixture
def non_curator_client(db) -> Client:
    User.objects.get_or_create(username="visitor")
    return Client(HTTP_REMOTE_USER="visitor")


def test_pause_endpoint_requires_curator_group(non_curator_client):
    r = non_curator_client.post(
        "/admin/monitoring/pause/", data={"reason": "test"}
    )
    assert r.status_code == 403


def test_pause_endpoint_sets_flag(curator_client):
    r = curator_client.post(
        "/admin/monitoring/pause/", data={"reason": "cluster maintenance"}
    )
    assert r.status_code == 200
    assert services.is_ingestion_paused() is True
    flag = FeatureFlag.objects.get(name="INGESTION_PAUSED")
    assert flag.last_changed_by == "curator"
    assert flag.last_changed_reason == "cluster maintenance"


def test_resume_endpoint_clears_flag(curator_client):
    services.set_ingestion_paused(True, by="curator", reason="setup")
    r = curator_client.post(
        "/admin/monitoring/resume/", data={"reason": "all clear"}
    )
    assert r.status_code == 200
    assert services.is_ingestion_paused() is False


def test_pause_endpoint_requires_post(curator_client):
    r = curator_client.get("/admin/monitoring/pause/")
    assert r.status_code == 405


def test_pause_endpoint_returns_htmx_partial(curator_client):
    r = curator_client.post(
        "/admin/monitoring/pause/", data={"reason": "x"}
    )
    assert "Ingestion paused" in r.content.decode()
```

- [ ] **Step 2: Implement `apps/monitoring/views.py`**

```python
"""monitoring views — admin pause / resume HTMX endpoints."""
from __future__ import annotations

from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import render
from django.views.decorators.http import require_POST

from monitoring import services


def _is_curator(request: HttpRequest) -> bool:
    if not request.user.is_authenticated:
        return False
    return request.user.groups.filter(name="curators").exists()


@require_POST
def pause(request: HttpRequest) -> HttpResponse:
    if not _is_curator(request):
        return HttpResponseForbidden("curators-only")
    reason = request.POST.get("reason", "").strip() or "(no reason given)"
    services.set_ingestion_paused(True, by=request.user.username, reason=reason)
    return render(
        request,
        "monitoring/pause_panel.html",
        {"paused": True, "reason": reason},
    )


@require_POST
def resume(request: HttpRequest) -> HttpResponse:
    if not _is_curator(request):
        return HttpResponseForbidden("curators-only")
    reason = request.POST.get("reason", "").strip() or "(no reason given)"
    services.set_ingestion_paused(False, by=request.user.username, reason=reason)
    return render(
        request,
        "monitoring/pause_panel.html",
        {"paused": False, "reason": reason},
    )
```

- [ ] **Step 3: Wire the URLs in `apps/monitoring/urls.py`**

```python
"""monitoring URL routes."""
from __future__ import annotations

from django.urls import path

from monitoring import views

app_name = "monitoring"
urlpatterns = [
    path("pause/", views.pause, name="pause"),
    path("resume/", views.resume, name="resume"),
]
```

- [ ] **Step 4: Create the HTMX partial template at `apps/monitoring/templates/monitoring/pause_panel.html`**

```html
{# Pause/resume control panel — included in the dashboard navbar. #}
<div id="monitoring-pause-panel" class="monitoring-pause-panel">
  {% if paused %}
    <span class="status status--paused">Ingestion paused</span>
    <form hx-post="{% url 'monitoring:resume' %}" hx-target="#monitoring-pause-panel">
      <input type="text" name="reason" placeholder="reason for resuming" required />
      <button type="submit">Resume ingestion</button>
    </form>
  {% else %}
    <span class="status status--running">Ingestion running</span>
    <form hx-post="{% url 'monitoring:pause' %}" hx-target="#monitoring-pause-panel">
      <input type="text" name="reason" placeholder="reason for pausing" required />
      <button type="submit">Pause ingestion</button>
    </form>
  {% endif %}
</div>
```

- [ ] **Step 5: Run the tests to confirm they pass**

```bash
poetry run pytest apps/monitoring/tests/test_views.py -v
```

Expected: `5 passed`.

- [ ] **Step 6: Commit**

```bash
git add apps/monitoring/views.py apps/monitoring/urls.py \
        apps/monitoring/templates/monitoring/pause_panel.html \
        apps/monitoring/tests/test_views.py
git commit -m "feat(monitoring): add pause/resume HTMX admin endpoints"
```

---

## Task 6: Honour the pause flag in `corpus.refresh_pubmed` and `extract.enqueue_pending_chunks` (TDD)

Per spec Section 10 risk row ("Compute contested by other groups → extraction
stalls — Beat-driven pause/resume"), the pause/resume mechanism is the user-
facing handle for the same problem. The two highest-throughput Beat tasks
must check the flag before doing real work.

`corpus.refresh_pubmed` additionally honours `is_backpressured()`.

**Files:**
- Create: `apps/monitoring/tests/test_backpressure.py`
- Modify: `apps/corpus/tasks.py` (add early-exit check at top of `refresh_pubmed`)
- Modify: `apps/extract/tasks.py` (add early-exit check at top of `enqueue_pending_chunks`)

- [ ] **Step 1: Create the test in `apps/monitoring/tests/test_backpressure.py`**

```python
"""Tests verifying pause flag and backpressure short-circuit Beat tasks."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from monitoring import services


@pytest.mark.django_db
class TestRefreshPubmedHonoursPauseFlag:
    @patch("corpus.tasks._do_refresh_pubmed")
    def test_paused_short_circuits(self, mock_do):
        services.set_ingestion_paused(True, by="t", reason="t")
        from corpus.tasks import refresh_pubmed

        result = refresh_pubmed()

        assert mock_do.called is False
        assert result == {"skipped": True, "reason": "ingestion_paused"}

    @patch("corpus.tasks._do_refresh_pubmed", return_value={"new_papers": 0})
    def test_not_paused_runs_normally(self, mock_do):
        from corpus.tasks import refresh_pubmed

        result = refresh_pubmed()

        assert mock_do.called is True
        assert result == {"new_papers": 0}


@pytest.mark.django_db
class TestRefreshPubmedHonoursBackpressure:
    @patch("corpus.tasks._do_refresh_pubmed")
    @patch("monitoring.services._extract_queue_depth", return_value=10_001)
    def test_backpressured_short_circuits(self, _depth, mock_do):
        from corpus.tasks import refresh_pubmed

        result = refresh_pubmed()

        assert mock_do.called is False
        assert result == {"skipped": True, "reason": "backpressured"}


@pytest.mark.django_db
class TestEnqueuePendingChunksHonoursPauseFlag:
    @patch("extract.tasks._do_enqueue_pending_chunks")
    def test_paused_short_circuits(self, mock_do):
        services.set_ingestion_paused(True, by="t", reason="t")
        from extract.tasks import enqueue_pending_chunks

        result = enqueue_pending_chunks()

        assert mock_do.called is False
        assert result == {"skipped": True, "reason": "ingestion_paused"}
```

- [ ] **Step 2: Modify `apps/corpus/tasks.py`**

Locate the existing `refresh_pubmed` task body. Rename the current body
to `_do_refresh_pubmed` (a private helper) and replace the public
`refresh_pubmed` with a thin wrapper that checks the flag first.

Add at the top of the file:

```python
from monitoring import services as monitoring_services
```

Replace the existing task definition. The new pattern is:

```python
@shared_task(queue="q.io")
def refresh_pubmed() -> dict:
    """Hourly Beat-fired sweep of PubMed for new IDD-relevant papers.

    Short-circuits if (a) the global INGESTION_PAUSED flag is set, or
    (b) the extraction queue depth exceeds the backpressure threshold.

    See spec Section 10 (continuous monitoring) and Section 6
    (Beat schedule).
    """
    if monitoring_services.is_ingestion_paused():
        return {"skipped": True, "reason": "ingestion_paused"}
    if monitoring_services.is_backpressured():
        return {"skipped": True, "reason": "backpressured"}
    return _do_refresh_pubmed()


def _do_refresh_pubmed() -> dict:
    """The original body of refresh_pubmed — preserved verbatim from Phase 1.

    Returns a summary dict like ``{"new_papers": N, "watermark": <pmid>}``.
    """
    # ... original Phase 1 body ...
```

(The exact contents of `_do_refresh_pubmed` are whatever Phase 1 wrote.
Do not modify the logic — only extract-and-rename.)

- [ ] **Step 3: Modify `apps/extract/tasks.py`**

Same pattern. Wrap the existing `enqueue_pending_chunks`:

```python
from monitoring import services as monitoring_services


@shared_task(queue="q.io")
def enqueue_pending_chunks() -> dict:
    """Every-5-min sweep that finds unprocessed (Chunk × Model) pairs.

    Short-circuits if INGESTION_PAUSED is set. Does NOT honour
    backpressure — when we *are* backpressured, this task is exactly
    what drains the queue.
    """
    if monitoring_services.is_ingestion_paused():
        return {"skipped": True, "reason": "ingestion_paused"}
    return _do_enqueue_pending_chunks()


def _do_enqueue_pending_chunks() -> dict:
    """Original Phase 2 body — preserved verbatim."""
    # ... original Phase 2 body ...
```

- [ ] **Step 4: Run the tests to confirm they pass**

```bash
poetry run pytest apps/monitoring/tests/test_backpressure.py -v
```

Expected: `4 passed`.

- [ ] **Step 5: Run the full Phase 1 + Phase 2 tests to confirm no regressions**

```bash
poetry run pytest apps/corpus apps/extract -v
```

Expected: all prior tests still pass (the wrapper is functionally a no-op
when the flag is clear and the queue is small).

- [ ] **Step 6: Commit**

```bash
git add apps/corpus/tasks.py apps/extract/tasks.py \
        apps/monitoring/tests/test_backpressure.py
git commit -m "feat(monitoring): wire pause flag and backpressure into corpus + extract"
```

---

## Task 7: `paper_ingested` Django signal + `graph.detect_affected_networks` (TDD)

This is the heart of the delta-detection logic. When `corpus.ingest_paper`
finishes, it fires a `paper_ingested` Django signal. A receiver enqueues
`graph.detect_affected_networks(paper_id)`, which uses the cheap-pass
relevance triage results from Phase 1 to determine which networks the
new paper might affect. It then updates `NetworkEdgeMembership` rows
optimistically with the paper's PMID flagged as `pending_extraction=True`,
so the downstream `graph.integrate_pending` knows which networks to
mark `STALE` once extraction completes.

**Files:**
- Create: `apps/corpus/signals.py`
- Modify: `apps/corpus/apps.py` (connect the signal in `ready`)
- Modify: `apps/corpus/tasks.py` (fire the signal after successful ingest)
- Create: `apps/graph/tests/test_detect_affected.py`
- Modify: `apps/graph/tasks.py` (add `detect_affected_networks`)
- Modify: `apps/graph/services.py` (add `affected_network_ids` helper)
- Create: `apps/corpus/tests/test_paper_ingested_signal.py`

- [ ] **Step 1: Create `apps/corpus/signals.py`**

```python
"""corpus signals.

``paper_ingested`` is fired by ``corpus.tasks.ingest_paper`` after a
new Paper row + its PaperRelevance rows are committed. Receivers should
be cheap (just enqueue downstream Celery tasks); they run synchronously
inside the ingest task's transaction-commit hook.
"""
from __future__ import annotations

from django.dispatch import Signal

# Sent with kwargs: paper_id (int), pmid (str), relevance_scores (dict[int,float])
paper_ingested = Signal()
```

- [ ] **Step 2: Modify `apps/corpus/apps.py` to connect a receiver**

```python
"""Django AppConfig for the corpus app."""
from __future__ import annotations

from django.apps import AppConfig


class CorpusConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "corpus"

    def ready(self) -> None:
        # Importing the module registers its @receiver-decorated handlers.
        from corpus import receivers  # noqa: F401
```

- [ ] **Step 3: Create `apps/corpus/receivers.py`**

```python
"""corpus signal receivers — wire paper_ingested → detect_affected_networks."""
from __future__ import annotations

from django.dispatch import receiver

from corpus.signals import paper_ingested


@receiver(paper_ingested)
def on_paper_ingested(sender, **kwargs):
    """Enqueue per-network delta-detection for the newly-ingested paper."""
    from graph.tasks import detect_affected_networks

    paper_id = kwargs["paper_id"]
    detect_affected_networks.delay(paper_id)
```

- [ ] **Step 4: Modify `apps/corpus/tasks.py` to fire the signal**

After the `Paper` row and its `PaperRelevance` rows are committed inside
the existing `ingest_paper` task, add:

```python
from django.db import transaction

from corpus.signals import paper_ingested


# at the end of ingest_paper, after the atomic block commits:
transaction.on_commit(
    lambda: paper_ingested.send(
        sender=ingest_paper,
        paper_id=paper.id,
        pmid=paper.pmid,
        relevance_scores={r.network_id: r.score for r in paper.paperrelevance_set.all()},
    )
)
```

(Use `transaction.on_commit` rather than firing inside the atomic block
so the signal handlers don't run if the transaction rolls back.)

- [ ] **Step 5: Create `apps/corpus/tests/test_paper_ingested_signal.py`**

```python
"""Tests for the paper_ingested signal wiring."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from corpus.signals import paper_ingested


@pytest.mark.django_db
def test_signal_handler_enqueues_detect_affected_networks():
    with patch("graph.tasks.detect_affected_networks.delay") as mock_delay:
        paper_ingested.send(
            sender=None,
            paper_id=42,
            pmid="99999999",
            relevance_scores={1: 0.8, 2: 0.3},
        )
        mock_delay.assert_called_once_with(42)
```

- [ ] **Step 6: Create `apps/graph/tests/test_detect_affected.py`**

```python
"""Tests for graph.detect_affected_networks."""
from __future__ import annotations

import pytest

from corpus.models import Paper, PaperRelevance
from graph.models import NetworkEdgeMembership
from graph.tasks import detect_affected_networks
from networks.models import Network


@pytest.fixture
def two_networks(db):
    n1 = Network.objects.create(code="nfkb_axis", title="NF-κB")
    n2 = Network.objects.create(code="wnt", title="Wnt")
    return n1, n2


@pytest.fixture
def paper_with_relevance(db, two_networks):
    n1, n2 = two_networks
    p = Paper.objects.create(pmid="11111111", title="t", abstract="a")
    PaperRelevance.objects.create(paper=p, network=n1, score=0.92)
    PaperRelevance.objects.create(paper=p, network=n2, score=0.10)  # below threshold
    return p


@pytest.mark.django_db
def test_detect_marks_only_relevant_networks(paper_with_relevance, two_networks):
    n1, n2 = two_networks
    result = detect_affected_networks(paper_with_relevance.id)
    assert n1.id in result["affected_network_ids"]
    assert n2.id not in result["affected_network_ids"]


@pytest.mark.django_db
def test_detect_creates_membership_rows_with_pending_flag(
    paper_with_relevance, two_networks
):
    n1, _ = two_networks
    detect_affected_networks(paper_with_relevance.id)
    rows = NetworkEdgeMembership.objects.filter(
        network=n1, pending_paper_id=paper_with_relevance.id
    )
    assert rows.exists()
    assert all(r.pending_extraction for r in rows)


@pytest.mark.django_db
def test_detect_is_idempotent(paper_with_relevance, two_networks):
    detect_affected_networks(paper_with_relevance.id)
    detect_affected_networks(paper_with_relevance.id)
    # Second call must not create duplicate pending rows
    rows = NetworkEdgeMembership.objects.filter(
        pending_paper_id=paper_with_relevance.id, pending_extraction=True
    )
    assert rows.count() == 1


@pytest.mark.django_db
def test_detect_returns_empty_for_paper_with_no_relevance(db, two_networks):
    p = Paper.objects.create(pmid="22222222", title="t", abstract="a")
    result = detect_affected_networks(p.id)
    assert result["affected_network_ids"] == []
```

- [ ] **Step 7: Implement `graph.tasks.detect_affected_networks` in `apps/graph/tasks.py`**

Append to the existing file:

```python
from celery import shared_task
from django.db import transaction

from corpus.models import Paper
from graph.models import NetworkEdgeMembership
from graph.services import affected_network_ids

RELEVANCE_THRESHOLD = 0.5  # mirrors Phase 1 corpus-export threshold


@shared_task(queue="q.io")
def detect_affected_networks(paper_id: int) -> dict:
    """For a newly-ingested paper, mark its candidate networks pending.

    Reads ``PaperRelevance`` rows produced by Phase 1's cheap-pass triage.
    For each network with score >= RELEVANCE_THRESHOLD, idempotently
    inserts a ``NetworkEdgeMembership`` row with
    ``pending_paper_id=paper_id`` and ``pending_extraction=True``.

    Once ``graph.integrate_pending`` processes the resulting RawPPIs and
    promotes them to Edges, it clears the pending flag and sets the
    network's ``pipeline_status='stale'`` (handled in Phase 3, untouched).

    Reference: spec Section 4 (per-paper pipeline) +
    Section 10 (Phase 6 — delta detection).
    """
    paper = Paper.objects.get(id=paper_id)
    network_ids = affected_network_ids(paper.id, threshold=RELEVANCE_THRESHOLD)

    with transaction.atomic():
        for nid in network_ids:
            NetworkEdgeMembership.objects.get_or_create(
                network_id=nid,
                pending_paper_id=paper.id,
                defaults={"pending_extraction": True, "edge_id": None},
            )

    return {"paper_id": paper_id, "affected_network_ids": network_ids}
```

- [ ] **Step 8: Add `affected_network_ids` helper to `apps/graph/services.py`**

```python
def affected_network_ids(paper_id: int, *, threshold: float = 0.5) -> list[int]:
    """Return network IDs whose relevance to ``paper_id`` is >= threshold.

    Public boundary function — other apps call this rather than touching
    ``PaperRelevance`` directly.
    """
    from corpus.models import PaperRelevance

    return list(
        PaperRelevance.objects.filter(paper_id=paper_id, score__gte=threshold)
        .values_list("network_id", flat=True)
    )
```

- [ ] **Step 9: Add `pending_paper_id` and `pending_extraction` columns to `NetworkEdgeMembership`**

In `apps/graph/models.py`, add to the existing `NetworkEdgeMembership`
model:

```python
    pending_paper_id = models.IntegerField(null=True, blank=True, db_index=True)
    pending_extraction = models.BooleanField(default=False, db_index=True)
```

Then generate the migration:

```bash
poetry run python manage.py makemigrations graph
```

Expected:
```
Migrations for 'graph':
  apps/graph/migrations/0002_alter_networkedgemembership_pending.py
    - Add field pending_paper_id to networkedgemembership
    - Add field pending_extraction to networkedgemembership
```

- [ ] **Step 10: Run all tests added in this task**

```bash
poetry run pytest apps/corpus/tests/test_paper_ingested_signal.py \
                  apps/graph/tests/test_detect_affected.py -v
```

Expected: `5 passed`.

- [ ] **Step 11: Commit**

```bash
git add apps/corpus/signals.py apps/corpus/receivers.py \
        apps/corpus/apps.py apps/corpus/tasks.py \
        apps/corpus/tests/test_paper_ingested_signal.py \
        apps/graph/tasks.py apps/graph/services.py apps/graph/models.py \
        apps/graph/migrations/ \
        apps/graph/tests/test_detect_affected.py
git commit -m "feat(graph): add detect_affected_networks task and paper_ingested signal"
```

---

## Task 8: Auto-conflict resolver (TDD)

The spec (Section 10 "auto-conflict resolver") calls for an LLM-driven
re-read of low-confidence conflicts. The strongest available biomedical
model — medgemma:27b — re-evaluates the source chunk against the
conflicting RawPPI rows. If the re-read produces high confidence, the
`Conflict` row is auto-resolved with full audit trail; otherwise it stays
open for a human curator.

**Files:**
- Create: `apps/verify/prompts.py`
- Create: `apps/verify/tests/test_auto_resolve.py`
- Modify: `apps/verify/tasks.py`

- [ ] **Step 1: Create `apps/verify/prompts.py`**

The exact prompt and JSON schema are below. Use these verbatim — the
Phase 2 prompt engineering process validated this style on the
Pfirrmann-grading work cited in spec Section 10 risks.

```python
"""Prompts for verify-app LLM tasks (conflict auto-resolution)."""
from __future__ import annotations

CONFLICT_REREAD_PROMPT = """\
You are a senior biomedical curator with deep expertise in cell signaling.
Two prior automated extractions disagreed about the direction of a
regulatory relationship reported in the same source chunk. Re-read the
chunk carefully, then return a single JSON object with your verdict.

Source chunk (PMID {pmid}, section {section_doco_type}):
\"\"\"
{chunk_text}
\"\"\"

Subject entity: {subject_symbol} ({subject_id})
Object entity:  {object_symbol} ({object_id})

The two prior extractions disagree as follows:

EXTRACTION A (model={model_a}, confidence={confidence_a:.2f}):
  relation={relation_a}
  evidence_span="{evidence_span_a}"

EXTRACTION B (model={model_b}, confidence={confidence_b:.2f}):
  relation={relation_b}
  evidence_span="{evidence_span_b}"

Your task:

1. Identify the single sentence (or sentence pair) in the chunk that
   resolves the question.
2. Pick the correct relation from this controlled vocabulary:
   activates, inhibits, binds, phosphorylates, dephosphorylates,
   ubiquitinates, deubiquitinates, methylates, acetylates,
   transcriptional_activation, transcriptional_repression,
   no_relation, context_dependent.
3. Assess your confidence on a 0.0–1.0 scale. A score >= 0.85 means
   "I am willing to stake my professional reputation on this verdict";
   below that, return ``context_dependent`` or ``no_relation`` and a
   lower confidence so a human reviews the case.
4. Cite the resolving text verbatim (≤ 200 chars).

Return ONLY valid JSON matching the schema below. No prose.
"""

CONFLICT_REREAD_SCHEMA = {
    "type": "object",
    "properties": {
        "relation": {
            "type": "string",
            "enum": [
                "activates",
                "inhibits",
                "binds",
                "phosphorylates",
                "dephosphorylates",
                "ubiquitinates",
                "deubiquitinates",
                "methylates",
                "acetylates",
                "transcriptional_activation",
                "transcriptional_repression",
                "no_relation",
                "context_dependent",
            ],
        },
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "resolving_text": {"type": "string", "maxLength": 200},
        "reasoning": {"type": "string", "maxLength": 800},
    },
    "required": ["relation", "confidence", "resolving_text", "reasoning"],
    "additionalProperties": False,
}

AUTO_RESOLVE_CONFIDENCE_THRESHOLD = 0.85
```

- [ ] **Step 2: Create the test in `apps/verify/tests/test_auto_resolve.py`**

```python
"""Tests for verify.tasks.auto_resolve."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from extract.models import ExtractionRun, RawPPI
from graph.models import Conflict, Edge, Entity
from networks.models import Network
from papers.models import Chunk, Section
from corpus.models import Paper
from verify.tasks import auto_resolve


@pytest.fixture
def conflict_with_two_raw_ppis(db):
    paper = Paper.objects.create(pmid="33333333", title="t", abstract="a")
    section = Section.objects.create(paper=paper, doco_type="Results", text="...")
    chunk = Chunk.objects.create(
        section=section,
        text="SIRT1 deacetylates p65 at K310, attenuating NF-κB-driven transcription.",
        ordinal=0,
    )
    e_src = Entity.objects.create(symbol="SIRT1", canonical_id="hgnc:14929")
    e_tgt = Entity.objects.create(symbol="NFKB1", canonical_id="hgnc:7794")
    edge = Edge.objects.create(source=e_src, target=e_tgt, relation_type="conflicted")

    run_a = ExtractionRun.objects.create(chunk=chunk, model="medgemma_27b", status="done")
    run_b = ExtractionRun.objects.create(chunk=chunk, model="phi4_14b", status="done")
    ppi_a = RawPPI.objects.create(
        run=run_a, subject_text="SIRT1", object_text="NFKB1",
        relation="inhibits", evidence_span="deacetylates p65", confidence=0.74,
    )
    ppi_b = RawPPI.objects.create(
        run=run_b, subject_text="SIRT1", object_text="NFKB1",
        relation="activates", evidence_span="...", confidence=0.68,
    )
    conflict = Conflict.objects.create(
        edge=edge,
        raw_ppi_a=ppi_a,
        raw_ppi_b=ppi_b,
        resolution_status="open",
    )
    return conflict


@pytest.mark.django_db
class TestAutoResolveHighConfidence:
    @patch("verify.tasks._call_medgemma_for_reread")
    def test_high_confidence_resolves_conflict(self, mock_llm, conflict_with_two_raw_ppis):
        mock_llm.return_value = {
            "relation": "inhibits",
            "confidence": 0.93,
            "resolving_text": "SIRT1 deacetylates p65 at K310, attenuating NF-κB",
            "reasoning": "Deacetylation of p65 reduces NF-κB transcriptional output.",
        }
        auto_resolve(conflict_with_two_raw_ppis.id)
        conflict_with_two_raw_ppis.refresh_from_db()
        assert conflict_with_two_raw_ppis.resolution_status == "auto_resolved"
        assert conflict_with_two_raw_ppis.resolved_relation == "inhibits"
        assert "Deacetylation" in conflict_with_two_raw_ppis.reasoning


@pytest.mark.django_db
class TestAutoResolveLowConfidence:
    @patch("verify.tasks._call_medgemma_for_reread")
    def test_low_confidence_leaves_open(self, mock_llm, conflict_with_two_raw_ppis):
        mock_llm.return_value = {
            "relation": "context_dependent",
            "confidence": 0.55,
            "resolving_text": "ambiguous wording in chunk",
            "reasoning": "The chunk mixes two cell types; cannot decide.",
        }
        auto_resolve(conflict_with_two_raw_ppis.id)
        conflict_with_two_raw_ppis.refresh_from_db()
        assert conflict_with_two_raw_ppis.resolution_status == "open"
        # but reasoning is recorded for the human curator's benefit
        assert "ambiguous" in conflict_with_two_raw_ppis.reasoning


@pytest.mark.django_db
class TestAutoResolveIdempotency:
    @patch("verify.tasks._call_medgemma_for_reread")
    def test_already_resolved_short_circuits(self, mock_llm, conflict_with_two_raw_ppis):
        conflict_with_two_raw_ppis.resolution_status = "auto_resolved"
        conflict_with_two_raw_ppis.save()
        auto_resolve(conflict_with_two_raw_ppis.id)
        assert mock_llm.called is False


@pytest.mark.django_db
class TestAutoResolveCorrectPromptShape:
    @patch("verify.tasks._call_medgemma_for_reread")
    def test_prompt_contains_chunk_text(self, mock_llm, conflict_with_two_raw_ppis):
        mock_llm.return_value = {
            "relation": "inhibits", "confidence": 0.9,
            "resolving_text": "x", "reasoning": "y",
        }
        auto_resolve(conflict_with_two_raw_ppis.id)
        args, kwargs = mock_llm.call_args
        prompt = kwargs.get("prompt") or args[0]
        assert "SIRT1 deacetylates p65" in prompt
        assert "EXTRACTION A" in prompt
        assert "EXTRACTION B" in prompt
```

- [ ] **Step 3: Add the `auto_resolve` task to `apps/verify/tasks.py`**

Append:

```python
from celery import shared_task
from django.db import transaction
from django.utils import timezone

from verify.prompts import (
    AUTO_RESOLVE_CONFIDENCE_THRESHOLD,
    CONFLICT_REREAD_PROMPT,
    CONFLICT_REREAD_SCHEMA,
)


def _call_medgemma_for_reread(prompt: str) -> dict:
    """Issue a single Ollama call to medgemma:27b with schema-constrained output.

    Extracted into its own function so tests can patch it. The actual
    HTTP call delegates to ``extract.ollama_client`` (built in Phase 2)
    so token-budget and timeout semantics are shared.
    """
    from extract.ollama_client import generate_structured

    return generate_structured(
        model="medgemma:27b",
        prompt=prompt,
        json_schema=CONFLICT_REREAD_SCHEMA,
        temperature=0.1,
        keep_alive="2h",
    )


@shared_task(queue="q.extract.medgemma_27b", bind=True, max_retries=2)
def auto_resolve(self, conflict_id: int) -> dict:
    """Re-read the source chunk and resolve a conflict if confidence is high.

    Sets ``Conflict.resolution_status='auto_resolved'`` when the medgemma
    re-read returns confidence >= AUTO_RESOLVE_CONFIDENCE_THRESHOLD;
    leaves it ``open`` (but records ``reasoning``) otherwise.

    Runs on the medgemma queue so the model stays hot — the extraction
    workers' OLLAMA_KEEP_ALIVE=2h means a single shared resident model
    serves both new chunks and conflict re-reads.

    Reference: spec Section 10 (Phase 6 — auto-conflict resolver).
    """
    from graph.models import Conflict

    with transaction.atomic():
        conflict = Conflict.objects.select_for_update().get(id=conflict_id)
        if conflict.resolution_status != "open":
            return {"skipped": True, "status": conflict.resolution_status}

    ppi_a = conflict.raw_ppi_a
    ppi_b = conflict.raw_ppi_b
    chunk = ppi_a.run.chunk
    paper = chunk.section.paper

    prompt = CONFLICT_REREAD_PROMPT.format(
        pmid=paper.pmid,
        section_doco_type=chunk.section.doco_type,
        chunk_text=chunk.text,
        subject_symbol=conflict.edge.source.symbol,
        subject_id=conflict.edge.source.canonical_id,
        object_symbol=conflict.edge.target.symbol,
        object_id=conflict.edge.target.canonical_id,
        model_a=ppi_a.run.model,
        confidence_a=ppi_a.confidence,
        relation_a=ppi_a.relation,
        evidence_span_a=ppi_a.evidence_span,
        model_b=ppi_b.run.model,
        confidence_b=ppi_b.confidence,
        relation_b=ppi_b.relation,
        evidence_span_b=ppi_b.evidence_span,
    )

    try:
        verdict = _call_medgemma_for_reread(prompt=prompt)
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60) from exc

    is_confident = verdict["confidence"] >= AUTO_RESOLVE_CONFIDENCE_THRESHOLD
    is_decisive = verdict["relation"] not in ("context_dependent", "no_relation")

    with transaction.atomic():
        conflict = Conflict.objects.select_for_update().get(id=conflict_id)
        conflict.reasoning = (
            f"medgemma:27b verdict (conf={verdict['confidence']:.2f}): "
            f"relation={verdict['relation']!r}. "
            f"Resolving text: {verdict['resolving_text']!r}. "
            f"Reasoning: {verdict['reasoning']}"
        )
        conflict.auto_resolve_attempted_at = timezone.now()

        if is_confident and is_decisive:
            conflict.resolution_status = "auto_resolved"
            conflict.resolved_relation = verdict["relation"]
            conflict.resolved_at = timezone.now()
            # Update the underlying edge so SBML regen picks up the verdict
            edge = conflict.edge
            edge.relation_type = verdict["relation"]
            edge.status = "accepted"
            edge.save(update_fields=["relation_type", "status", "updated_at"])

        conflict.save()

    return {
        "conflict_id": conflict_id,
        "status": conflict.resolution_status,
        "confidence": verdict["confidence"],
    }
```

- [ ] **Step 4: Add the missing fields to `Conflict`**

In `apps/graph/models.py`, add (if not already present from Phase 3):

```python
    reasoning = models.TextField(blank=True, default="")
    resolved_relation = models.CharField(max_length=64, blank=True, default="")
    resolved_at = models.DateTimeField(null=True, blank=True)
    auto_resolve_attempted_at = models.DateTimeField(null=True, blank=True)
```

Update the `resolution_status` choices to include `auto_resolved`:

```python
    RESOLUTION_CHOICES = [
        ("open", "Open"),
        ("auto_resolved", "Auto-resolved"),
        ("human_resolved", "Human-resolved"),
        ("split_context_dependent", "Split (context-dependent)"),
    ]
```

Generate the migration:

```bash
poetry run python manage.py makemigrations graph
```

- [ ] **Step 5: Run the tests**

```bash
poetry run pytest apps/verify/tests/test_auto_resolve.py -v
```

Expected: `5 passed`.

- [ ] **Step 6: Commit**

```bash
git add apps/verify/prompts.py apps/verify/tasks.py \
        apps/verify/tests/test_auto_resolve.py \
        apps/graph/models.py apps/graph/migrations/
git commit -m "feat(verify): add auto_resolve conflict task with medgemma:27b re-read"
```

---

## Task 9: Beat sweeper for open conflicts + Beat schedule additions (TDD)

Per spec Section 6 + Phase 6 brief, four new Beat entries are needed:

| Task | Cadence | Queue |
|---|---|---|
| `monitoring.tasks.healthcheck` | every 15 min | `q.io` |
| `verify.tasks.sweep_open_conflicts` | every 30 min | `q.io` |
| `verify.tasks.notify_subscribers_daily_digest` | daily 09:00 UTC | `q.io` |
| `verify.tasks.notify_subscribers_stale` | (signal-driven, not Beat) | `q.io` |

The 30-min `sweep_open_conflicts` task selects `Conflict` rows that
are `open` AND `created_at < now() - 1 hour` (the buffer lets the
integration worker detect cross-paper conflicts before the auto-resolver
fires) and enqueues `auto_resolve` for each.

**Files:**
- Modify: `apps/verify/tasks.py` (add `sweep_open_conflicts`)
- Modify: `apps/schedule/beat_schedule.py`
- Create: `apps/verify/tests/test_sweep_open_conflicts.py`
- Modify: `apps/schedule/tests/test_beat_schedule.py`

- [ ] **Step 1: Create the sweep test in `apps/verify/tests/test_sweep_open_conflicts.py`**

```python
"""Tests for verify.tasks.sweep_open_conflicts."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from graph.models import Conflict
from verify.tasks import sweep_open_conflicts


@pytest.fixture
def fresh_open_conflict(db):
    c = Conflict.objects.create(resolution_status="open")
    c.created_at = timezone.now() - timedelta(minutes=10)
    c.save()
    return c


@pytest.fixture
def aged_open_conflict(db):
    c = Conflict.objects.create(resolution_status="open")
    Conflict.objects.filter(id=c.id).update(
        created_at=timezone.now() - timedelta(hours=2)
    )
    return c


@pytest.fixture
def already_resolved_conflict(db):
    c = Conflict.objects.create(resolution_status="auto_resolved")
    Conflict.objects.filter(id=c.id).update(
        created_at=timezone.now() - timedelta(hours=2)
    )
    return c


@pytest.mark.django_db
class TestSweepOpenConflicts:
    @patch("verify.tasks.auto_resolve.delay")
    def test_aged_open_conflict_is_enqueued(
        self, mock_delay, aged_open_conflict
    ):
        sweep_open_conflicts()
        mock_delay.assert_called_once_with(aged_open_conflict.id)

    @patch("verify.tasks.auto_resolve.delay")
    def test_fresh_open_conflict_is_skipped(
        self, mock_delay, fresh_open_conflict
    ):
        sweep_open_conflicts()
        mock_delay.assert_not_called()

    @patch("verify.tasks.auto_resolve.delay")
    def test_already_resolved_conflict_is_skipped(
        self, mock_delay, already_resolved_conflict
    ):
        sweep_open_conflicts()
        mock_delay.assert_not_called()

    @patch("verify.tasks.auto_resolve.delay")
    def test_returns_count_dispatched(self, mock_delay, aged_open_conflict):
        result = sweep_open_conflicts()
        assert result["dispatched"] == 1
```

- [ ] **Step 2: Add the sweep task to `apps/verify/tasks.py`**

```python
from datetime import timedelta


CONFLICT_SWEEP_BUFFER = timedelta(hours=1)


@shared_task(queue="q.io")
def sweep_open_conflicts() -> dict:
    """Every 30 min, enqueue auto_resolve for stale-enough open conflicts.

    The 1-hour buffer (``CONFLICT_SWEEP_BUFFER``) gives ``graph.integrate_pending``
    time to detect inter-paper conflicts that arrive in the same batch.
    Without this delay, the resolver would fire on conflicts that are
    about to gain additional supporting evidence.

    Reference: spec Section 10 (Phase 6 — auto-conflict resolver).
    """
    from graph.models import Conflict

    cutoff = timezone.now() - CONFLICT_SWEEP_BUFFER
    qs = Conflict.objects.filter(
        resolution_status="open",
        created_at__lt=cutoff,
    ).values_list("id", flat=True)
    count = 0
    for cid in qs:
        auto_resolve.delay(cid)
        count += 1
    return {"dispatched": count}
```

- [ ] **Step 3: Add four Beat entries to `apps/schedule/beat_schedule.py`**

Open the existing file (built in Phase 1+) and add the following entries
to the `CELERY_BEAT_SCHEDULE` dict:

```python
from celery.schedules import crontab

CELERY_BEAT_SCHEDULE = {
    # ... existing Phase 1–5 entries ...

    # --- Phase 6 additions ---
    "monitoring.healthcheck": {
        "task": "monitoring.tasks.healthcheck",
        "schedule": 15 * 60,  # every 15 min
        "options": {"queue": "q.io"},
    },
    "verify.sweep_open_conflicts": {
        "task": "verify.tasks.sweep_open_conflicts",
        "schedule": 30 * 60,  # every 30 min
        "options": {"queue": "q.io"},
    },
    "verify.notify_subscribers_daily_digest": {
        "task": "verify.tasks.notify_subscribers_daily_digest",
        "schedule": crontab(hour=9, minute=0),  # daily 09:00 UTC
        "options": {"queue": "q.io"},
    },
    "schedule.refresh_beat_assertion": {
        "task": "schedule.tasks.assert_beat_alive",
        "schedule": 60,  # every minute — touches a Watermark row so healthcheck can verify Beat itself
        "options": {"queue": "q.io"},
    },
}
```

- [ ] **Step 4: Update `apps/schedule/tests/test_beat_schedule.py`**

Add (do not replace existing assertions):

```python
def test_phase6_entries_present(settings):
    sched = settings.CELERY_BEAT_SCHEDULE
    assert "monitoring.healthcheck" in sched
    assert sched["monitoring.healthcheck"]["schedule"] == 15 * 60
    assert "verify.sweep_open_conflicts" in sched
    assert sched["verify.sweep_open_conflicts"]["schedule"] == 30 * 60
    assert "verify.notify_subscribers_daily_digest" in sched


def test_phase6_entries_routed_to_io_queue(settings):
    sched = settings.CELERY_BEAT_SCHEDULE
    for entry_name in (
        "monitoring.healthcheck",
        "verify.sweep_open_conflicts",
        "verify.notify_subscribers_daily_digest",
    ):
        assert sched[entry_name]["options"]["queue"] == "q.io"
```

- [ ] **Step 5: Add `schedule.tasks.assert_beat_alive`**

In `apps/schedule/tasks.py`, append:

```python
@shared_task(queue="q.io")
def assert_beat_alive() -> dict:
    """Touch a watermark row so monitoring.healthcheck can verify Beat is firing."""
    from schedule.models import Watermark

    Watermark.objects.update_or_create(
        source="beat_heartbeat",
        defaults={"last_success_at": timezone.now()},
    )
    return {"ok": True}
```

- [ ] **Step 6: Run the new tests**

```bash
poetry run pytest apps/verify/tests/test_sweep_open_conflicts.py \
                  apps/schedule/tests/test_beat_schedule.py -v
```

Expected: all new tests pass; no regressions in existing Beat-schedule tests.

- [ ] **Step 7: Commit**

```bash
git add apps/verify/tasks.py apps/verify/tests/test_sweep_open_conflicts.py \
        apps/schedule/beat_schedule.py apps/schedule/tasks.py \
        apps/schedule/tests/test_beat_schedule.py
git commit -m "feat(schedule): add Phase 6 Beat entries for healthcheck, conflict sweep, daily digest"
```

---

## Task 10: Subscription notifications — stale-on-transition + daily disagreement digest (TDD)

Per spec Section 7 ("Reviewers subscribe per-user, per-network or per-category
for email + in-app notifications") and the Phase 6 brief:

- **Stale transition**: when a Network's `pipeline_status` flips to
  `stale`, enqueue `verify.notify_subscribers_stale(network_id)` to email
  every subscriber.
- **Daily digest**: collect all `Conflict` rows that opened in subscribed
  networks during the last 24 h and send one batched email per subscriber.

We use a Django signal `network_status_changed` fired by the existing
Phase 4 state-machine code; if Phase 5 already added a `Subscription`
model, reuse it.

**Files:**
- Create: `apps/verify/tests/test_subscription_notify.py`
- Create: `apps/verify/tests/test_disagreement_digest.py`
- Modify: `apps/verify/tasks.py`
- Modify: `apps/verify/services.py`
- Modify: `apps/networks/signals.py` (or create if it doesn't exist) — add `network_status_changed`
- Modify: `apps/networks/models.py` — fire the signal in `Network.transition_to`

- [ ] **Step 1: Add `network_status_changed` signal**

In `apps/networks/signals.py`:

```python
"""networks signals."""
from __future__ import annotations

from django.dispatch import Signal

# Sent with kwargs: network_id, from_status, to_status
network_status_changed = Signal()
```

- [ ] **Step 2: Fire the signal in the existing state-machine method**

In `apps/networks/models.py`, locate the `Network.transition_to(new_status)`
method (added in Phase 4). After the row is saved, add:

```python
        from networks.signals import network_status_changed
        from django.db import transaction

        old_status = self._original_pipeline_status  # set in __init__
        transaction.on_commit(
            lambda: network_status_changed.send(
                sender=self.__class__,
                network_id=self.id,
                from_status=old_status,
                to_status=new_status,
            )
        )
```

- [ ] **Step 3: Connect a receiver in `apps/verify/apps.py`**

```python
class VerifyConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "verify"

    def ready(self) -> None:
        from verify import receivers  # noqa: F401
```

- [ ] **Step 4: Create `apps/verify/receivers.py`**

```python
"""verify signal receivers."""
from __future__ import annotations

from django.dispatch import receiver

from networks.signals import network_status_changed


@receiver(network_status_changed)
def on_network_status_changed(sender, **kwargs):
    """When a network goes ``stale``, enqueue subscriber notifications."""
    from verify.tasks import notify_subscribers_stale

    if kwargs.get("to_status") == "stale":
        notify_subscribers_stale.delay(kwargs["network_id"])
```

- [ ] **Step 5: Create test in `apps/verify/tests/test_subscription_notify.py`**

```python
"""Tests for verify.tasks.notify_subscribers_stale."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from networks.models import Network
from verify.models import Subscription
from verify.tasks import notify_subscribers_stale

User = get_user_model()


@pytest.fixture
def subscribed_user(db):
    user = User.objects.create(username="alice", email="alice@upf.edu")
    n = Network.objects.create(code="nfkb_axis", title="NF-κB")
    Subscription.objects.create(user=user, network=n)
    return user, n


@pytest.mark.django_db
class TestStaleNotifications:
    @patch("verify.tasks.send_mail")
    def test_subscribed_user_receives_email(self, mock_send, subscribed_user):
        user, network = subscribed_user
        notify_subscribers_stale(network.id)
        mock_send.assert_called_once()
        kwargs = mock_send.call_args[1]
        assert "alice@upf.edu" in kwargs["recipient_list"]
        assert "NF-κB" in kwargs["subject"] or "NF-κB" in kwargs["message"]
        assert "stale" in kwargs["subject"].lower()

    @patch("verify.tasks.send_mail")
    def test_unsubscribed_user_does_not_receive(
        self, mock_send, db, subscribed_user
    ):
        user, network = subscribed_user
        other_net = Network.objects.create(code="wnt", title="Wnt")
        notify_subscribers_stale(other_net.id)
        mock_send.assert_not_called()

    @patch("verify.tasks.send_mail")
    def test_no_email_to_users_without_email_address(
        self, mock_send, db
    ):
        net = Network.objects.create(code="x", title="X")
        u = User.objects.create(username="noemail", email="")
        Subscription.objects.create(user=u, network=net)
        notify_subscribers_stale(net.id)
        mock_send.assert_not_called()
```

- [ ] **Step 6: Create test in `apps/verify/tests/test_disagreement_digest.py`**

```python
"""Tests for verify.tasks.notify_subscribers_daily_digest."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from graph.models import Conflict, Edge, Entity
from networks.models import Network
from verify.models import Subscription
from verify.tasks import notify_subscribers_daily_digest

User = get_user_model()


@pytest.fixture
def user_with_conflicts(db):
    user = User.objects.create(username="bob", email="bob@upf.edu")
    net = Network.objects.create(code="nfkb_axis", title="NF-κB")
    Subscription.objects.create(user=user, network=net)

    src = Entity.objects.create(symbol="A", canonical_id="hgnc:1")
    tgt = Entity.objects.create(symbol="B", canonical_id="hgnc:2")
    edge = Edge.objects.create(source=src, target=tgt, relation_type="conflicted")
    edge.networks.add(net)
    # Two fresh conflicts in the past 24h
    for _ in range(2):
        Conflict.objects.create(edge=edge, resolution_status="open")
    # One old conflict (outside the window)
    old = Conflict.objects.create(edge=edge, resolution_status="open")
    Conflict.objects.filter(id=old.id).update(
        created_at=timezone.now() - timedelta(days=2)
    )
    return user, net


@pytest.mark.django_db
class TestDailyDigest:
    @patch("verify.tasks.send_mail")
    def test_digest_lists_recent_conflicts(self, mock_send, user_with_conflicts):
        user, _ = user_with_conflicts
        notify_subscribers_daily_digest()
        mock_send.assert_called_once()
        kwargs = mock_send.call_args[1]
        assert kwargs["recipient_list"] == ["bob@upf.edu"]
        # Body mentions 2 new disagreements (the old one is excluded)
        assert "2" in kwargs["message"]

    @patch("verify.tasks.send_mail")
    def test_digest_skipped_when_no_recent_conflicts(self, mock_send, db):
        user = User.objects.create(username="quiet", email="q@upf.edu")
        net = Network.objects.create(code="silent", title="Silent")
        Subscription.objects.create(user=user, network=net)
        notify_subscribers_daily_digest()
        mock_send.assert_not_called()
```

- [ ] **Step 7: Implement the two new tasks in `apps/verify/tasks.py`**

Append:

```python
from django.core.mail import send_mail


@shared_task(queue="q.io")
def notify_subscribers_stale(network_id: int) -> dict:
    """Email every subscriber of ``network_id`` that the network is stale."""
    from networks.models import Network
    from verify.models import Subscription

    network = Network.objects.get(id=network_id)
    subs = (
        Subscription.objects.filter(network=network)
        .select_related("user")
        .exclude(user__email="")
    )
    recipients = [s.user.email for s in subs]
    if not recipients:
        return {"sent": 0}

    send_mail(
        subject=f"[interactome] {network.title} is now STALE — new evidence pending",
        message=(
            f"The {network.title} network ({network.code}) has been marked stale.\n"
            f"New PubMed evidence triggered re-evaluation; the SBML draft will be "
            f"regenerated overnight. Visit https://interactome.simbiosys.sb.upf.edu/"
            f"networks/{network.code}/ to inspect.\n"
        ),
        from_email="interactome@simbiosys.sb.upf.edu",
        recipient_list=recipients,
        fail_silently=True,
    )
    return {"sent": len(recipients)}


@shared_task(queue="q.io")
def notify_subscribers_daily_digest() -> dict:
    """Once daily, email each subscriber the new disagreements in their networks."""
    from datetime import timedelta

    from django.utils import timezone

    from graph.models import Conflict
    from verify.models import Subscription

    cutoff = timezone.now() - timedelta(hours=24)
    by_user: dict[int, dict[int, int]] = {}  # user_id -> network_id -> count

    subs = (
        Subscription.objects.select_related("user", "network")
        .exclude(user__email="")
    )
    for sub in subs:
        n_conflicts = Conflict.objects.filter(
            edge__networks=sub.network,
            created_at__gte=cutoff,
            resolution_status="open",
        ).count()
        if n_conflicts == 0:
            continue
        by_user.setdefault(sub.user_id, {})[sub.network_id] = n_conflicts

    sent = 0
    for user_id, net_counts in by_user.items():
        from django.contrib.auth import get_user_model

        user = get_user_model().objects.get(id=user_id)
        body_lines = [
            f"Hi {user.first_name or user.username},",
            "",
            "New disagreements appeared in networks you subscribe to in the last 24h:",
            "",
        ]
        for net_id, count in net_counts.items():
            from networks.models import Network

            net = Network.objects.get(id=net_id)
            body_lines.append(f"  - {net.title} ({net.code}): {count} new disagreements")
        body_lines += [
            "",
            "Review at https://interactome.simbiosys.sb.upf.edu/dashboard/",
        ]
        send_mail(
            subject="[interactome] Daily disagreement digest",
            message="\n".join(body_lines),
            from_email="interactome@simbiosys.sb.upf.edu",
            recipient_list=[user.email],
            fail_silently=True,
        )
        sent += 1
    return {"sent": sent}
```

- [ ] **Step 8: Run the new tests**

```bash
poetry run pytest apps/verify/tests/test_subscription_notify.py \
                  apps/verify/tests/test_disagreement_digest.py -v
```

Expected: `5 passed`.

- [ ] **Step 9: Commit**

```bash
git add apps/networks/signals.py apps/networks/models.py \
        apps/verify/apps.py apps/verify/receivers.py \
        apps/verify/tasks.py apps/verify/services.py \
        apps/verify/tests/test_subscription_notify.py \
        apps/verify/tests/test_disagreement_digest.py
git commit -m "feat(verify): add subscriber stale + daily-digest notification tasks"
```

---

## Task 11: Dashboard widgets — pause panel + health alerts (TDD-light)

Render the monitoring controls and recent alerts on the existing dashboard
nav so the operator doesn't have to grep the database.

**Files:**
- Modify: `apps/dashboard/templates/dashboard/base.html` (include the pause panel)
- Create: `apps/dashboard/templates/dashboard/partials/health_alerts.html`
- Modify: `apps/dashboard/views.py` (add `health_alerts_panel`)
- Modify: `apps/dashboard/urls.py`
- Create: `apps/dashboard/tests/test_health_alerts_view.py`

- [ ] **Step 1: Add the partial template `apps/dashboard/templates/dashboard/partials/health_alerts.html`**

```html
{# Polled by HTMX every 30s from the dashboard navbar. #}
<div id="health-alerts" hx-get="{% url 'dashboard:health-alerts' %}" hx-trigger="every 30s">
  {% if alerts %}
    <ul class="health-alerts">
      {% for a in alerts %}
        <li class="severity--{{ a.severity }}">
          <strong>{{ a.severity|upper }}</strong> · {{ a.check_name }} ·
          <em>{{ a.created_at|timesince }} ago</em>
          <span>{{ a.message }}</span>
        </li>
      {% endfor %}
    </ul>
  {% else %}
    <span class="health-alerts__none">All systems normal.</span>
  {% endif %}
</div>
```

- [ ] **Step 2: Include both panels in `apps/dashboard/templates/dashboard/base.html`**

Add inside the `<nav>` or navbar block:

```html
{% include "monitoring/pause_panel.html" %}
<div hx-get="{% url 'dashboard:health-alerts' %}" hx-trigger="load">
  Loading health…
</div>
```

- [ ] **Step 3: Implement the view in `apps/dashboard/views.py`**

```python
def health_alerts_panel(request: HttpRequest) -> HttpResponse:
    """Render the recent-open-alerts widget for the dashboard navbar."""
    from monitoring.models import HealthAlert

    alerts = (
        HealthAlert.objects.filter(resolved_at__isnull=True)
        .order_by("-created_at")[:5]
    )
    return render(
        request,
        "dashboard/partials/health_alerts.html",
        {"alerts": alerts},
    )
```

- [ ] **Step 4: Wire the URL in `apps/dashboard/urls.py`**

```python
    path("health-alerts/", views.health_alerts_panel, name="health-alerts"),
```

- [ ] **Step 5: Test in `apps/dashboard/tests/test_health_alerts_view.py`**

```python
"""Tests for the dashboard health-alerts panel."""
from __future__ import annotations

import pytest
from django.test import Client

from monitoring.models import HealthAlert


@pytest.mark.django_db
class TestHealthAlertsPanel:
    def test_empty_state(self):
        c = Client(HTTP_REMOTE_USER="curator")
        r = c.get("/dashboard/health-alerts/")
        assert r.status_code == 200
        assert "All systems normal" in r.content.decode()

    def test_lists_recent_open_alerts(self):
        HealthAlert.objects.create(
            check_name="ollama_unreachable",
            severity="critical",
            message="Connection refused",
        )
        c = Client(HTTP_REMOTE_USER="curator")
        r = c.get("/dashboard/health-alerts/")
        body = r.content.decode()
        assert "ollama_unreachable" in body
        assert "Connection refused" in body

    def test_excludes_resolved_alerts(self):
        a = HealthAlert.objects.create(
            check_name="x", severity="info", message="m"
        )
        a.resolve(by="ops")
        c = Client(HTTP_REMOTE_USER="curator")
        r = c.get("/dashboard/health-alerts/")
        assert "x" not in r.content.decode()
```

- [ ] **Step 6: Run the test**

```bash
poetry run pytest apps/dashboard/tests/test_health_alerts_view.py -v
```

Expected: `3 passed`.

- [ ] **Step 7: Commit**

```bash
git add apps/dashboard/templates/dashboard/ \
        apps/dashboard/views.py apps/dashboard/urls.py \
        apps/dashboard/tests/test_health_alerts_view.py
git commit -m "feat(dashboard): add health-alerts panel and pause-panel include"
```

---

## Task 12: End-to-end integration test — new paper → notification

This is the gold-plated proof that Phase 6 actually works. A synthetic
`Paper` row is inserted with PubTator-annotated content; the test asserts
that the full pipeline triggers, ending with `notify_subscribers_stale`
being called.

To keep the test deterministic we stub the four external boundaries
(NCBI, Europe PMC, PubTator, Ollama) and assert on the internal flow.

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/integration/__init__.py`
- Create: `tests/integration/conftest.py`
- Create: `tests/integration/test_new_paper_end_to_end.py`
- Modify: `pytest.ini` (add `tests` to `testpaths`)

- [ ] **Step 1: Update `pytest.ini`**

```ini
testpaths = apps tests
```

- [ ] **Step 2: Create the empty package files** `tests/__init__.py` and `tests/integration/__init__.py`.

- [ ] **Step 3: Create `tests/integration/conftest.py`**

```python
"""Shared fixtures for cross-app integration tests."""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import pytest


@contextmanager
def _stub_external_calls():
    """Stub every external HTTP boundary so the test runs offline."""
    with patch("corpus.ncbi_client.efetch_metadata") as efetch, \
         patch("corpus.ncbi_client.pubtator_annotations") as pubtator, \
         patch("papers.fulltext_client.fetch_jats_xml") as jats, \
         patch("extract.ollama_client.generate_structured") as ollama:
        efetch.return_value = {
            "pmid": "99999999",
            "title": "SIRT1 deacetylates p65 in NP cells",
            "abstract": "We show that SIRT1 inhibits NF-κB activity.",
            "authors": [{"family": "Doe", "given": "J"}],
            "journal": "Spine",
            "pub_date": "2026-05-01",
            "entrez_date": "2026-05-15",
            "mesh_terms": ["Intervertebral Disc", "NF-kappa B"],
            "publication_types": ["Journal Article"],
        }
        pubtator.return_value = [
            {"text": "SIRT1", "type": "Gene", "id": "23411"},
            {"text": "p65", "type": "Gene", "id": "5970"},
        ]
        jats.return_value = (
            "<article><body><sec sec-type='results'>"
            "<p>SIRT1 deacetylates p65 at K310, inhibiting NF-κB.</p>"
            "</sec></body></article>"
        )
        ollama.return_value = {
            "subject_text": "SIRT1",
            "object_text": "p65",
            "relation": "inhibits",
            "evidence_span": "SIRT1 deacetylates p65 at K310",
            "confidence": 0.91,
        }
        yield {
            "efetch": efetch,
            "pubtator": pubtator,
            "jats": jats,
            "ollama": ollama,
        }


@pytest.fixture
def stub_externals():
    with _stub_external_calls() as stubs:
        yield stubs
```

- [ ] **Step 4: Create `tests/integration/test_new_paper_end_to_end.py`**

```python
"""End-to-end Phase 6 integration test.

Inserts a synthetic Paper row mimicking PubTator-annotated content
and verifies the full chain runs:

    classify → fetch → section → extract (≥1 model) → integrate
        → mark affected network stale
        → SBML regen scheduled
        → email notification fired

External services (NCBI/EuropePMC/PubTator/Ollama) are stubbed via
``tests/integration/conftest.py::stub_externals``. Every Celery task
runs eagerly (``CELERY_TASK_ALWAYS_EAGER=True``).
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model

from corpus.models import Paper, PaperRelevance
from corpus.tasks import ingest_paper
from extract.models import ExtractionRun, RawPPI
from graph.models import Edge, NetworkEdgeMembership
from networks.models import Network
from papers.models import Chunk, Section
from verify.models import Subscription

User = get_user_model()


@pytest.fixture
def eager_celery(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True


@pytest.fixture
def network_with_subscriber(db):
    net = Network.objects.create(
        code="nfkb_axis",
        title="NF-κB Axis",
        keywords=["NF-κB", "SIRT1", "p65"],
    )
    user = User.objects.create(username="alice", email="alice@upf.edu")
    Subscription.objects.create(user=user, network=net)
    return net, user


@pytest.mark.django_db
def test_new_paper_propagates_to_notification(
    eager_celery, stub_externals, network_with_subscriber
):
    net, user = network_with_subscriber

    # --- ACT: drive the ingest task with a synthetic PMID ---
    with patch("verify.tasks.send_mail") as mock_send, \
         patch("sbml.tasks.regenerate_stale_networks.delay") as mock_sbml_regen:
        ingest_paper("99999999")

    # --- ASSERT: every stage left its trail ---
    paper = Paper.objects.get(pmid="99999999")

    # 1. classify_original → is_original=True
    assert paper.is_original is True

    # 2. fetch_fulltext → at least one Section
    assert Section.objects.filter(paper=paper).exists()

    # 3. section_and_chunk → at least one Chunk
    assert Chunk.objects.filter(section__paper=paper).exists()

    # 4. per-network relevance triage produced PaperRelevance rows
    relevance = PaperRelevance.objects.get(paper=paper, network=net)
    assert relevance.score >= 0.5

    # 5. detect_affected_networks added a pending NetworkEdgeMembership row
    assert NetworkEdgeMembership.objects.filter(
        network=net, pending_paper_id=paper.id, pending_extraction=True
    ).exists()

    # 6. At least one ExtractionRun produced a RawPPI
    assert ExtractionRun.objects.filter(chunk__section__paper=paper, status="done").exists()
    assert RawPPI.objects.filter(run__chunk__section__paper=paper).exists()

    # 7. graph.integrate_pending produced an Edge
    assert Edge.objects.filter(
        source__symbol__iexact="SIRT1",
        target__symbol__iexact="p65",
    ).exists()

    # 8. Network is now stale (transitioned by integration)
    net.refresh_from_db()
    assert net.pipeline_status == "stale"

    # 9. SBML regen was scheduled
    assert mock_sbml_regen.called

    # 10. Subscriber email was fired
    mock_send.assert_called()
    sent_kwargs = mock_send.call_args[1]
    assert "alice@upf.edu" in sent_kwargs["recipient_list"]
    assert "NF-κB" in sent_kwargs["subject"] or "NF-κB" in sent_kwargs["message"]


@pytest.mark.django_db
def test_pause_flag_halts_the_chain(
    eager_celery, stub_externals, network_with_subscriber
):
    """When INGESTION_PAUSED is on, refresh_pubmed skips and no Paper appears."""
    from corpus.tasks import refresh_pubmed
    from monitoring import services

    services.set_ingestion_paused(True, by="ops", reason="integration test")

    with patch("corpus.tasks._do_refresh_pubmed") as mock_do:
        result = refresh_pubmed()

    assert mock_do.called is False
    assert result == {"skipped": True, "reason": "ingestion_paused"}
    assert Paper.objects.count() == 0
```

- [ ] **Step 5: Run the integration test**

```bash
poetry run pytest tests/integration/ -v -s
```

Expected: `2 passed`. If the test fails at any stage, the assertion
message will pinpoint which downstream task did not fire — that is the
expected debugging signal, not a flake. Fix the wiring (most likely a
missing `transaction.on_commit` or an unconnected receiver) and re-run.

- [ ] **Step 6: Commit**

```bash
git add tests/ pytest.ini
git commit -m "test: add end-to-end Phase 6 integration test (new paper → notification)"
```

---

## Task 13: Stack verification + Beat schedule smoke test

This is the "all-up" Phase 6 verification, equivalent to Task 14 of
Phase 0 but against the full Phase 1–6 stack.

- [ ] **Step 1: Run the full pytest suite**

```bash
poetry run ruff check .
poetry run ruff format --check .
poetry run mypy apps interactome
poetry run pytest -v
```

All four commands must return exit code 0.

- [ ] **Step 2: Bring up the docker-compose stack**

```bash
docker-compose up -d
docker-compose ps
```

All containers from Phases 1–5 should be `Up (healthy)`. Phase 6 adds
no new containers.

- [ ] **Step 3: Verify Beat is firing the new tasks**

Wait 16 minutes (one healthcheck cadence), then:

```bash
docker-compose exec web python manage.py shell -c \
  "from monitoring.models import HealthAlert; \
   from schedule.models import Watermark; \
   print('alerts:', HealthAlert.objects.count()); \
   print('beat_heartbeat:', Watermark.objects.filter(source='beat_heartbeat').first())"
```

Expected: the `beat_heartbeat` Watermark row exists and has a recent
`last_success_at`. Alerts may or may not be present depending on the
real Ollama / PubMed availability — both outcomes are acceptable, as
long as `beat_heartbeat` is fresh.

- [ ] **Step 4: Verify the pause/resume endpoint via HTTP**

```bash
# Pause:
curl -sk -X POST -H 'Remote-User: curator' -H 'Remote-Groups: curators' \
  -d 'reason=verification' \
  https://localhost/admin/monitoring/pause/

# Confirm:
docker-compose exec web python manage.py shell -c \
  "from monitoring.services import is_ingestion_paused; print(is_ingestion_paused())"
# → True

# Resume:
curl -sk -X POST -H 'Remote-User: curator' -H 'Remote-Groups: curators' \
  -d 'reason=resumed' \
  https://localhost/admin/monitoring/resume/

# Confirm:
docker-compose exec web python manage.py shell -c \
  "from monitoring.services import is_ingestion_paused; print(is_ingestion_paused())"
# → False
```

- [ ] **Step 5: Bring the stack down**

```bash
docker-compose down
```

- [ ] **Step 6: Push and verify GitHub Actions CI is green**

```bash
git push origin main
```

Open the Actions tab; the run should be green within ~5 minutes.

- [ ] **Step 7: Tag the Phase 6 release**

```bash
git tag -a phase-6-complete -m "Phase 6 (Continuous Monitoring) complete

Working features:
- monitoring app with HealthAlert and FeatureFlag models
- 15-min healthcheck task probing pubmed freshness / ollama reachability / postgres latency
- Admin pause/resume HTMX endpoints with audit trail
- corpus.refresh_pubmed and extract.enqueue_pending_chunks honour INGESTION_PAUSED
- Backpressure: refresh_pubmed pauses when extract queue >= 10k
- paper_ingested signal → graph.detect_affected_networks(paper_id)
- Auto-conflict resolver: medgemma:27b re-reads low-confidence conflicts every 30 min with 1h buffer
- Stale-on-transition subscriber email + daily disagreement digest
- Dashboard health-alerts panel + pause-panel widget
- End-to-end integration test: new paper → notification

Next: Phase 7 (Hardening + handoff) — pgbackrest, Sentry, runbook,
biologist onboarding, first sign-off."

git push origin phase-6-complete
```

---

## Phase 6 Self-Review

**Spec coverage check** (against `docs/superpowers/specs/2026-05-19-disc-interactome-app-design.md`):

- Section 1 ("All persistent state lives in Postgres") — `HealthAlert` and `FeatureFlag` are Postgres rows; pause flag is a row, not a Redis key. Continuous-service runtime mode is now realised: every Beat task short-circuits cleanly on pause, all monitoring is read from rows, no in-memory globals.
- Section 4 (per-paper pipeline) — `paper_ingested` signal + `detect_affected_networks` close the loop between corpus ingest and the downstream STALE-network propagation, completing the diagram's "fans out" → "chunk completion triggers" → "STALE networks" flow as a fully wired chain.
- Section 6 (Celery topology + Beat schedule) — four new Beat entries added (`monitoring.healthcheck` 15 min, `verify.sweep_open_conflicts` 30 min, `verify.notify_subscribers_daily_digest` daily 09:00 UTC, `schedule.assert_beat_alive` 1 min). All routed to `q.io` except `auto_resolve` which runs on `q.extract.medgemma_27b` to keep the model hot. No new queues, no new worker processes.
- Section 7 (Verification UI subscription notifications) — `notify_subscribers_stale` on state transition, `notify_subscribers_daily_digest` for batched disagreements. Both use the existing `Subscription` model from Phase 5.
- Section 8 (resumability) — auto-resolve uses the standard `select_for_update` + `status` short-circuit pattern. Conflict rows go from `open → auto_resolved` exactly once; idempotent on re-run. No new janitor needed because the existing `schedule.janitor_reset_stale_running` already covers the new tasks.
- Section 10 (roadmap) — every concrete subsystem listed in the Phase 6 brief is covered: daily delta detection, auto-conflict resolver with exact prompt + JSON schema, subscribe-to-network notifications (both modes), health monitoring, backpressure, pause/resume, end-to-end integration test. The 13 tasks correspond to the "mostly orchestration glue" character of Phase 6.

**Cross-phase dependency check:**

| Phase | Component reused | Component extended in this phase |
|---|---|---|
| Phase 1 | `corpus.refresh_pubmed`, `Paper.PaperRelevance`, `Watermark` | refresh_pubmed wrapped with pause + backpressure short-circuit; new `paper_ingested` signal |
| Phase 2 | `ExtractionRun`, `RawPPI`, `extract.enqueue_pending_chunks`, `extract.ollama_client.generate_structured` | enqueue_pending_chunks wrapped with pause short-circuit; ollama_client reused by auto_resolve |
| Phase 3 | `graph.integrate_pending`, `Edge`, `Conflict`, `NetworkEdgeMembership` | new `detect_affected_networks` task; `Conflict` gains `reasoning`, `resolved_relation`, `resolved_at`, `auto_resolve_attempted_at` columns; `NetworkEdgeMembership` gains `pending_paper_id`, `pending_extraction` columns |
| Phase 4 | `sbml.regenerate_stale_networks`, `ModelVersion`, Network state machine | network_status_changed signal fired from `Network.transition_to` |
| Phase 5 | `verify.notify`, `Subscription`, `Review`, `Signoff` | reused as-is; two new subscriber-facing tasks (`notify_subscribers_stale`, `notify_subscribers_daily_digest`) |
| schedule | `Watermark`, `CELERY_BEAT_SCHEDULE`, janitor | 4 new Beat entries; new `assert_beat_alive` heartbeat task |

**Placeholder scan:** No "TBD"/"TODO"/"implement later" strings in any task. Every step contains either complete code, a complete command, or a single concrete file action. The two private helpers carried forward from earlier phases (`_do_refresh_pubmed`, `_do_enqueue_pending_chunks`) are referenced by name only because their bodies were authored in Phases 1 and 2 — Phase 6 deliberately does not re-author them, only wraps them.

**Type consistency:** `FeatureFlag`, `HealthAlert`, `auto_resolve`, `detect_affected_networks`, `sweep_open_conflicts`, `notify_subscribers_stale`, `notify_subscribers_daily_digest`, `is_ingestion_paused`, `is_backpressured` are referenced identically in tests, implementation, Beat schedule, settings, and the end-to-end test. The prompt template variable names (`subject_symbol`, `relation_a`, `confidence_b`, etc.) match between `prompts.py` and the `.format()` call site in `auto_resolve`.

**Prompt + schema explicitness:** The exact `CONFLICT_REREAD_PROMPT` text and `CONFLICT_REREAD_SCHEMA` JSON schema are present in full inside Task 8 — the spec requires no placeholders for this critical artifact. The confidence threshold (0.85) is a named module-level constant so curators can tune it without touching task code.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-19-phase-6-continuous-monitoring.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration. Phase 6 is small enough (13 tasks, mostly glue) that this can complete in one work day with parallel agents on independent tasks (e.g. Tasks 4, 8, and 10 have no inter-dependencies and can run concurrently).

**2. Inline Execution** — execute tasks in this session using `executing-plans`, batch execution with checkpoints for review.

**Recommended task ordering when parallelising:**
1. Task 1 (scaffold monitoring app) — strict prerequisite for everything else
2. Task 2 (models) and Task 3 (services) — sequential, in this app
3. **Parallel batch**: Task 4 (healthcheck), Task 7 (detect_affected_networks), Task 8 (auto_resolve), Task 10 (subscriber notifications) — independent
4. Task 5 (pause/resume views) — depends on Task 3
5. Task 6 (wire pause into corpus + extract) — depends on Task 3
6. Task 9 (Beat schedule additions) — depends on Tasks 4, 8, and 10
7. Task 11 (dashboard widgets) — depends on Tasks 2 and 5
8. Task 12 (end-to-end integration test) — must run last; depends on every prior task
9. Task 13 (stack verification + tag) — final

**Which approach?**
