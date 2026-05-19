# Phase 0: Foundation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring up the empty Django + Celery + Postgres + Redis + MinIO + Caddy + GROBID stack with Authelia SSO middleware wired, a health endpoint that returns the authenticated user, all common dev tooling (pytest, ruff, mypy), and green CI. No domain logic. End state: `docker-compose up -d` brings 9 containers online; `curl -H 'Remote-User: fchemorion' http://localhost:8000/health/` returns 200 with the user identity.

**Architecture:** Single Django project at the repo root. One internal Django app (`core`) holding shared abstractions: `AutheliaRemoteUserMiddleware`, `TimestampedModel` abstract base, the health endpoint, and the Celery smoke task. Celery is fully wired (Beat + worker_io) but no domain tasks yet. All services live in one `docker-compose.yml`; Caddy fronts Django with `forward_auth` to the existing Authelia gateway.

**Tech Stack:** Python 3.12, Django 5.0, Celery 5.3, django-celery-beat 2.6, PostgreSQL 16, Redis 7, MinIO RELEASE.2024-10-13T13-34-11Z, Caddy 2.8, GROBID 0.8.0, Docker Compose v2, pytest 8 + pytest-django 4.8, ruff 0.6, mypy 1.10, GitHub Actions.

**Reference spec:** `docs/superpowers/specs/2026-05-19-disc-interactome-app-design.md` Sections 1, 2, 8, 9.

---

## File Structure After Phase 0

```
/                                       (git repo root)
├── pyproject.toml                      Poetry-managed Python project
├── poetry.lock                         locked dependencies
├── .python-version                     pyenv version pin → 3.12
├── .gitignore                          Python/Django/Docker patterns
├── .editorconfig                       4-space Python, 2-space YAML
├── .env.example                        documented env vars; never committed live
├── .ruff.toml                          ruff lint + format config
├── mypy.ini                            mypy strict config
├── pytest.ini                          pytest-django config
├── docker-compose.yml                  9-service stack for Phase 0
├── Dockerfile                          shared image for web + workers + beat
├── Caddyfile                           reverse proxy + forward_auth
├── manage.py                           Django management entrypoint
├── README.md                           quickstart + dev workflow
├── interactome/                        Django project package
│   ├── __init__.py                     loads Celery app
│   ├── celery.py                       Celery app definition
│   ├── settings/
│   │   ├── __init__.py                 reads DJANGO_SETTINGS_MODULE
│   │   ├── base.py                     installed apps, middleware, DB, Celery
│   │   ├── dev.py                      DEBUG=True, console emails
│   │   └── production.py               DEBUG=False, env-driven secrets
│   ├── urls.py                         project URL conf — includes core.urls
│   ├── wsgi.py                         gunicorn entrypoint
│   └── asgi.py                         for future async support
├── apps/                               internal Django apps
│   ├── __init__.py                     namespace package
│   └── core/
│       ├── __init__.py
│       ├── apps.py                     CoreConfig with default_auto_field
│       ├── middleware.py               AutheliaRemoteUserMiddleware
│       ├── models.py                   TimestampedModel abstract base
│       ├── tasks.py                    smoke_ping Celery task
│       ├── urls.py                     /health/ route
│       ├── views.py                    health endpoint
│       ├── migrations/
│       │   └── __init__.py
│       └── tests/
│           ├── __init__.py
│           ├── conftest.py             shared fixtures
│           ├── test_middleware.py      authelia middleware behaviour
│           ├── test_models.py          TimestampedModel timestamps update
│           ├── test_tasks.py           Celery smoke task runs
│           └── test_views.py           /health/ returns 200 + user
└── .github/
    └── workflows/
        └── ci.yml                      lint + tests on push/PR
```

**Why this layout:**
- `apps/` is a flat directory of Django apps; each app is a Python package. Settings adds `apps/` to `sys.path` so `INSTALLED_APPS = ["core", ...]` works (not `apps.core`). This matches the spec's app-boundary discipline (Section 2) — apps stay siblings, no nesting.
- `interactome/` is the Django *project* (settings + URL conf + Celery), not an app.
- Tests live alongside each app, not in a top-level `tests/`. This is the Django-pytest idiom and keeps tests next to the code they exercise.
- All Phase 0 tests live in `apps/core/tests/`. Later phases each create their own `apps/<app>/tests/`.

---

## Task 1: Initialize Python project

**Files:**
- Create: `pyproject.toml`
- Create: `.python-version`
- Create: `.gitignore`
- Create: `.editorconfig`

- [ ] **Step 1: Create `.python-version`**

Write the content `3.12` (single line, no trailing whitespace).

```
3.12
```

- [ ] **Step 2: Create `pyproject.toml`**

```toml
[tool.poetry]
name = "interactome"
version = "0.1.0"
description = "Autonomous PubMed → SBML-qual pipeline for intervertebral disc regulatory networks."
authors = ["Francis Chemorion <francis.chemorion@upf.edu>"]
readme = "README.md"
package-mode = false

[tool.poetry.dependencies]
python = "^3.12"
django = "^5.0"
celery = {extras = ["redis"], version = "^5.3"}
django-celery-beat = "^2.6"
django-celery-results = "^2.5"
psycopg = {extras = ["binary"], version = "^3.2"}
redis = "^5.0"
gunicorn = "^23.0"
requests = "^2.32"
structlog = "^24.4"
django-structlog = "^9.0"
python-dotenv = "^1.0"

[tool.poetry.group.dev.dependencies]
pytest = "^8.3"
pytest-django = "^4.8"
pytest-cov = "^5.0"
pytest-mock = "^3.14"
ruff = "^0.6"
mypy = "^1.10"
django-stubs = {extras = ["compatible-mypy"], version = "^5.0"}
types-requests = "^2.32"

[build-system]
requires = ["poetry-core"]
build-backend = "poetry.core.masonry.api"
```

- [ ] **Step 3: Create `.gitignore`**

```
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
*.egg-info/
.eggs/
.installed.cfg
dist/
build/
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
htmlcov/
.tox/
.nox/

# Virtual environments
.venv/
venv/
env/
ENV/

# Poetry
# (commit poetry.lock; don't ignore it)

# Django
*.log
db.sqlite3
db.sqlite3-journal
media/
staticfiles/
local_settings.py

# Environment
.env
.env.local
.env.*.local
!.env.example

# IDE
.idea/
.vscode/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db

# Docker volumes (when running locally outside compose)
pgdata/
redisdata/
miniodata/
backupdata/
```

