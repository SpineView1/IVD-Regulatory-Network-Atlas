"""Base Django settings shared across all environments.

Subclasses (``dev.py``, ``production.py``) override the few values
that differ per environment.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import structlog

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
    "networks",
    "corpus",
    "papers",
    "extract",
    "graph",
    "analysis",
    "schedule",
    "dashboard",
    "sbml",
    "verify",
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
                "dashboard.context_processors.unread_notifications_count",
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
CELERY_TASK_DEFAULT_QUEUE = "q.io"
CELERY_TASK_ROUTES = {
    # Route all core tasks (including smoke_ping) to the io worker.
    # Later phases add extract queues for ML-intensive work.
    "core.tasks.*": {"queue": "q.io"},
    "corpus.tasks.refresh_pubmed": {"queue": "q.io"},
    "corpus.tasks.refresh_pubmed_full": {"queue": "q.io"},
    "corpus.tasks.ingest_paper": {"queue": "q.io"},
    "corpus.tasks.triage_relevance_cheap": {"queue": "q.io"},
    "corpus.tasks.triage_relevance_llm": {"queue": "q.fast"},
    "papers.tasks.classify_pending": {"queue": "q.io"},
    "papers.tasks.classify_original": {"queue": "q.fast"},
    "papers.tasks.fetch_fulltext_pending": {"queue": "q.io"},
    "papers.tasks.fetch_fulltext": {"queue": "q.io"},
    "papers.tasks.section_pending": {"queue": "q.io"},
    "papers.tasks.section_and_chunk": {"queue": "q.io"},
    "schedule.tasks.janitor_reset_stale_running": {"queue": "q.io"},
    "schedule.tasks.refill_rate_limit_buckets": {"queue": "q.io"},
    # extract — non-dynamic tasks go to the io worker (spec §6).
    # extract.tasks.run_ppi is routed dynamically by enqueue_pending_chunks
    # via apply_async(queue=queue_for_model(...)); no static route here.
    "extract.tasks.enqueue_pending_chunks": {"queue": "q.io"},
    "extract.tasks.smoke_all_models": {"queue": "q.io"},
    "graph.integrate_pending": {"queue": "q.io"},
    # Phase 5: verify notification + reviewer-reminder tasks (shared q.io worker)
    "verify.notify": {"queue": "q.io"},
    "verify.dispatch_review_assignments": {"queue": "q.io"},
    # Phase 8: Neo4j projection and reconciliation tasks
    "analysis.tasks.project_edges": {"queue": "q.io"},
    "analysis.tasks.reconcile_neo4j": {"queue": "q.io"},
}

# === MinIO / S3-compatible object store ===
MINIO_ENDPOINT_URL = os.environ.get("MINIO_ENDPOINT_URL", "http://minio:9000")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ROOT_USER", "interactome")
MINIO_SECRET_KEY = os.environ.get("MINIO_ROOT_PASSWORD", "interactome")
MINIO_BUCKET_PAPERS = os.environ.get("MINIO_BUCKET_PAPERS", "papers")
MINIO_BUCKET_SBML = os.environ.get("MINIO_BUCKET_SBML", "sbml-artifacts")
MINIO_REGION = "us-east-1"  # placeholder; MinIO ignores it
# Presigned URL TTL (seconds).  900 = 15 min, used by sbml download view.
MINIO_PRESIGN_EXPIRY_SECONDS = int(os.environ.get("MINIO_PRESIGN_EXPIRY_SECONDS", "900"))

# === Ollama gateway (behind Authelia) ===
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE", "https://ollama.simbiosys.sb.upf.edu")
OLLAMA_AUTHELIA_BASE = os.environ.get("AUTHELIA_BASE", "https://authelia.simbiosys.sb.upf.edu")
# OLLAMA_USER / OLLAMA_PASSWORD — the per-model worker credentials used by
# OllamaClient in task workers (run_ppi, smoke_all_models). Workers self-refresh
# on 401 via OllamaClient._login().
OLLAMA_USER = os.environ.get("OLLAMA_USER", "")
OLLAMA_PASSWORD = os.environ.get("OLLAMA_PASSWORD", "")
OLLAMA_DEFAULT_TIMEOUT = float(os.environ.get("OLLAMA_DEFAULT_TIMEOUT", "120"))
OLLAMA_KEEP_ALIVE = os.environ.get("OLLAMA_KEEP_ALIVE", "2h")
# OLLAMA_SESSION_COOKIE — optional pre-seeded Authelia session cookie value.
# When set, OllamaClient can skip the initial /api/firstfactor login on first
# use (useful for operator smoke tests and management commands).
OLLAMA_SESSION_COOKIE = os.environ.get("OLLAMA_SESSION_COOKIE", "")

# === Authelia service-account credentials (for standalone session refresh) ===
# AUTHELIA_SVC_USER / AUTHELIA_SVC_PASSWORD — used exclusively by the standalone
# refresh_authelia_session() helper (management commands, periodic re-auth tasks).
# These are the SAME account as OLLAMA_USER/OLLAMA_PASSWORD in environments
# where one service account is used for all Ollama/Authelia operations. In
# environments with separate accounts, OLLAMA_USER/PASSWORD is the per-worker
# credential and AUTHELIA_SVC_* is the management/refresh credential.
# Populated at deploy time; left blank in dev where Ollama is not reachable.
AUTHELIA_SVC_USER = os.environ.get("AUTHELIA_SVC_USER", "")
AUTHELIA_SVC_PASSWORD = os.environ.get("AUTHELIA_SVC_PASSWORD", "")

# === NCBI E-utilities ===
NCBI_API_KEY = os.environ.get("NCBI_API_KEY", "")
NCBI_TOOL_NAME = "interactome-disc-atlas"
NCBI_CONTACT_EMAIL = os.environ.get("NCBI_CONTACT_EMAIL", "francis.chemorion@upf.edu")

# === Europe PMC ===
EUROPE_PMC_BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest"
EUROPE_PMC_OAI_URL = "https://europepmc.org/oai.cgi"

# === PubTator3 ===
PUBTATOR3_BASE_URL = "https://www.ncbi.nlm.nih.gov/research/pubtator3-api"

# === GROBID ===
GROBID_BASE_URL = os.environ.get("GROBID_BASE_URL", "http://grobid:8070")
GROBID_TIMEOUT = float(os.environ.get("GROBID_TIMEOUT", "300"))

# Logging
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "structlog.stdlib.ProcessorFormatter",
            "processor": structlog.dev.ConsoleRenderer(),
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

# === Celery Beat schedule (merged across phases) ===
from schedule.beat_schedule import BEAT_SCHEDULE  # noqa: E402

CELERY_BEAT_SCHEDULE = BEAT_SCHEDULE
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

# === Neo4j read-model (Phase 8) =============================================
# Postgres is the system of record; Neo4j is derived and rebuildable.
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "")

# Which GraphBackend the analysis app uses. "neo4j" in real deployments;
# tests override to "fake" via the settings fixture.
ANALYSIS_GRAPH_BACKEND = os.environ.get("ANALYSIS_GRAPH_BACKEND", "neo4j")

# === Email (Phase 5 verification notifications) ===
# Default to console backend; dev.py keeps console, production.py uses SMTP.
EMAIL_BACKEND = os.environ.get(
    "DJANGO_EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend",
)
DEFAULT_FROM_EMAIL = os.environ.get(
    "DJANGO_DEFAULT_FROM_EMAIL",
    "no-reply@interactome.simbiosys.sb.upf.edu",
)