- [ ] **Step 4: Create `.editorconfig`**

```ini
root = true

[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true

[*.py]
indent_style = space
indent_size = 4
max_line_length = 100

[*.{yml,yaml,toml}]
indent_style = space
indent_size = 2

[*.md]
trim_trailing_whitespace = false

[Makefile]
indent_style = tab
```

- [ ] **Step 5: Install dependencies**

Run:
```bash
cd /Users/kiptengwer/Downloads/interactome
poetry install
```

Expected output (last line):
```
Installing the current project: interactome (0.1.0)
```

If `poetry` is not installed, install it first via the official installer at `https://python-poetry.org/docs/#installation`.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml poetry.lock .python-version .gitignore .editorconfig
git commit -m "build: initialize Python project with Poetry"
```

---

## Task 2: Django project skeleton

**Files:**
- Create: `manage.py`
- Create: `interactome/__init__.py`
- Create: `interactome/celery.py`
- Create: `interactome/settings/__init__.py`
- Create: `interactome/settings/base.py`
- Create: `interactome/settings/dev.py`
- Create: `interactome/settings/production.py`
- Create: `interactome/urls.py`
- Create: `interactome/wsgi.py`
- Create: `interactome/asgi.py`
- Create: `apps/__init__.py`

- [ ] **Step 1: Create `manage.py`**

```python
#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys
from pathlib import Path


def main() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent / "apps"))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "interactome.settings.dev")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you in the Poetry shell?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
```

Make it executable:
```bash
chmod +x manage.py
```

- [ ] **Step 2: Create `interactome/__init__.py`**

```python
"""interactome Django project package."""
from interactome.celery import app as celery_app

__all__ = ("celery_app",)
```

- [ ] **Step 3: Create `interactome/celery.py`**

```python
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
```

- [ ] **Step 4: Create `interactome/settings/__init__.py`**

```python
"""Settings package. Selection happens via DJANGO_SETTINGS_MODULE env var.

- ``interactome.settings.dev`` is the local-development default.
- ``interactome.settings.production`` is what gunicorn loads in the
  container.

Never import ``base`` directly; always go through one of the leaf
modules so all overrides are applied consistently.
"""
```

- [ ] **Step 5: Create `interactome/settings/base.py`**

```python
"""Base Django settings shared across all environments.

Subclasses (``dev.py``, ``production.py``) override the few values
that differ per environment.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
APPS_DIR = BASE_DIR / "apps"
sys.path.insert(0, str(APPS_DIR))

SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "insecure-dev-key-do-not-use-in-production",
)
DEBUG = False
ALLOWED_HOSTS: list[str] = []

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_celery_beat",
    "django_celery_results",
    # Local apps
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core.middleware.AutheliaRemoteUserMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "interactome.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "interactome.wsgi.application"
ASGI_APPLICATION = "interactome.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "interactome"),
        "USER": os.environ.get("POSTGRES_USER", "interactome"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "interactome"),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 60,
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Celery
CELERY_BROKER_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = "django-db"
CELERY_CACHE_BACKEND = "django-cache"
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 60 * 60  # 1 hour hard limit
CELERY_TASK_SOFT_TIME_LIMIT = 60 * 50  # soft 50 min — task can clean up

# Logging
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "structlog.stdlib.ProcessorFormatter",
            "processor": "structlog.dev.ConsoleRenderer",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "celery": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
```

- [ ] **Step 6: Create `interactome/settings/dev.py`**

```python
"""Development settings."""
from __future__ import annotations

from interactome.settings.base import *  # noqa: F401,F403

DEBUG = True
ALLOWED_HOSTS = ["*"]
SECRET_KEY = "dev-secret-not-for-production"

# Allow the Authelia middleware to short-circuit to a fake user in dev
# when no Remote-User header is present.
AUTHELIA_DEV_FAKE_USER = "fchemorion"

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Disable HTTPS-only cookies in dev.
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
```

- [ ] **Step 7: Create `interactome/settings/production.py`**

```python
"""Production settings — everything secret comes from the environment."""
from __future__ import annotations

import os

from interactome.settings.base import *  # noqa: F401,F403

DEBUG = False
ALLOWED_HOSTS = os.environ["DJANGO_ALLOWED_HOSTS"].split(",")
SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]

# Strict cookie + HTTPS settings — Caddy terminates TLS in front.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30  # 30 days
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = False

# No dev fallback user in production.
AUTHELIA_DEV_FAKE_USER = None
```

- [ ] **Step 8: Create `interactome/urls.py`**

```python
"""Top-level URL conf. Each app contributes via its own ``urls.py``."""
from __future__ import annotations

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("core.urls")),
]
```

- [ ] **Step 9: Create `interactome/wsgi.py`**

```python
"""WSGI config — gunicorn's entrypoint in production."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apps"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "interactome.settings.production")

from django.core.wsgi import get_wsgi_application  # noqa: E402

application = get_wsgi_application()
```

- [ ] **Step 10: Create `interactome/asgi.py`**

```python
"""ASGI config — for future async views."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "apps"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "interactome.settings.production")

from django.core.asgi import get_asgi_application  # noqa: E402

application = get_asgi_application()
```

- [ ] **Step 11: Create `apps/__init__.py`**

Empty file so Python treats `apps/` as a namespace package container:
```python
```

- [ ] **Step 12: Verify Django can boot**

Run:
```bash
poetry run python manage.py check
```

Expected output:
```
System check identified no issues (0 silenced).
```

(The `core` app doesn't exist yet so this will fail. Acceptable — proceed to Task 3.)

- [ ] **Step 13: Commit (partial — Django skeleton, no core app yet)**

```bash
git add manage.py interactome/ apps/__init__.py
git commit -m "feat: scaffold Django project structure"
```

---

## Task 3: Create the `core` Django app

**Files:**
- Create: `apps/core/__init__.py`
- Create: `apps/core/apps.py`
- Create: `apps/core/models.py`
- Create: `apps/core/views.py`
- Create: `apps/core/urls.py`
- Create: `apps/core/middleware.py`
- Create: `apps/core/tasks.py`
- Create: `apps/core/migrations/__init__.py`
- Create: `apps/core/tests/__init__.py`

- [ ] **Step 1: Create `apps/core/__init__.py`**

```python
"""core — shared utilities, base models, and middleware.

This app must depend on nothing else; everything else can depend on it.
"""
```

- [ ] **Step 2: Create `apps/core/apps.py`**

```python
"""Django AppConfig for the core app."""
from __future__ import annotations

from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"
    verbose_name = "Core (shared abstractions)"
```

- [ ] **Step 3: Create `apps/core/migrations/__init__.py`** (empty file).

- [ ] **Step 4: Create empty placeholder modules so imports don't fail**

`apps/core/models.py`:
```python
"""Core models — abstract bases and shared concrete models."""
```

`apps/core/views.py`:
```python
"""Core views."""
```

`apps/core/urls.py`:
```python
"""Core URL routes."""
from __future__ import annotations

from django.urls import path

app_name = "core"
urlpatterns: list = []
```

`apps/core/middleware.py`:
```python
"""Core middleware — Authelia SSO integration lives here."""
```

`apps/core/tasks.py`:
```python
"""Core Celery tasks — shared utility tasks like janitor sweeps."""
```

`apps/core/tests/__init__.py` (empty file).

- [ ] **Step 5: Verify Django can boot**

```bash
poetry run python manage.py check
```

Expected output:
```
System check identified no issues (0 silenced).
```

- [ ] **Step 6: Commit**

```bash
git add apps/core/
git commit -m "feat(core): scaffold core app"
```

---

## Task 4: TimestampedModel abstract base model (TDD)

The spec (Section 3) requires every persistent unit of work to be auditable.
Every concrete model in every future app will inherit `created_at` and
`updated_at` from `TimestampedModel`.

**Files:**
- Create: `apps/core/tests/conftest.py`
- Create: `apps/core/tests/test_models.py`
- Modify: `apps/core/models.py`
- Create: `pytest.ini`

- [ ] **Step 1: Create `pytest.ini`**

```ini
[pytest]
DJANGO_SETTINGS_MODULE = interactome.settings.dev
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = --strict-markers --strict-config --tb=short
filterwarnings =
    error
    ignore::DeprecationWarning:celery.*
    ignore::DeprecationWarning:kombu.*
testpaths = apps
```

- [ ] **Step 2: Create `apps/core/tests/conftest.py`**

```python
"""Shared pytest fixtures for the core app."""
from __future__ import annotations

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.fixture
def db_executor() -> MigrationExecutor:
    """Allows tests to dynamically create models for abstract-base tests."""
    return MigrationExecutor(connection)
```

- [ ] **Step 3: Write the failing test in `apps/core/tests/test_models.py`**

```python
"""Tests for core.models."""
from __future__ import annotations

import time

import pytest
from django.db import connection, models

from core.models import TimestampedModel


class _ConcreteTimestamped(TimestampedModel):
    """A throwaway concrete subclass to exercise the abstract base."""

    name = models.CharField(max_length=32)

    class Meta:
        app_label = "core"


@pytest.fixture(autouse=True)
def _create_concrete_table(db):
    with connection.schema_editor() as schema_editor:
        schema_editor.create_model(_ConcreteTimestamped)
    yield
    with connection.schema_editor() as schema_editor:
        schema_editor.delete_model(_ConcreteTimestamped)


def test_timestamped_model_sets_created_at_on_insert(db):
    instance = _ConcreteTimestamped.objects.create(name="alpha")
    assert instance.created_at is not None


def test_timestamped_model_sets_updated_at_on_insert(db):
    instance = _ConcreteTimestamped.objects.create(name="alpha")
    assert instance.updated_at is not None


def test_timestamped_model_updates_updated_at_on_save(db):
    instance = _ConcreteTimestamped.objects.create(name="alpha")
    original_updated_at = instance.updated_at
    time.sleep(0.01)
    instance.name = "beta"
    instance.save()
    assert instance.updated_at > original_updated_at


def test_timestamped_model_does_not_change_created_at_on_save(db):
    instance = _ConcreteTimestamped.objects.create(name="alpha")
    original_created_at = instance.created_at
    instance.name = "beta"
    instance.save()
    assert instance.created_at == original_created_at
```

- [ ] **Step 4: Run the test to verify it fails**

```bash
poetry run pytest apps/core/tests/test_models.py -v
```

Expected:
```
ImportError while loading conftest ...
ImportError: cannot import name 'TimestampedModel' from 'core.models'
```

(Or a similar "cannot import" error. Confirming the test does NOT silently pass.)

- [ ] **Step 5: Implement `TimestampedModel` in `apps/core/models.py`**

Replace the placeholder content with:

```python
"""Core models — abstract bases and shared concrete models."""
from __future__ import annotations

from django.db import models


class TimestampedModel(models.Model):
    """Abstract base that adds ``created_at`` and ``updated_at``.

    Every concrete model in the project should inherit from this so that
    audit timestamps are uniform across the schema.
    """

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        abstract = True
```

- [ ] **Step 6: Run the test to verify it passes**

```bash
poetry run pytest apps/core/tests/test_models.py -v
```

Expected:
```
test_timestamped_model_sets_created_at_on_insert PASSED
test_timestamped_model_sets_updated_at_on_insert PASSED
test_timestamped_model_updates_updated_at_on_save PASSED
test_timestamped_model_does_not_change_created_at_on_save PASSED

4 passed
```

If tests skip with "no database" — verify your local Postgres is reachable
or temporarily use SQLite in dev settings.

- [ ] **Step 7: Commit**

```bash
git add apps/core/models.py apps/core/tests/test_models.py apps/core/tests/conftest.py pytest.ini
git commit -m "feat(core): add TimestampedModel abstract base"
```

---

## Task 5: AutheliaRemoteUserMiddleware (TDD)

The spec (Section 9) requires Django to honour the `Remote-User` header
set by Authelia after successful auth at the Caddy front. In dev, with no
Authelia in the path, fall back to a configurable fake user.

**Files:**
- Create: `apps/core/tests/test_middleware.py`
- Modify: `apps/core/middleware.py`

- [ ] **Step 1: Write the failing test in `apps/core/tests/test_middleware.py`**

```python
"""Tests for core.middleware.AutheliaRemoteUserMiddleware."""
from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import RequestFactory, override_settings

from core.middleware import AutheliaRemoteUserMiddleware

User = get_user_model()


@pytest.fixture
def factory() -> RequestFactory:
    return RequestFactory()


@pytest.fixture
def middleware():
    return AutheliaRemoteUserMiddleware(lambda r: HttpResponse("ok"))


def test_middleware_creates_user_from_remote_user_header(db, factory, middleware):
    request = factory.get("/health/", HTTP_REMOTE_USER="fchemorion")
    request.session = {}
    middleware(request)
    assert User.objects.filter(username="fchemorion").exists()


def test_middleware_attaches_user_to_request(db, factory, middleware):
    request = factory.get("/health/", HTTP_REMOTE_USER="fchemorion")
    request.session = {}
    middleware(request)
    assert request.user.username == "fchemorion"


def test_middleware_sets_email_from_remote_email_header(db, factory, middleware):
    request = factory.get(
        "/health/",
        HTTP_REMOTE_USER="fchemorion",
        HTTP_REMOTE_EMAIL="francis.chemorion@upf.edu",
    )
    request.session = {}
    middleware(request)
    request.user.refresh_from_db()
    assert request.user.email == "francis.chemorion@upf.edu"


def test_middleware_sets_full_name_from_remote_name_header(db, factory, middleware):
    request = factory.get(
        "/health/",
        HTTP_REMOTE_USER="fchemorion",
        HTTP_REMOTE_NAME="Francis Chemorion",
    )
    request.session = {}
    middleware(request)
    request.user.refresh_from_db()
    assert request.user.first_name == "Francis"
    assert request.user.last_name == "Chemorion"


def test_middleware_assigns_groups_from_remote_groups_header(db, factory, middleware):
    request = factory.get(
        "/health/",
        HTTP_REMOTE_USER="fchemorion",
        HTTP_REMOTE_GROUPS="simbiosys-lab,curators",
    )
    request.session = {}
    middleware(request)
    request.user.refresh_from_db()
    group_names = set(request.user.groups.values_list("name", flat=True))
    assert group_names == {"simbiosys-lab", "curators"}


def test_middleware_idempotent_on_repeated_requests(db, factory, middleware):
    request = factory.get("/health/", HTTP_REMOTE_USER="fchemorion")
    request.session = {}
    middleware(request)
    middleware(request)
    assert User.objects.filter(username="fchemorion").count() == 1


@override_settings(AUTHELIA_DEV_FAKE_USER="fchemorion")
def test_middleware_uses_dev_fallback_when_no_header(db, factory, middleware):
    request = factory.get("/health/")  # no Remote-User header
    request.session = {}
    middleware(request)
    assert request.user.username == "fchemorion"


@override_settings(AUTHELIA_DEV_FAKE_USER=None)
def test_middleware_anonymous_when_no_header_and_no_fallback(db, factory, middleware):
    request = factory.get("/health/")
    request.session = {}
    middleware(request)
    assert request.user.is_anonymous
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
poetry run pytest apps/core/tests/test_middleware.py -v
```

Expected:
```
ImportError: cannot import name 'AutheliaRemoteUserMiddleware' from 'core.middleware'
```

- [ ] **Step 3: Implement the middleware in `apps/core/middleware.py`**

```python
"""Authelia SSO middleware.

Reads the ``Remote-User``, ``Remote-Email``, ``Remote-Name``, and
``Remote-Groups`` headers set by Authelia after a successful upstream
auth at the Caddy reverse proxy. Creates or updates the corresponding
Django ``User`` and attaches it to ``request.user``.

In development, falls back to ``settings.AUTHELIA_DEV_FAKE_USER`` if
no header is present, so the app remains usable when run outside
docker-compose.
"""
from __future__ import annotations

from typing import Callable

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Group
from django.http import HttpRequest, HttpResponse

User = get_user_model()


class AutheliaRemoteUserMiddleware:
    """Middleware factory in Django's new-style ``(get_response)`` form."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        username = request.META.get("HTTP_REMOTE_USER")
        if not username:
            username = getattr(settings, "AUTHELIA_DEV_FAKE_USER", None)

        if username:
            user = self._upsert_user(
                username=username,
                email=request.META.get("HTTP_REMOTE_EMAIL", ""),
                full_name=request.META.get("HTTP_REMOTE_NAME", ""),
                groups_csv=request.META.get("HTTP_REMOTE_GROUPS", ""),
            )
            request.user = user
        else:
            request.user = AnonymousUser()

        return self.get_response(request)

    @staticmethod
    def _upsert_user(
        *,
        username: str,
        email: str,
        full_name: str,
        groups_csv: str,
    ) -> User:
        user, _ = User.objects.get_or_create(username=username)
        changed = False

        if email and user.email != email:
            user.email = email
            changed = True

        if full_name:
            first, _, last = full_name.partition(" ")
            if user.first_name != first:
                user.first_name = first
                changed = True
            if user.last_name != last:
                user.last_name = last
                changed = True

        if changed:
            user.save()

        if groups_csv:
            wanted = {g.strip() for g in groups_csv.split(",") if g.strip()}
            current = set(user.groups.values_list("name", flat=True))
            for name in wanted - current:
                group, _ = Group.objects.get_or_create(name=name)
                user.groups.add(group)
            for name in current - wanted:
                user.groups.remove(Group.objects.get(name=name))

        return user
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
poetry run pytest apps/core/tests/test_middleware.py -v
```

Expected:
```
8 passed
```

- [ ] **Step 5: Commit**

```bash
git add apps/core/middleware.py apps/core/tests/test_middleware.py
git commit -m "feat(core): add AutheliaRemoteUserMiddleware"
```

---

## Task 6: Health check endpoint (TDD)

A simple `/health/` endpoint that:
- Returns 200 always (for k8s/docker readiness probes)
- Includes the authenticated user identity (proves the middleware is in the path)
- Includes a database round-trip (proves the DB is reachable)

**Files:**
- Create: `apps/core/tests/test_views.py`
- Modify: `apps/core/views.py`
- Modify: `apps/core/urls.py`

- [ ] **Step 1: Write the failing test in `apps/core/tests/test_views.py`**

```python
"""Tests for core.views."""
from __future__ import annotations

import pytest
from django.test import Client


@pytest.fixture
def client_with_remote_user() -> Client:
    return Client(HTTP_REMOTE_USER="fchemorion")


def test_health_endpoint_returns_200(db, client_with_remote_user):
    response = client_with_remote_user.get("/health/")
    assert response.status_code == 200


def test_health_endpoint_includes_user(db, client_with_remote_user):
    response = client_with_remote_user.get("/health/")
    payload = response.json()
    assert payload["user"] == "fchemorion"


def test_health_endpoint_reports_db_ok(db, client_with_remote_user):
    response = client_with_remote_user.get("/health/")
    payload = response.json()
    assert payload["database"] == "ok"


def test_health_endpoint_returns_json(db, client_with_remote_user):
    response = client_with_remote_user.get("/health/")
    assert response["Content-Type"].startswith("application/json")


def test_health_endpoint_works_without_remote_user_in_dev(db):
    # In dev, AUTHELIA_DEV_FAKE_USER kicks in
    client = Client()
    response = client.get("/health/")
    assert response.status_code == 200
    assert response.json()["user"] == "fchemorion"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
poetry run pytest apps/core/tests/test_views.py -v
```

Expected:
```
... 404 Not Found at /health/
```

- [ ] **Step 3: Implement the view in `apps/core/views.py`**

```python
"""Core views."""
from __future__ import annotations

from django.db import connection
from django.http import HttpRequest, JsonResponse


def health(request: HttpRequest) -> JsonResponse:
    """Liveness + identity + DB reachability check.

    Always returns 200. ``database`` will be ``"error"`` if the DB
    cursor open fails, but the response still returns 200 so external
    probes don't restart the container — the failure is in the body
    for the operator to read.
    """
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        db_status = "ok"
    except Exception as exc:
        db_status = f"error: {exc}"

    return JsonResponse(
        {
            "user": getattr(request.user, "username", None)
            if request.user.is_authenticated
            else None,
            "database": db_status,
        }
    )
```

- [ ] **Step 4: Wire the URL in `apps/core/urls.py`**

```python
"""Core URL routes."""
from __future__ import annotations

from django.urls import path

from core import views

app_name = "core"
urlpatterns = [
    path("health/", views.health, name="health"),
]
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
poetry run pytest apps/core/tests/test_views.py -v
```

Expected:
```
5 passed
```

- [ ] **Step 6: Manually verify via the dev server**

```bash
poetry run python manage.py migrate
poetry run python manage.py runserver
```

In another terminal:
```bash
curl -s http://localhost:8000/health/ | python -m json.tool
```

Expected:
```json
{
    "user": "fchemorion",
    "database": "ok"
}
```

Stop the dev server (`Ctrl-C`).

- [ ] **Step 7: Commit**

```bash
git add apps/core/views.py apps/core/urls.py apps/core/tests/test_views.py
git commit -m "feat(core): add /health/ endpoint with user + DB status"
```

---

## Task 7: Celery smoke task (TDD)

Prove that Celery is wired correctly: the Django app can enqueue a task,
a worker can pick it up via Redis, and the result is stored.

**Files:**
- Create: `apps/core/tests/test_tasks.py`
- Modify: `apps/core/tasks.py`

- [ ] **Step 1: Write the failing test in `apps/core/tests/test_tasks.py`**

```python
"""Tests for core.tasks."""
from __future__ import annotations

import pytest

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
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
poetry run pytest apps/core/tests/test_tasks.py -v
```

Expected:
```
ImportError: cannot import name 'smoke_ping' from 'core.tasks'
```

- [ ] **Step 3: Implement the task in `apps/core/tasks.py`**

```python
"""Core Celery tasks — shared utility tasks like janitor sweeps."""
from __future__ import annotations

from celery import shared_task


@shared_task
def smoke_ping(message: str) -> str:
    """Sanity-check task: prove Celery routing works end-to-end."""
    return f"pong: {message}"
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
poetry run pytest apps/core/tests/test_tasks.py -v
```

Expected:
```
2 passed
```

- [ ] **Step 5: Commit**

```bash
git add apps/core/tasks.py apps/core/tests/test_tasks.py
git commit -m "feat(core): add smoke_ping Celery task"
```

---

## Task 8: ruff + mypy configuration

**Files:**
- Create: `.ruff.toml`
- Create: `mypy.ini`

- [ ] **Step 1: Create `.ruff.toml`**

```toml
target-version = "py312"
line-length = 100
src = ["apps", "interactome"]

[lint]
select = [
  "E",   # pycodestyle errors
  "F",   # pyflakes
  "W",   # pycodestyle warnings
  "I",   # isort
  "B",   # flake8-bugbear
  "UP",  # pyupgrade
  "DJ",  # flake8-django
  "S",   # flake8-bandit (security)
  "C4",  # flake8-comprehensions
  "SIM", # flake8-simplify
  "RET", # flake8-return
]
ignore = [
  "E501",  # line-too-long — formatter handles this
  "S101",  # assert used (we use it in tests freely)
]

[lint.per-file-ignores]
"**/tests/*" = ["S101", "S106"]  # tests use literal passwords, asserts
"**/migrations/*" = ["E501", "RET504"]
"interactome/settings/*" = ["F401", "F403"]  # star imports are deliberate

[format]
quote-style = "double"
indent-style = "space"
```

- [ ] **Step 2: Create `mypy.ini`**

```ini
[mypy]
python_version = 3.12
plugins = mypy_django_plugin.main
strict_optional = True
warn_unused_ignores = True
warn_redundant_casts = True
warn_unreachable = True
disallow_untyped_defs = True
disallow_incomplete_defs = True
check_untyped_defs = True
disallow_untyped_decorators = False
no_implicit_optional = True
ignore_missing_imports = False

[mypy.plugins.django-stubs]
django_settings_module = "interactome.settings.dev"

[mypy-celery.*]
ignore_missing_imports = True

[mypy-django_celery_beat.*]
ignore_missing_imports = True

[mypy-django_celery_results.*]
ignore_missing_imports = True

[mypy-structlog.*]
ignore_missing_imports = True

[mypy-*.tests.*]
disallow_untyped_defs = False
```

- [ ] **Step 3: Run ruff to verify the codebase is clean**

```bash
poetry run ruff check .
```

Expected: `All checks passed!` (or a small number of issues that should be fixed inline before continuing).

If issues found, fix them:
```bash
poetry run ruff check . --fix
poetry run ruff format .
```

- [ ] **Step 4: Run mypy to verify the codebase type-checks**

```bash
poetry run mypy apps interactome
```

Expected: `Success: no issues found in N source files.`

If mypy complains about missing type hints in code we wrote, add them. Don't disable strict mode.

- [ ] **Step 5: Commit**

```bash
git add .ruff.toml mypy.ini
git commit -m "build: configure ruff and mypy"
```

---

## Task 9: Dockerfile (shared image for web + workers)

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`

- [ ] **Step 1: Create `.dockerignore`**

```
.git
.github
.venv
__pycache__
*.pyc
.pytest_cache
.mypy_cache
.ruff_cache
.coverage
htmlcov
docs
pgdata
redisdata
miniodata
backupdata
.env
.env.*
README.md
```

- [ ] **Step 2: Create `Dockerfile`**

```dockerfile
# Multi-stage build:
#   1. ``builder`` installs Poetry-managed deps into a virtualenv
#   2. ``runtime`` copies the virtualenv + source into a slim image
# Web, beat, and worker_* containers all use the same image — they differ
# only in their startup command (see docker-compose.yml).

FROM python:3.12-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VERSION=1.8.3 \
    POETRY_HOME=/opt/poetry \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=true

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
      curl \
      libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN curl -sSL https://install.python-poetry.org | python3 -
ENV PATH="${POETRY_HOME}/bin:${PATH}"

WORKDIR /app
COPY pyproject.toml poetry.lock ./
RUN poetry install --no-root --without dev

FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}" \
    DJANGO_SETTINGS_MODULE=interactome.settings.production

RUN apt-get update && apt-get install -y --no-install-recommends \
      libpq5 \
      curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1000 app \
    && useradd --system --uid 1000 --gid app --no-create-home app

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --chown=app:app . .

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -f http://localhost:8000/health/ || exit 1

CMD ["gunicorn", "interactome.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "4", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
```

- [ ] **Step 3: Build the image to verify it works**

```bash
docker build -t interactome:dev .
```

Expected: builds successfully, ends with `naming to docker.io/library/interactome:dev`.

- [ ] **Step 4: Commit**

```bash
git add Dockerfile .dockerignore
git commit -m "build: add multi-stage Dockerfile for web and workers"
```

---

## Task 10: docker-compose.yml (9-service Phase 0 stack)

**Files:**
- Create: `docker-compose.yml`
- Create: `.env.example`

- [ ] **Step 1: Create `.env.example`**

```bash
# === Django ===
DJANGO_SECRET_KEY=change-me-to-a-50-char-random-string
DJANGO_ALLOWED_HOSTS=interactome.simbiosys.sb.upf.edu,localhost
DJANGO_SETTINGS_MODULE=interactome.settings.production

# === Postgres ===
POSTGRES_DB=interactome
POSTGRES_USER=interactome
POSTGRES_PASSWORD=change-me-to-a-strong-password
POSTGRES_HOST=postgres
POSTGRES_PORT=5432

# === Redis ===
REDIS_URL=redis://redis:6379/0

# === MinIO ===
MINIO_ROOT_USER=interactome
MINIO_ROOT_PASSWORD=change-me-to-a-strong-password
MINIO_BUCKET_PAPERS=papers
MINIO_BUCKET_SBML=sbml-artifacts

# === External services ===
OLLAMA_BASE=https://ollama.simbiosys.sb.upf.edu
AUTHELIA_VERIFY=https://authelia.simbiosys.sb.upf.edu/api/verify
NCBI_API_KEY=your-ncbi-api-key-here

# === Observability ===
SENTRY_DSN=
```

- [ ] **Step 2: Create `docker-compose.yml`**

```yaml
# Phase 0 stack: brings the foundation online.
#
# Services:
#   caddy        — TLS + reverse proxy + Authelia forward_auth
#   web          — Django + gunicorn (production settings)
#   beat         — Celery Beat scheduler
#   worker_io    — Celery worker for the io queue
#   postgres     — application database
#   redis        — Celery broker + cache
#   minio        — S3-compatible blob store
#   grobid       — PDF → TEI XML sidecar (used by later phases)
#
# Later phases will add 7 more `worker_extract_<model>` services.

services:
  caddy:
    image: caddy:2.8-alpine
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
      - caddy_config:/config
    depends_on:
      - web

  web:
    build:
      context: .
      dockerfile: Dockerfile
    image: interactome:dev
    restart: unless-stopped
    env_file: .env
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    command: >
      sh -c "python manage.py migrate --noinput &&
             gunicorn interactome.wsgi:application
                      --bind 0.0.0.0:8000
                      --workers 4
                      --access-logfile - --error-logfile -"
    expose:
      - "8000"

  beat:
    image: interactome:dev
    restart: unless-stopped
    env_file: .env
    depends_on:
      web:
        condition: service_healthy
    command: celery -A interactome beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler

  worker_io:
    image: interactome:dev
    restart: unless-stopped
    env_file: .env
    depends_on:
      web:
        condition: service_healthy
    command: celery -A interactome worker -Q q.io -c 8 -n io@%h -l info

  postgres:
    image: postgres:16-alpine
    restart: unless-stopped
    env_file: .env
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    restart: unless-stopped
    command: redis-server --appendonly yes --save 60 1000
    volumes:
      - redisdata:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

  minio:
    image: minio/minio:RELEASE.2024-10-13T13-34-11Z
    restart: unless-stopped
    env_file: .env
    environment:
      MINIO_ROOT_USER: ${MINIO_ROOT_USER}
      MINIO_ROOT_PASSWORD: ${MINIO_ROOT_PASSWORD}
    command: server /data --console-address ':9001'
    volumes:
      - miniodata:/data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 10s
      timeout: 5s
      retries: 5

  grobid:
    image: lfoppiano/grobid:0.8.0
    restart: unless-stopped
    deploy:
      resources:
        limits:
          memory: 6G
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8070/api/isalive"]
      interval: 30s
      timeout: 10s
      retries: 5

volumes:
  pgdata:
  redisdata:
  miniodata:
  caddy_data:
  caddy_config:
```

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml .env.example
git commit -m "build: add docker-compose stack for Phase 0"
```

---

## Task 11: Caddyfile with Authelia forward_auth

**Files:**
- Create: `Caddyfile`

- [ ] **Step 1: Create `Caddyfile`**

```caddy
# Caddy v2 reverse proxy.
#
# In production behind the cluster DNS, Caddy terminates TLS using ACME
# (Let's Encrypt) and forwards traffic to the ``web`` container after
# verifying the request with Authelia.
#
# In local dev, you can substitute the production hostname with
# ``localhost:8000`` and skip the forward_auth block — see README.

{
    # Email used by Caddy for Let's Encrypt registration.
    email francis.chemorion@upf.edu
}

interactome.simbiosys.sb.upf.edu {
    encode zstd gzip

    # Forward every request to Authelia first. If Authelia returns 200,
    # the original request continues; if 401, Authelia handles the
    # redirect to its login page.
    forward_auth https://authelia.simbiosys.sb.upf.edu {
        uri /api/verify?rd=https://authelia.simbiosys.sb.upf.edu/
        copy_headers Remote-User Remote-Groups Remote-Name Remote-Email
    }

    reverse_proxy web:8000 {
        header_up X-Forwarded-Proto https
        header_up X-Forwarded-Host {host}
        header_up X-Real-IP {remote_host}
    }

    log {
        output stdout
        format json
    }
}
```

- [ ] **Step 2: Validate Caddyfile syntax**

```bash
docker run --rm -v "$(pwd)/Caddyfile:/etc/caddy/Caddyfile:ro" caddy:2.8-alpine \
  caddy validate --config /etc/caddy/Caddyfile
```

Expected: `Valid configuration`.

- [ ] **Step 3: Commit**

```bash
git add Caddyfile
git commit -m "build: add Caddyfile with Authelia forward_auth"
```

---

## Task 12: GitHub Actions CI

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Create `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  lint-and-test:
    runs-on: ubuntu-latest

    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_DB: interactome_test
          POSTGRES_USER: interactome
          POSTGRES_PASSWORD: interactome
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U interactome"
          --health-interval 5s
          --health-timeout 5s
          --health-retries 5

      redis:
        image: redis:7-alpine
        ports: ["6379:6379"]
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 5s
          --health-timeout 3s
          --health-retries 5

    env:
      POSTGRES_DB: interactome_test
      POSTGRES_USER: interactome
      POSTGRES_PASSWORD: interactome
      POSTGRES_HOST: localhost
      POSTGRES_PORT: 5432
      REDIS_URL: redis://localhost:6379/0
      DJANGO_SETTINGS_MODULE: interactome.settings.dev

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python 3.12
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install Poetry
        run: |
          curl -sSL https://install.python-poetry.org | python3 -
          echo "$HOME/.local/bin" >> $GITHUB_PATH

      - name: Cache Poetry virtualenv
        uses: actions/cache@v4
        with:
          path: .venv
          key: poetry-${{ runner.os }}-${{ hashFiles('poetry.lock') }}

      - name: Install dependencies
        run: poetry install --with dev

      - name: Lint with ruff
        run: poetry run ruff check .

      - name: Format check with ruff
        run: poetry run ruff format --check .

      - name: Type check with mypy
        run: poetry run mypy apps interactome

      - name: Run tests
        run: poetry run pytest -v --tb=short
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add GitHub Actions workflow for lint, types, tests"
```

- [ ] **Step 3: Push and verify CI is green on GitHub**

```bash
git push origin main
```

Open `https://github.com/SpineView1/IVD-Regulatory-Network-Atlas/actions` in a
browser. The most recent run should complete with green checks within ~3
minutes. If anything fails, fix the failure inline (do NOT skip / disable
checks) and push again.

---

## Task 13: README.md

**Files:**
- Create: `README.md`

- [ ] **Step 1: Create `README.md`**

````markdown
# IVD Regulatory Network Atlas

Autonomous PubMed → SBML-qual pipeline for intervertebral disc regulatory
networks. Built as a Django application hosted alongside the SIMBIOsys
Ollama gateway.

## Documentation

- [Full design specification](docs/superpowers/specs/2026-05-19-disc-interactome-app-design.md)
- [Phase 0 implementation plan (this is what's been built)](docs/superpowers/plans/2026-05-19-phase-0-foundation.md)

## Prerequisites

- Python 3.12
- Poetry 1.8+
- Docker Engine 24+ and Docker Compose v2
- 32 GB RAM, 200 GB disk available
- Access to the SIMBIOsys cluster Ollama gateway and Authelia SSO

## Local development

```bash
git clone git@github.com:SpineView1/IVD-Regulatory-Network-Atlas.git
cd IVD-Regulatory-Network-Atlas
cp .env.example .env
# Edit .env and fill in real values for DJANGO_SECRET_KEY, POSTGRES_PASSWORD, etc.
poetry install
poetry run python manage.py migrate
poetry run python manage.py runserver
```

Open `http://localhost:8000/health/`. You should see:

```json
{ "user": "fchemorion", "database": "ok" }
```

(`user` is `fchemorion` because the dev settings set
`AUTHELIA_DEV_FAKE_USER`. In production this is `None` and the
middleware reads the `Remote-User` header from Authelia.)

## Running the full stack locally (docker-compose)

```bash
docker-compose up -d
docker-compose ps         # check all 8 services are healthy
docker-compose logs -f web
```

Then `curl https://localhost/health/` (you'll need a TLS cert override for
the self-signed dev cert, or hit `http://localhost:8000/health/`
directly bypassing Caddy).

## Running tests

```bash
poetry run pytest
```

Lint and type checks:

```bash
poetry run ruff check .
poetry run ruff format --check .
poetry run mypy apps interactome
```

## Project layout

See [the design spec](docs/superpowers/specs/2026-05-19-disc-interactome-app-design.md#2-django-apps-and-module-boundaries)
for the full architecture. Phase 0 contains only the `core` app; subsequent
phases add `networks`, `corpus`, `papers`, `extract`, `graph`, `sbml`,
`verify`, `schedule`, and `dashboard`.

## Deployment

The cluster host runs the same `docker-compose.yml`. See
[Section 9 of the spec](docs/superpowers/specs/2026-05-19-disc-interactome-app-design.md#9-deployment-and-operations)
for IT prerequisites (DNS, Authelia AD group) and the deploy procedure.

## License

UPF / SIMBIOsys research code. Contact Francis Chemorion before
redistributing.
````

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add README with quickstart and project layout"
```

---

## Task 14: End-to-end stack verification

This task isn't TDD-shaped — it's the final integration check that all
the pieces from tasks 1–13 actually work together.

- [ ] **Step 1: Create a real `.env`**

```bash
cp .env.example .env
# Edit .env. Generate a real DJANGO_SECRET_KEY:
python -c "import secrets; print(secrets.token_urlsafe(50))"
# Paste the output as the DJANGO_SECRET_KEY value.
# Set POSTGRES_PASSWORD and MINIO_ROOT_PASSWORD to non-default values too.
```

- [ ] **Step 2: Bring up the stack**

```bash
docker-compose up -d
```

Wait ~30 seconds for all services to be ready.

- [ ] **Step 3: Verify every container is up and healthy**

```bash
docker-compose ps
```

Expected output:
```
NAME                         STATUS              PORTS
interactome-beat-1           Up                  -
interactome-caddy-1          Up                  0.0.0.0:80->80/tcp, 0.0.0.0:443->443/tcp
interactome-grobid-1         Up (healthy)        8070/tcp, 8071/tcp
interactome-minio-1          Up (healthy)        9000-9001/tcp
interactome-postgres-1       Up (healthy)        5432/tcp
interactome-redis-1          Up (healthy)        6379/tcp
interactome-web-1            Up (healthy)        8000/tcp
interactome-worker_io-1      Up                  -
```

If any service is `Restarting` or `Exited`, inspect its logs:
```bash
docker-compose logs <service-name>
```

Fix issues and re-run `docker-compose up -d` until all services are
`Up`/`Up (healthy)`.

- [ ] **Step 4: Verify the health endpoint works via Caddy (skip TLS check)**

```bash
curl -sk -H 'Remote-User: fchemorion' \
        -H 'Remote-Email: francis.chemorion@upf.edu' \
        -H 'Remote-Name: Francis Chemorion' \
        -H 'Remote-Groups: simbiosys-lab' \
        https://localhost/health/ | python -m json.tool
```

Expected:
```json
{
    "user": "fchemorion",
    "database": "ok"
}
```

(Caddy in local dev hasn't gotten a Let's Encrypt cert; `-k` skips
self-signed-cert validation. The `Remote-User` header simulates what
Authelia would normally inject in production.)

- [ ] **Step 5: Enqueue a smoke task via the worker**

```bash
docker-compose exec web python manage.py shell -c \
  "from core.tasks import smoke_ping; r = smoke_ping.delay('ci'); print(r.get(timeout=10))"
```

Expected output:
```
pong: ci
```

This proves: Django can enqueue → Redis routes → `worker_io` picks up →
task runs → result returns.

- [ ] **Step 6: Verify Beat is scheduling tasks**

```bash
docker-compose logs --tail 20 beat
```

Expected: log lines mentioning `Scheduler: Sending due task` or
`Scheduler: registered`. There are no domain tasks scheduled yet, so
the scheduler will be quiet but should NOT be erroring.

- [ ] **Step 7: Bring the stack down**

```bash
docker-compose down
```

(Volumes are preserved — DB data, Redis queues, MinIO blobs survive a
`down`. To wipe state, add `--volumes`.)

- [ ] **Step 8: Cold-restart verification**

```bash
docker-compose up -d
sleep 30
curl -sk -H 'Remote-User: fchemorion' https://localhost/health/ | python -m json.tool
```

Expected: same response as Step 4, proving state survives restart.

Bring stack down again:
```bash
docker-compose down
```

- [ ] **Step 9: Commit (if any small fixes were needed during verification)**

```bash
git status
# If there are uncommitted changes from this verification step:
git add <files>
git commit -m "fix: address issues found in Phase 0 stack verification"
```

---

## Task 15: Final push and Phase 0 close-out

- [ ] **Step 1: Run the full local CI suite one more time**

```bash
poetry run ruff check .
poetry run ruff format --check .
poetry run mypy apps interactome
poetry run pytest -v
```

All four commands must return exit code 0.

- [ ] **Step 2: Push to origin**

```bash
git push origin main
```

- [ ] **Step 3: Verify GitHub Actions CI is green**

Open the repository's Actions tab in a browser. The latest workflow
run should be green within ~3 minutes.

- [ ] **Step 4: Tag the Phase 0 release**

```bash
git tag -a phase-0-complete -m "Phase 0 (Foundation) complete

Working stack:
- 8 services up via docker-compose
- /health/ endpoint returning user + DB status
- Authelia middleware honouring Remote-* headers
- Celery wired with smoke task verified
- pytest + ruff + mypy all green
- GitHub Actions CI green

Next: Phase 1 (Master IDD corpus) — see
docs/superpowers/plans/ for the next implementation plan
(to be written after Phase 0 is verified working on the cluster)."
git push origin phase-0-complete
```

- [ ] **Step 5: Phase 0 done. Hand off for cluster deployment.**

The Phase 0 deliverable is now ready for Javier (IT) to:

1. Provision a host with Docker, ≥ 32 GB RAM, ≥ 200 GB disk
2. Configure DNS A record for `interactome.simbiosys.sb.upf.edu`
3. Add the Authelia rule + AD group `simbiosys-lab`
4. Clone the repo, configure `.env`, run `docker-compose up -d`
5. Open `https://interactome.simbiosys.sb.upf.edu/health/` from inside
   the VPN. After Authelia SSO, the response should show the logged-in
   user.

Once deployed-and-green on the cluster, the Phase 1 implementation
plan can be written.

---

## Phase 0 Self-Review

**Spec coverage check** (against `docs/superpowers/specs/2026-05-19-disc-interactome-app-design.md`):

- ✅ Section 1 (high-level architecture) — Caddy → Web → Postgres/Redis/MinIO wired, Authelia forward_auth, all services in compose
- ✅ Section 2 (Django apps) — `core` app created with the responsibilities listed (middleware, base models, shared utilities). Other 9 apps deferred to subsequent phases per spec.
- ✅ Section 3 (data model) — `TimestampedModel` abstract base implemented; concrete models deferred to phases that introduce them.
- ⏭️ Section 4 (per-paper pipeline) — deferred to Phase 1 / Phase 2 plans.
- ⏭️ Section 5 (master corpus) — deferred to Phase 1 plan.
- ✅ Section 6 (Celery topology) — Beat + worker_io in compose; per-model extract workers deferred to Phase 2 plan.
- ⏭️ Section 7 (SBML + verify UI) — deferred to Phase 4 / Phase 5 plans.
- ✅ Section 8 (resumability) — `TimestampedModel` provides the audit-timestamp infrastructure all later phases will rely on. No long-running tasks in Phase 0 to require the janitor pattern yet.
- ✅ Section 9 (deployment) — `docker-compose.yml`, `Caddyfile`, `Dockerfile`, `.env.example`, README all present and tested.
- ⏭️ Section 10 (roadmap) — this plan implements Phase 0, the first row of the table.

**Placeholder scan:** No "TBD"/"TODO"/"implement later" strings in any task. Every step contains either complete code, a complete command, or a single concrete file action.

**Type consistency:** `AutheliaRemoteUserMiddleware` is referenced identically in test, implementation, and settings. `TimestampedModel` is the same name everywhere. `smoke_ping` task name consistent across test, implementation, and verification shell command.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-19-phase-0-foundation.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task,
review between tasks, fast iteration. Each task is small enough for one
subagent invocation, and the foundation phase benefits from independent
review of each commit.

**2. Inline Execution** — Execute tasks in this session using
`executing-plans`, batch execution with checkpoints for review.

**Which approach?**
