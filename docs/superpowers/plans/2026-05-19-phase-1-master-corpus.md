# Phase 1: Master IDD Corpus — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the master IDD corpus — a queryable Postgres database of ~30,000–40,000 disc-relevant PubMed papers, classified original-vs-review, tagged with per-network relevance, with full-text fetched where available, and exported via `/corpus/export.csv`. End state (week 3): a curator can run `curl https://interactome.simbiosys.sb.upf.edu/corpus/export.csv?network=nfkb_axis -o nfkb.csv` and receive every NF-κB-relevant paper as a CSV row. All discovery, fetching, classification, and triage runs autonomously under Celery Beat. (per spec §5, "first usable artifact (deliverable in week 3) is the master IDD corpus itself")

**Architecture:** Five new Django apps (`networks`, `corpus`, `papers`, `schedule`, `dashboard`) sit between the Phase 0 `core` app and the still-unwritten extraction/graph/SBML apps. The pipeline `corpus.refresh_pubmed → corpus.ingest_paper → papers.classify_original → papers.fetch_fulltext → papers.section_and_chunk → corpus.triage_relevance` runs as Celery tasks coordinated by Beat schedules and watermarks. All external HTTP calls (NCBI, Europe PMC, PubTator3, Ollama, Authelia) pass through a token-bucket rate limiter persisted in `schedule_ratelimitbucket`. The Ollama client authenticates against Authelia (`POST /api/firstfactor` → cookie), used for the cheap LLM passes (`is_original` classifier and per-network relevance triage). MinIO holds JATS XML / GROBID TEI / PDF blobs sharded by PMID prefix. (per spec §1, "All persistent state lives in Postgres" — every task starts by reading rows and ends by committing rows.)

**Tech Stack:** Python 3.12, Django 5.0, Celery 5.3, django-celery-beat 2.6, PostgreSQL 16, Redis 7, MinIO RELEASE.2024-10-13T13-34-11Z, `requests` 2.32, `lxml` 5.3 (JATS/TEI parsing), `nltk` 3.9 (sentence boundary detection), `tiktoken` 0.7 (token counting for chunk sizing), `boto3` 1.35 (MinIO client), `httpx` 0.27 (HTTP/2 + cookie jar for Authelia), `pytest-httpx` 0.30 (HTTP mocking in tests), `factory-boy` 3.3 (model fixtures), `freezegun` 1.5 (frozen time in tests).

**Reference spec:** `docs/superpowers/specs/2026-05-19-disc-interactome-app-design.md` Sections 2 (apps), 3 (data model), 4 (pipeline), 5 (master corpus subsystem — the load-bearing section), 6 (Celery topology and Beat schedule), and Appendix A (network taxonomy).

---

## File Structure After Phase 1

```
/                                       (git repo root — Phase 0 already in place)
├── pyproject.toml                      add new deps (lxml, nltk, tiktoken, boto3, httpx, ...)
├── poetry.lock                         re-locked
├── .env.example                        add NCBI_API_KEY, OLLAMA_USER, OLLAMA_PASSWORD, MINIO_*
├── docker-compose.yml                  add worker_fast service
├── apps/
│   ├── core/                           (Phase 0; extended with OllamaClient + ontology stubs)
│   │   ├── ollama.py                   Authelia-aware Ollama HTTP client
│   │   ├── minio_client.py             boto3 wrapper, bucket helpers
│   │   └── tests/test_ollama.py
│   │   └── tests/test_minio_client.py
│   ├── networks/
│   │   ├── __init__.py
│   │   ├── apps.py
│   │   ├── models.py                   Network, NetworkQuery, FamilyFilter
│   │   ├── admin.py
│   │   ├── services.py                 public API: get_network, list_active, etc.
│   │   ├── fixtures/
│   │   │   └── 0001_taxonomy.yaml      seed data for the 200+ networks
│   │   ├── management/commands/
│   │   │   └── load_network_taxonomy.py   loads the YAML fixture
│   │   ├── migrations/
│   │   └── tests/
│   │       ├── conftest.py             NetworkFactory
│   │       ├── test_models.py
│   │       ├── test_services.py
│   │       └── test_load_taxonomy.py
│   ├── corpus/
│   │   ├── __init__.py
│   │   ├── apps.py
│   │   ├── models.py                   Paper, PaperRelevance, IngestRun
│   │   ├── admin.py
│   │   ├── services.py                 enqueue helpers; public API
│   │   ├── clients/
│   │   │   ├── __init__.py
│   │   │   ├── ncbi.py                 ESearch, EFetch, ELink
│   │   │   ├── europepmc.py            OAI-PMH JATS XML fetcher
│   │   │   └── pubtator.py             PubTator3 REST client
│   │   ├── tasks.py                    refresh_pubmed, ingest_paper, triage_relevance
│   │   ├── views.py                    export.csv, stats, paper detail
│   │   ├── urls.py
│   │   ├── pubmed_query.py             builds the canonical IDD MeSH+TIAB query
│   │   ├── migrations/
│   │   └── tests/
│   │       ├── conftest.py             PaperFactory, recorded HTTP fixtures
│   │       ├── fixtures/
│   │       │   ├── esearch_response.xml
│   │       │   ├── efetch_response.xml
│   │       │   ├── elink_response.xml
│   │       │   └── pubtator_response.json
│   │       ├── test_models.py
│   │       ├── test_pubmed_query.py
│   │       ├── test_ncbi_client.py
│   │       ├── test_europepmc_client.py
│   │       ├── test_pubtator_client.py
│   │       ├── test_refresh_pubmed.py
│   │       ├── test_ingest_paper.py
│   │       ├── test_triage_relevance.py
│   │       └── test_views.py
│   ├── papers/
│   │   ├── __init__.py
│   │   ├── apps.py
│   │   ├── models.py                   Section, Chunk, PaperClassification
│   │   ├── doco.py                     section-type → DoCO IRI mapping
│   │   ├── chunking.py                 sentence-aware chunker
│   │   ├── jats.py                     JATS XML → section list
│   │   ├── grobid.py                   GROBID PDF → TEI XML client
│   │   ├── services.py
│   │   ├── tasks.py                    classify_original, fetch_fulltext, section_and_chunk
│   │   ├── migrations/
│   │   └── tests/
│   │       ├── conftest.py             SectionFactory, ChunkFactory
│   │       ├── fixtures/
│   │       │   ├── sample_jats.xml
│   │       │   └── sample_grobid_tei.xml
│   │       ├── test_models.py
│   │       ├── test_doco.py
│   │       ├── test_chunking.py
│   │       ├── test_jats.py
│   │       ├── test_grobid.py
│   │       ├── test_classify_original.py
│   │       ├── test_fetch_fulltext.py
│   │       └── test_section_and_chunk.py
│   ├── schedule/
│   │   ├── __init__.py
│   │   ├── apps.py
│   │   ├── models.py                   Watermark, RateLimitBucket, ScheduledJob
│   │   ├── ratelimit.py                @require_token decorator + bucket math
│   │   ├── watermarks.py               read/advance helpers
│   │   ├── tasks.py                    janitor_reset_stale_running, refill_rate_limit_buckets
│   │   ├── beat_schedule.py            CELERY_BEAT_SCHEDULE dict
│   │   ├── fixtures/
│   │   │   └── 0001_buckets.yaml       initial token-bucket allocations
│   │   ├── migrations/
│   │   └── tests/
│   │       ├── conftest.py
│   │       ├── test_models.py
│   │       ├── test_ratelimit.py
│   │       ├── test_watermarks.py
│   │       ├── test_janitor.py
│   │       └── test_beat_schedule.py
│   └── dashboard/
│       ├── __init__.py
│       ├── apps.py
│       ├── views.py                    stats, paper detail
│       ├── urls.py
│       ├── templates/
│       │   └── dashboard/
│       │       ├── base.html
│       │       ├── stats.html
│       │       └── paper_detail.html
│       └── tests/
│           ├── conftest.py
│           ├── test_stats_view.py
│           └── test_paper_detail_view.py
└── interactome/
    ├── settings/
    │   └── base.py                     extend INSTALLED_APPS, CELERY_TASK_ROUTES, MINIO_*, OLLAMA_*
    └── urls.py                         include corpus.urls, dashboard.urls
```

**Why this layout:**
- Each new app owns one concern from spec §2; `services.py` is the public boundary (other apps and views call `services.py` functions, not models or tasks directly).
- HTTP client classes live in `corpus/clients/` (one file per external provider) so they can be mocked uniformly in tests.
- `papers/jats.py`, `papers/chunking.py`, `papers/doco.py` are pure functions — no Django imports — so the unit tests don't need the database.
- Fixtures are committed XML/JSON files captured from real responses (sanitized) so tests don't hit the network.
- `schedule/beat_schedule.py` is a Python module (not the DB scheduler) so the Beat schedule is reviewable in git; `django_celery_beat` still runs it via `DatabaseScheduler` for hot reload, but the canonical source is the python dict.

---

## Task 1: Add Phase 1 Python dependencies

**Files:**
- Modify: `pyproject.toml`
- Regenerate: `poetry.lock`

- [ ] **Step 1: Add the new runtime dependencies to `pyproject.toml`**

Under `[tool.poetry.dependencies]`, add (alphabetised among existing entries):

```toml
boto3 = "^1.35"
httpx = {extras = ["http2"], version = "^0.27"}
lxml = "^5.3"
nltk = "^3.9"
pyyaml = "^6.0"
tiktoken = "^0.7"
```

- [ ] **Step 2: Add the new dev dependencies to `pyproject.toml`**

Under `[tool.poetry.group.dev.dependencies]`, add:

```toml
factory-boy = "^3.3"
freezegun = "^1.5"
pytest-httpx = "^0.30"
responses = "^0.25"
```

- [ ] **Step 3: Re-lock and install**

```bash
poetry lock --no-update
poetry install
```

Expected output (last line):
```
Installing the current project: interactome (0.1.0)
```

- [ ] **Step 4: Verify Django still boots**

```bash
poetry run python manage.py check
```

Expected:
```
System check identified no issues (0 silenced).
```

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml poetry.lock
git commit -m "build: add Phase 1 dependencies (lxml, httpx, boto3, nltk, tiktoken, ...)"
```

---

## Task 2: Extend settings with MinIO and Ollama configuration

**Files:**
- Modify: `interactome/settings/base.py`
- Modify: `.env.example`

- [ ] **Step 1: Add settings to `interactome/settings/base.py`** (append at the end of the file)

```python
# === MinIO / S3-compatible object store ===
MINIO_ENDPOINT_URL = os.environ.get("MINIO_ENDPOINT_URL", "http://minio:9000")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ROOT_USER", "interactome")
MINIO_SECRET_KEY = os.environ.get("MINIO_ROOT_PASSWORD", "interactome")
MINIO_BUCKET_PAPERS = os.environ.get("MINIO_BUCKET_PAPERS", "papers")
MINIO_BUCKET_SBML = os.environ.get("MINIO_BUCKET_SBML", "sbml-artifacts")
MINIO_REGION = "us-east-1"  # placeholder; MinIO ignores it

# === Ollama gateway (behind Authelia) ===
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE", "https://ollama.simbiosys.sb.upf.edu")
OLLAMA_AUTHELIA_BASE = os.environ.get(
    "AUTHELIA_BASE", "https://authelia.simbiosys.sb.upf.edu"
)
OLLAMA_USER = os.environ.get("OLLAMA_USER", "")
OLLAMA_PASSWORD = os.environ.get("OLLAMA_PASSWORD", "")
OLLAMA_DEFAULT_TIMEOUT = float(os.environ.get("OLLAMA_DEFAULT_TIMEOUT", "120"))
OLLAMA_KEEP_ALIVE = os.environ.get("OLLAMA_KEEP_ALIVE", "2h")

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

# === Celery routing (Phase 1) ===
CELERY_TASK_DEFAULT_QUEUE = "q.io"
CELERY_TASK_ROUTES = {
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
}
```

- [ ] **Step 2: Add `INSTALLED_APPS` entries** — extend the `INSTALLED_APPS` list in `interactome/settings/base.py` so it reads:

```python
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
    "schedule",
    "dashboard",
]
```

- [ ] **Step 3: Extend `.env.example`**

Append:

```bash
# === Ollama / Authelia credentials ===
OLLAMA_BASE=https://ollama.simbiosys.sb.upf.edu
AUTHELIA_BASE=https://authelia.simbiosys.sb.upf.edu
OLLAMA_USER=set-at-deploy-time
OLLAMA_PASSWORD=set-at-deploy-time
OLLAMA_DEFAULT_TIMEOUT=120
OLLAMA_KEEP_ALIVE=2h

# === NCBI E-utilities ===
NCBI_API_KEY=your-ncbi-api-key
NCBI_CONTACT_EMAIL=francis.chemorion@upf.edu

# === MinIO endpoints ===
MINIO_ENDPOINT_URL=http://minio:9000

# === GROBID ===
GROBID_BASE_URL=http://grobid:8070
GROBID_TIMEOUT=300
```

- [ ] **Step 4: Verify Django check passes**

```bash
poetry run python manage.py check
```

Expected:
```
System check identified no issues (0 silenced).
```

- [ ] **Step 5: Commit**

```bash
git add interactome/settings/base.py .env.example
git commit -m "feat(settings): add MinIO, Ollama, NCBI, Europe PMC, PubTator, GROBID settings"
```

---

## Task 3: Scaffold the five new Django apps

**Files:**
- Create: `apps/networks/{__init__.py,apps.py,models.py,admin.py,services.py,migrations/__init__.py,tests/__init__.py}`
- Create: `apps/corpus/{__init__.py,apps.py,models.py,admin.py,services.py,clients/__init__.py,migrations/__init__.py,tests/__init__.py}`
- Create: `apps/papers/{__init__.py,apps.py,models.py,admin.py,services.py,migrations/__init__.py,tests/__init__.py}`
- Create: `apps/schedule/{__init__.py,apps.py,models.py,services.py,migrations/__init__.py,tests/__init__.py}`
- Create: `apps/dashboard/{__init__.py,apps.py,migrations/__init__.py,tests/__init__.py}`

- [ ] **Step 1: Create `apps/networks/__init__.py`**

```python
"""networks — registry of the 200+ regulatory networks the system targets.

Owns the per-network search queries and family filters. Read-mostly; write
path is the YAML-backed fixture loader.
"""
```

- [ ] **Step 2: Create `apps/networks/apps.py`**

```python
"""Django AppConfig for the networks app."""
from __future__ import annotations

from django.apps import AppConfig


class NetworksConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "networks"
    verbose_name = "Networks (regulatory network registry)"
```

- [ ] **Step 3: Create placeholder `apps/networks/models.py`**

```python
"""networks models — Network, NetworkQuery, FamilyFilter."""
```

- [ ] **Step 4: Create `apps/networks/admin.py`**

```python
"""Django admin registrations for networks."""
```

- [ ] **Step 5: Create `apps/networks/services.py`**

```python
"""Public API for the networks app.

Other apps must import from here, not from `models` directly, per the
boundary discipline in spec §2.
"""
```

- [ ] **Step 6: Create empty files**

- `apps/networks/migrations/__init__.py` — empty
- `apps/networks/tests/__init__.py` — empty

- [ ] **Step 7: Repeat steps 1–6 for `corpus`**

`apps/corpus/__init__.py`:
```python
"""corpus — master IDD corpus: ingest, dedupe, per-network relevance triage.

Owns the Paper, PaperRelevance, IngestRun models and HTTP clients for
NCBI E-utilities, Europe PMC, and PubTator3.
"""
```

`apps/corpus/apps.py`:
```python
"""Django AppConfig for the corpus app."""
from __future__ import annotations

from django.apps import AppConfig


class CorpusConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "corpus"
    verbose_name = "Corpus (master IDD paper database)"
```

`apps/corpus/models.py`:
```python
"""corpus models — Paper, PaperRelevance, IngestRun."""
```

`apps/corpus/admin.py`:
```python
"""Django admin registrations for corpus."""
```

`apps/corpus/services.py`:
```python
"""Public API for the corpus app."""
```

`apps/corpus/clients/__init__.py`:
```python
"""HTTP clients for external data sources (NCBI, Europe PMC, PubTator3)."""
```

`apps/corpus/migrations/__init__.py` — empty
`apps/corpus/tests/__init__.py` — empty

- [ ] **Step 8: Repeat for `papers`**

`apps/papers/__init__.py`:
```python
"""papers — document sectioning: JATS, GROBID, DoCO mapping, chunking.

Owns the Section, Chunk, PaperClassification models.
"""
```

`apps/papers/apps.py`:
```python
"""Django AppConfig for the papers app."""
from __future__ import annotations

from django.apps import AppConfig


class PapersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "papers"
    verbose_name = "Papers (sectioning and chunking)"
```

`apps/papers/models.py`:
```python
"""papers models — Section, Chunk, PaperClassification."""
```

`apps/papers/admin.py`:
```python
"""Django admin registrations for papers."""
```

`apps/papers/services.py`:
```python
"""Public API for the papers app."""
```

`apps/papers/migrations/__init__.py` — empty
`apps/papers/tests/__init__.py` — empty

- [ ] **Step 9: Repeat for `schedule`**

`apps/schedule/__init__.py`:
```python
"""schedule — Celery Beat, rate limiting, janitors, watermarks.

Owns the Watermark, RateLimitBucket, ScheduledJob models.
"""
```

`apps/schedule/apps.py`:
```python
"""Django AppConfig for the schedule app."""
from __future__ import annotations

from django.apps import AppConfig


class ScheduleConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "schedule"
    verbose_name = "Schedule (Beat, rate limits, janitors)"
```

`apps/schedule/models.py`:
```python
"""schedule models — Watermark, RateLimitBucket, ScheduledJob."""
```

`apps/schedule/services.py`:
```python
"""Public API for the schedule app."""
```

`apps/schedule/migrations/__init__.py` — empty
`apps/schedule/tests/__init__.py` — empty

- [ ] **Step 10: Repeat for `dashboard`** (no models)

`apps/dashboard/__init__.py`:
```python
"""dashboard — read-only views over corpus + networks for the operator UI."""
```

`apps/dashboard/apps.py`:
```python
"""Django AppConfig for the dashboard app."""
from __future__ import annotations

from django.apps import AppConfig


class DashboardConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "dashboard"
    verbose_name = "Dashboard (read-only operator views)"
```

`apps/dashboard/migrations/__init__.py` — empty
`apps/dashboard/tests/__init__.py` — empty

- [ ] **Step 11: Verify Django boots with all five apps registered**

```bash
poetry run python manage.py check
```

Expected:
```
System check identified no issues (0 silenced).
```

- [ ] **Step 12: Commit**

```bash
git add apps/networks apps/corpus apps/papers apps/schedule apps/dashboard
git commit -m "feat: scaffold networks, corpus, papers, schedule, dashboard apps"
```

---

## Task 4: `schedule.RateLimitBucket` model (TDD)

This is implemented first because every external HTTP call in subsequent tasks will be wrapped in `@require_token(...)` against a bucket row. (per spec §6, "Every outbound call wrapped in `@require_token`".)

**Files:**
- Create: `apps/schedule/tests/conftest.py`
- Create: `apps/schedule/tests/test_models.py`
- Modify: `apps/schedule/models.py`

- [ ] **Step 1: Create `apps/schedule/tests/conftest.py`**

```python
"""Shared pytest fixtures for the schedule app."""
from __future__ import annotations

import pytest

from schedule.models import RateLimitBucket, Watermark


@pytest.fixture
def ncbi_bucket(db) -> RateLimitBucket:
    return RateLimitBucket.objects.create(
        provider="ncbi_eutils",
        capacity=10,
        refill_per_sec=10.0,
        current_tokens=10.0,
    )


@pytest.fixture
def pubmed_watermark(db) -> Watermark:
    return Watermark.objects.create(
        source="pubmed",
        last_entrez_date=None,
        last_pmid_seen=None,
        resumption_token="",
    )
```

- [ ] **Step 2: Write failing tests in `apps/schedule/tests/test_models.py`**

```python
"""Tests for schedule.models."""
from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from schedule.models import RateLimitBucket, ScheduledJob, Watermark


def test_ratelimit_bucket_round_trip(db):
    bucket = RateLimitBucket.objects.create(
        provider="ncbi_eutils", capacity=10, refill_per_sec=10.0, current_tokens=5.0
    )
    assert bucket.pk is not None
    assert bucket.updated_at is not None


def test_ratelimit_bucket_provider_is_unique(db):
    RateLimitBucket.objects.create(
        provider="ncbi_eutils", capacity=10, refill_per_sec=10.0, current_tokens=10.0
    )
    with pytest.raises(Exception):
        RateLimitBucket.objects.create(
            provider="ncbi_eutils", capacity=20, refill_per_sec=20.0, current_tokens=20.0
        )


def test_ratelimit_bucket_consume_decrements(db, ncbi_bucket):
    assert ncbi_bucket.consume(1) is True
    ncbi_bucket.refresh_from_db()
    assert ncbi_bucket.current_tokens == 9.0


def test_ratelimit_bucket_consume_refuses_when_empty(db):
    bucket = RateLimitBucket.objects.create(
        provider="ncbi_eutils", capacity=10, refill_per_sec=10.0, current_tokens=0.0
    )
    assert bucket.consume(1) is False
    bucket.refresh_from_db()
    assert bucket.current_tokens == 0.0


def test_ratelimit_bucket_refill_caps_at_capacity(db):
    bucket = RateLimitBucket.objects.create(
        provider="ncbi_eutils", capacity=10, refill_per_sec=10.0, current_tokens=5.0
    )
    bucket.updated_at = timezone.now() - timedelta(seconds=60)
    bucket.save(update_fields=["updated_at"])
    bucket.refill()
    bucket.refresh_from_db()
    assert bucket.current_tokens == 10.0


def test_ratelimit_bucket_seconds_until_refill_when_empty(db):
    bucket = RateLimitBucket.objects.create(
        provider="ncbi_eutils", capacity=10, refill_per_sec=10.0, current_tokens=0.0
    )
    # Need 1 token at 10/s = 0.1s
    assert 0.05 < bucket.seconds_until_refill(cost=1) < 0.2


def test_watermark_round_trip(db, pubmed_watermark):
    assert pubmed_watermark.pk is not None
    pubmed_watermark.last_pmid_seen = 39000000
    pubmed_watermark.save()
    pubmed_watermark.refresh_from_db()
    assert pubmed_watermark.last_pmid_seen == 39000000


def test_watermark_source_is_unique(db):
    Watermark.objects.create(source="pubmed")
    with pytest.raises(Exception):
        Watermark.objects.create(source="pubmed")


def test_scheduled_job_round_trip(db):
    job = ScheduledJob.objects.create(
        name="corpus.refresh_pubmed",
        cadence_seconds=3600,
        last_run_at=None,
        last_status="never_run",
    )
    assert job.pk is not None
```

- [ ] **Step 3: Run the failing tests**

```bash
poetry run pytest apps/schedule/tests/test_models.py -v
```

Expected:
```
ImportError: cannot import name 'RateLimitBucket' from 'schedule.models'
```

- [ ] **Step 4: Implement `apps/schedule/models.py`**

```python
"""schedule models — Watermark, RateLimitBucket, ScheduledJob.

These three tables hold all the durable cross-task coordination state:
- Watermark: how far each external-source ingestion has progressed.
- RateLimitBucket: token bucket per provider, persisted so restarts
  don't reset budget. (per spec §5 / §6)
- ScheduledJob: bookkeeping for Beat-driven periodic tasks.
"""
from __future__ import annotations

from datetime import timedelta

from django.db import models, transaction
from django.utils import timezone

from core.models import TimestampedModel


class RateLimitBucket(TimestampedModel):
    """Token-bucket for one outbound provider.

    `consume(cost)` is the public API: returns True if a token was
    deducted (and persists the decrement), False if the bucket is empty.
    Callers re-enqueue with `countdown=seconds_until_refill(cost)` on
    a False return.
    """

    provider = models.CharField(max_length=64, unique=True)
    capacity = models.PositiveIntegerField()
    refill_per_sec = models.FloatField()
    current_tokens = models.FloatField()

    class Meta:
        db_table = "schedule_ratelimitbucket"

    def __str__(self) -> str:
        return f"{self.provider}: {self.current_tokens:.1f}/{self.capacity}"

    def refill(self) -> None:
        """Advance tokens based on wall-clock elapsed since updated_at."""
        with transaction.atomic():
            locked = RateLimitBucket.objects.select_for_update().get(pk=self.pk)
            elapsed = (timezone.now() - locked.updated_at).total_seconds()
            replenished = locked.current_tokens + (elapsed * locked.refill_per_sec)
            locked.current_tokens = min(replenished, float(locked.capacity))
            locked.save(update_fields=["current_tokens", "updated_at"])

    def consume(self, cost: int = 1) -> bool:
        """Atomically deduct `cost` tokens if available."""
        with transaction.atomic():
            locked = RateLimitBucket.objects.select_for_update().get(pk=self.pk)
            elapsed = (timezone.now() - locked.updated_at).total_seconds()
            replenished = min(
                locked.current_tokens + (elapsed * locked.refill_per_sec),
                float(locked.capacity),
            )
            if replenished < cost:
                locked.current_tokens = replenished
                locked.save(update_fields=["current_tokens", "updated_at"])
                return False
            locked.current_tokens = replenished - cost
            locked.save(update_fields=["current_tokens", "updated_at"])
            self.current_tokens = locked.current_tokens
            return True

    def seconds_until_refill(self, cost: int = 1) -> float:
        """How long the caller should wait before retrying."""
        deficit = max(0.0, cost - self.current_tokens)
        if self.refill_per_sec <= 0:
            return float("inf")
        return deficit / self.refill_per_sec


class Watermark(TimestampedModel):
    """One row per external source. Tracks how far ingestion has progressed."""

    source = models.CharField(max_length=64, unique=True)
    last_entrez_date = models.DateField(null=True, blank=True)
    last_pmid_seen = models.BigIntegerField(null=True, blank=True)
    resumption_token = models.TextField(blank=True, default="")
    notes = models.TextField(blank=True, default="")

    class Meta:
        db_table = "schedule_watermark"

    def __str__(self) -> str:
        return f"watermark<{self.source}>"


class ScheduledJob(TimestampedModel):
    """Lightweight log of Beat-driven jobs: when did each task last run?"""

    STATUS_CHOICES = [
        ("never_run", "never_run"),
        ("running", "running"),
        ("done", "done"),
        ("failed", "failed"),
    ]
    name = models.CharField(max_length=128, unique=True)
    cadence_seconds = models.PositiveIntegerField()
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="never_run")
    last_error = models.TextField(blank=True, default="")

    class Meta:
        db_table = "schedule_scheduledjob"

    def mark_running(self) -> None:
        self.last_run_at = timezone.now()
        self.last_status = "running"
        self.save(update_fields=["last_run_at", "last_status", "updated_at"])

    def mark_done(self) -> None:
        self.last_status = "done"
        self.last_error = ""
        self.save(update_fields=["last_status", "last_error", "updated_at"])

    def mark_failed(self, error: str) -> None:
        self.last_status = "failed"
        self.last_error = error[:4000]
        self.save(update_fields=["last_status", "last_error", "updated_at"])
```

- [ ] **Step 5: Generate the migration**

```bash
poetry run python manage.py makemigrations schedule
```

Expected output:
```
Migrations for 'schedule':
  apps/schedule/migrations/0001_initial.py
    + Create model RateLimitBucket
    + Create model ScheduledJob
    + Create model Watermark
```

- [ ] **Step 6: Run the tests**

```bash
poetry run pytest apps/schedule/tests/test_models.py -v
```

Expected:
```
9 passed
```

- [ ] **Step 7: Commit**

```bash
git add apps/schedule/models.py apps/schedule/migrations/ apps/schedule/tests/
git commit -m "feat(schedule): add RateLimitBucket, Watermark, ScheduledJob models"
```

---

## Task 5: `@require_token` rate-limit decorator (TDD)

**Files:**
- Create: `apps/schedule/tests/test_ratelimit.py`
- Create: `apps/schedule/ratelimit.py`

- [ ] **Step 1: Write failing tests in `apps/schedule/tests/test_ratelimit.py`**

```python
"""Tests for the @require_token rate-limit decorator."""
from __future__ import annotations

import pytest

from schedule.models import RateLimitBucket
from schedule.ratelimit import RateLimitExceeded, require_token


def test_require_token_allows_call_when_bucket_has_tokens(db):
    RateLimitBucket.objects.create(
        provider="test_provider", capacity=5, refill_per_sec=1.0, current_tokens=5.0
    )

    @require_token("test_provider", cost=1)
    def call() -> str:
        return "ok"

    assert call() == "ok"
    bucket = RateLimitBucket.objects.get(provider="test_provider")
    assert bucket.current_tokens == pytest.approx(4.0, abs=0.1)


def test_require_token_raises_when_bucket_empty(db):
    RateLimitBucket.objects.create(
        provider="test_provider", capacity=5, refill_per_sec=0.0, current_tokens=0.0
    )

    @require_token("test_provider", cost=1)
    def call() -> str:
        return "ok"

    with pytest.raises(RateLimitExceeded) as exc:
        call()
    assert exc.value.provider == "test_provider"
    assert exc.value.retry_after_seconds == float("inf")


def test_require_token_provider_missing_raises(db):
    @require_token("nonexistent_provider", cost=1)
    def call() -> str:
        return "ok"

    with pytest.raises(RateLimitExceeded):
        call()


def test_require_token_multi_cost_call(db):
    RateLimitBucket.objects.create(
        provider="test_provider", capacity=10, refill_per_sec=0.0, current_tokens=3.0
    )

    @require_token("test_provider", cost=5)
    def expensive_call() -> str:
        return "expensive"

    with pytest.raises(RateLimitExceeded):
        expensive_call()
```

- [ ] **Step 2: Run failing tests**

```bash
poetry run pytest apps/schedule/tests/test_ratelimit.py -v
```

Expected:
```
ImportError: cannot import name 'require_token' from 'schedule.ratelimit'
```

- [ ] **Step 3: Implement `apps/schedule/ratelimit.py`**

```python
"""@require_token decorator — gates every outbound provider call.

Usage:

    @require_token("ncbi_eutils", cost=1)
    def esearch(term: str) -> bytes:
        return httpx.get(...).content

If the bucket has no tokens, raises :class:`RateLimitExceeded` with
``retry_after_seconds`` populated. Celery tasks catch this and re-enqueue
themselves with ``countdown=retry_after_seconds``.
"""
from __future__ import annotations

import functools
from typing import Any, Callable, TypeVar

from schedule.models import RateLimitBucket

F = TypeVar("F", bound=Callable[..., Any])


class RateLimitExceeded(Exception):
    """Raised when a provider's token bucket is empty."""

    def __init__(self, provider: str, retry_after_seconds: float) -> None:
        self.provider = provider
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            f"rate-limited on {provider}; retry in {retry_after_seconds:.2f}s"
        )


def require_token(provider: str, *, cost: int = 1) -> Callable[[F], F]:
    """Decorator factory."""

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                bucket = RateLimitBucket.objects.get(provider=provider)
            except RateLimitBucket.DoesNotExist as exc:
                raise RateLimitExceeded(provider, float("inf")) from exc
            if not bucket.consume(cost):
                raise RateLimitExceeded(
                    provider, bucket.seconds_until_refill(cost)
                )
            return func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator
```

- [ ] **Step 4: Run tests**

```bash
poetry run pytest apps/schedule/tests/test_ratelimit.py -v
```

Expected:
```
4 passed
```

- [ ] **Step 5: Commit**

```bash
git add apps/schedule/ratelimit.py apps/schedule/tests/test_ratelimit.py
git commit -m "feat(schedule): add @require_token rate-limit decorator"
```

---

## Task 6: Janitor and rate-limit refill tasks (TDD)

(per spec §8, "A janitor job scans for `status='running' AND heartbeat < now() - 10min` rows every 5 minutes and resets them to `queued`.")

**Files:**
- Create: `apps/schedule/tests/test_janitor.py`
- Create: `apps/schedule/tasks.py`

- [ ] **Step 1: Write failing tests in `apps/schedule/tests/test_janitor.py`**

```python
"""Tests for janitor and rate-limit refill tasks."""
from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from schedule.models import RateLimitBucket
from schedule.tasks import janitor_reset_stale_running, refill_rate_limit_buckets


@pytest.fixture(autouse=True)
def _eager(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True


def test_refill_rate_limit_buckets_advances_tokens(db):
    bucket = RateLimitBucket.objects.create(
        provider="ncbi_eutils", capacity=10, refill_per_sec=10.0, current_tokens=5.0
    )
    RateLimitBucket.objects.filter(pk=bucket.pk).update(
        updated_at=timezone.now() - timedelta(seconds=2)
    )
    refill_rate_limit_buckets.delay().get(timeout=1)
    bucket.refresh_from_db()
    assert bucket.current_tokens >= 10.0  # capped at capacity


def test_refill_rate_limit_buckets_no_buckets(db):
    # Should not raise even if no buckets exist
    refill_rate_limit_buckets.delay().get(timeout=1)


def test_janitor_resets_stale_running_extraction_runs(db):
    # Phase 1 doesn't have ExtractionRun yet; the janitor scans models we
    # register with it. Verify the registry plumbing is in place by passing
    # an empty list (the default).
    result = janitor_reset_stale_running.delay().get(timeout=1)
    assert isinstance(result, dict)
    assert "total_reset" in result
    assert result["total_reset"] == 0
```

- [ ] **Step 2: Run failing tests**

```bash
poetry run pytest apps/schedule/tests/test_janitor.py -v
```

Expected:
```
ImportError: cannot import name 'janitor_reset_stale_running' from 'schedule.tasks'
```

- [ ] **Step 3: Implement `apps/schedule/tasks.py`**

```python
"""schedule.tasks — Beat-driven housekeeping tasks.

`janitor_reset_stale_running`: scans every registered "long-running"
model for rows in status='running' with stale heartbeats and resets them
to status='queued'. Registry is empty in Phase 1 (no long-running tasks
yet); Phase 2 (extract.ExtractionRun) registers itself with us.

`refill_rate_limit_buckets`: calls `.refill()` on every bucket. The
buckets self-refill on access, but a periodic refill smooths out
edge cases where a provider is idle for hours.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Iterable

from celery import shared_task
from django.apps import apps
from django.db.models import Q
from django.utils import timezone

from schedule.models import RateLimitBucket

logger = logging.getLogger(__name__)

# Apps register their long-running model + status field here so the janitor
# can sweep them. Tuple is (app_label, model_name, status_field, heartbeat_field).
_JANITOR_REGISTRY: list[tuple[str, str, str, str]] = []


def register_janitor_target(
    app_label: str, model_name: str, status_field: str, heartbeat_field: str
) -> None:
    """Register a model for janitor sweeping. Called from each app's apps.py."""
    entry = (app_label, model_name, status_field, heartbeat_field)
    if entry not in _JANITOR_REGISTRY:
        _JANITOR_REGISTRY.append(entry)


def _janitor_targets() -> Iterable[tuple[str, str, str, str]]:
    return list(_JANITOR_REGISTRY)


@shared_task(name="schedule.tasks.janitor_reset_stale_running")
def janitor_reset_stale_running(stale_minutes: int = 10) -> dict:
    """Sweep every registered model; reset stale running rows to queued."""
    cutoff = timezone.now() - timedelta(minutes=stale_minutes)
    summary: dict[str, int] = {}
    total = 0
    for app_label, model_name, status_field, heartbeat_field in _janitor_targets():
        try:
            model = apps.get_model(app_label, model_name)
        except LookupError:
            logger.warning("janitor: unknown model %s.%s", app_label, model_name)
            continue
        qs = model.objects.filter(
            Q(**{status_field: "running"})
            & (Q(**{f"{heartbeat_field}__isnull": True}) | Q(**{f"{heartbeat_field}__lt": cutoff}))
        )
        count = qs.update(**{status_field: "queued", heartbeat_field: None})
        summary[f"{app_label}.{model_name}"] = count
        total += count
    summary["total_reset"] = total
    logger.info("janitor swept: %s", summary)
    return summary


@shared_task(name="schedule.tasks.refill_rate_limit_buckets")
def refill_rate_limit_buckets() -> dict:
    """Walk every bucket and call .refill()."""
    refilled = 0
    for bucket in RateLimitBucket.objects.all():
        bucket.refill()
        refilled += 1
    return {"refilled": refilled}
```

- [ ] **Step 4: Run tests**

```bash
poetry run pytest apps/schedule/tests/test_janitor.py -v
```

Expected:
```
3 passed
```

- [ ] **Step 5: Commit**

```bash
git add apps/schedule/tasks.py apps/schedule/tests/test_janitor.py
git commit -m "feat(schedule): add janitor and rate-limit refill tasks"
```

---

## Task 7: Watermark helpers (TDD)

**Files:**
- Create: `apps/schedule/tests/test_watermarks.py`
- Create: `apps/schedule/watermarks.py`

- [ ] **Step 1: Write failing tests in `apps/schedule/tests/test_watermarks.py`**

```python
"""Tests for schedule.watermarks helpers."""
from __future__ import annotations

from datetime import date

import pytest

from schedule.models import Watermark
from schedule.watermarks import (
    advance_watermark,
    get_watermark,
    reset_watermark,
)


def test_get_watermark_creates_if_missing(db):
    wm = get_watermark("pubmed")
    assert wm.source == "pubmed"
    assert wm.last_pmid_seen is None
    assert Watermark.objects.count() == 1


def test_get_watermark_returns_existing(db):
    Watermark.objects.create(source="pubmed", last_pmid_seen=12345)
    wm = get_watermark("pubmed")
    assert wm.last_pmid_seen == 12345
    assert Watermark.objects.count() == 1


def test_advance_watermark_sets_pmid(db):
    wm = advance_watermark("pubmed", last_pmid_seen=39000000)
    assert wm.last_pmid_seen == 39000000


def test_advance_watermark_only_moves_forward(db):
    advance_watermark("pubmed", last_pmid_seen=39000000)
    wm = advance_watermark("pubmed", last_pmid_seen=12345)
    # Lower PMID must NOT regress the watermark
    assert wm.last_pmid_seen == 39000000


def test_advance_watermark_sets_entrez_date(db):
    wm = advance_watermark("pubmed", last_entrez_date=date(2026, 5, 1))
    assert wm.last_entrez_date == date(2026, 5, 1)


def test_advance_watermark_entrez_date_only_moves_forward(db):
    advance_watermark("pubmed", last_entrez_date=date(2026, 5, 1))
    wm = advance_watermark("pubmed", last_entrez_date=date(2025, 1, 1))
    assert wm.last_entrez_date == date(2026, 5, 1)


def test_reset_watermark_clears_fields(db):
    advance_watermark("pubmed", last_pmid_seen=39000000)
    reset_watermark("pubmed")
    wm = Watermark.objects.get(source="pubmed")
    assert wm.last_pmid_seen is None
    assert wm.last_entrez_date is None
    assert wm.resumption_token == ""
```

- [ ] **Step 2: Run failing tests**

```bash
poetry run pytest apps/schedule/tests/test_watermarks.py -v
```

Expected: ImportError on `schedule.watermarks`.

- [ ] **Step 3: Implement `apps/schedule/watermarks.py`**

```python
"""Watermark helpers — transactional read / advance / reset.

Watermarks track the high-water mark per external source so daily
ingestion picks up exactly where it left off. (per spec §5)
"""
from __future__ import annotations

from datetime import date

from django.db import transaction

from schedule.models import Watermark


def get_watermark(source: str) -> Watermark:
    """Get or create a watermark row for ``source``."""
    wm, _ = Watermark.objects.get_or_create(source=source)
    return wm


@transaction.atomic
def advance_watermark(
    source: str,
    *,
    last_pmid_seen: int | None = None,
    last_entrez_date: date | None = None,
    resumption_token: str | None = None,
) -> Watermark:
    """Move the watermark forward. Never regresses."""
    wm = Watermark.objects.select_for_update().get_or_create(source=source)[0]
    if last_pmid_seen is not None:
        if wm.last_pmid_seen is None or last_pmid_seen > wm.last_pmid_seen:
            wm.last_pmid_seen = last_pmid_seen
    if last_entrez_date is not None:
        if wm.last_entrez_date is None or last_entrez_date > wm.last_entrez_date:
            wm.last_entrez_date = last_entrez_date
    if resumption_token is not None:
        wm.resumption_token = resumption_token
    wm.save()
    return wm


@transaction.atomic
def reset_watermark(source: str) -> None:
    """Clear a watermark — used for full re-sweeps."""
    Watermark.objects.filter(source=source).update(
        last_pmid_seen=None,
        last_entrez_date=None,
        resumption_token="",
    )
```

- [ ] **Step 4: Run tests**

```bash
poetry run pytest apps/schedule/tests/test_watermarks.py -v
```

Expected:
```
7 passed
```

- [ ] **Step 5: Commit**

```bash
git add apps/schedule/watermarks.py apps/schedule/tests/test_watermarks.py
git commit -m "feat(schedule): add watermark helpers (get/advance/reset)"
```

---

## Task 8: Initial RateLimitBucket fixture and Beat schedule module

**Files:**
- Create: `apps/schedule/fixtures/0001_buckets.yaml`
- Create: `apps/schedule/management/__init__.py`
- Create: `apps/schedule/management/commands/__init__.py`
- Create: `apps/schedule/management/commands/seed_rate_limit_buckets.py`
- Create: `apps/schedule/tests/test_seed_buckets.py`
- Create: `apps/schedule/beat_schedule.py`
- Create: `apps/schedule/tests/test_beat_schedule.py`
- Modify: `interactome/settings/base.py`

- [ ] **Step 1: Create `apps/schedule/fixtures/0001_buckets.yaml`**

```yaml
# Initial token-bucket allocations per external provider.
# Capacity = burst size; refill_per_sec = steady-state rate.
# Conservative values; tune in production based on observed 429s.
buckets:
  - provider: ncbi_eutils
    capacity: 10
    refill_per_sec: 10.0   # with API key; 3 without
  - provider: europe_pmc
    capacity: 30
    refill_per_sec: 30.0
  - provider: europe_pmc_oai
    capacity: 10
    refill_per_sec: 5.0
  - provider: pubtator3
    capacity: 10
    refill_per_sec: 10.0
  - provider: ollama_qwen3_8b
    capacity: 4
    refill_per_sec: 2.0
  - provider: grobid
    capacity: 4
    refill_per_sec: 4.0
```

- [ ] **Step 2: Create management command stubs**

`apps/schedule/management/__init__.py` — empty file.

`apps/schedule/management/commands/__init__.py` — empty file.

`apps/schedule/management/commands/seed_rate_limit_buckets.py`:

```python
"""Management command: seed initial RateLimitBucket rows from YAML fixture."""
from __future__ import annotations

from pathlib import Path

import yaml
from django.core.management.base import BaseCommand

from schedule.models import RateLimitBucket


class Command(BaseCommand):
    help = "Seed RateLimitBucket rows from apps/schedule/fixtures/0001_buckets.yaml"

    def handle(self, *args: object, **options: object) -> None:
        fixture_path = Path(__file__).resolve().parents[2] / "fixtures" / "0001_buckets.yaml"
        data = yaml.safe_load(fixture_path.read_text())
        created = 0
        updated = 0
        for entry in data["buckets"]:
            bucket, was_created = RateLimitBucket.objects.update_or_create(
                provider=entry["provider"],
                defaults={
                    "capacity": entry["capacity"],
                    "refill_per_sec": entry["refill_per_sec"],
                    "current_tokens": entry["capacity"],
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {created} new buckets, updated {updated} existing."
            )
        )
```

- [ ] **Step 3: Write the test in `apps/schedule/tests/test_seed_buckets.py`**

```python
"""Test the seed_rate_limit_buckets management command."""
from __future__ import annotations

from django.core.management import call_command

from schedule.models import RateLimitBucket


def test_seed_creates_all_buckets(db):
    call_command("seed_rate_limit_buckets")
    providers = set(RateLimitBucket.objects.values_list("provider", flat=True))
    assert {"ncbi_eutils", "europe_pmc", "europe_pmc_oai", "pubtator3", "grobid"} <= providers


def test_seed_is_idempotent(db):
    call_command("seed_rate_limit_buckets")
    n_first = RateLimitBucket.objects.count()
    call_command("seed_rate_limit_buckets")
    n_second = RateLimitBucket.objects.count()
    assert n_first == n_second
```

- [ ] **Step 4: Run the test**

```bash
poetry run pytest apps/schedule/tests/test_seed_buckets.py -v
```

Expected:
```
2 passed
```

- [ ] **Step 5: Create `apps/schedule/beat_schedule.py`**

```python
"""Phase 1 Celery Beat schedule.

Each entry maps a Celery task name to its run cadence. Beat hot-reloads
this via django_celery_beat's DatabaseScheduler in production; for dev
the schedule is read directly from this Python dict.

(per spec §6 Beat schedule table)
"""
from __future__ import annotations

from celery.schedules import crontab

PHASE_1_BEAT_SCHEDULE: dict[str, dict] = {
    "janitor-reset-stale-running": {
        "task": "schedule.tasks.janitor_reset_stale_running",
        "schedule": crontab(minute="*/5"),
    },
    "refill-rate-limit-buckets": {
        "task": "schedule.tasks.refill_rate_limit_buckets",
        "schedule": crontab(minute="*"),
    },
    "corpus-refresh-pubmed": {
        "task": "corpus.tasks.refresh_pubmed",
        "schedule": crontab(minute=0),  # every hour
    },
    "corpus-refresh-pubmed-full": {
        "task": "corpus.tasks.refresh_pubmed_full",
        "schedule": crontab(minute=0, hour=3, day_of_week=0),  # Sun 03:00 UTC
    },
    "papers-classify-pending": {
        "task": "papers.tasks.classify_pending",
        "schedule": crontab(minute="*/15"),
    },
    "papers-fetch-fulltext-pending": {
        "task": "papers.tasks.fetch_fulltext_pending",
        "schedule": crontab(minute="*/10"),
    },
    "papers-section-pending": {
        "task": "papers.tasks.section_pending",
        "schedule": crontab(minute="*/10"),
    },
    "corpus-triage-pending": {
        "task": "corpus.tasks.triage_pending",
        "schedule": crontab(minute="*/20"),
    },
}
```

- [ ] **Step 6: Wire the schedule into settings** — append to `interactome/settings/base.py`:

```python
# === Celery Beat schedule (Phase 1) ===
from schedule.beat_schedule import PHASE_1_BEAT_SCHEDULE  # noqa: E402

CELERY_BEAT_SCHEDULE = PHASE_1_BEAT_SCHEDULE
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
```

- [ ] **Step 7: Write the test in `apps/schedule/tests/test_beat_schedule.py`**

```python
"""Smoke tests for the Beat schedule."""
from __future__ import annotations

from schedule.beat_schedule import PHASE_1_BEAT_SCHEDULE


def test_beat_schedule_includes_janitor():
    assert "janitor-reset-stale-running" in PHASE_1_BEAT_SCHEDULE


def test_beat_schedule_includes_pubmed_refresh():
    assert "corpus-refresh-pubmed" in PHASE_1_BEAT_SCHEDULE


def test_beat_schedule_entries_have_task_and_schedule():
    for name, entry in PHASE_1_BEAT_SCHEDULE.items():
        assert "task" in entry, name
        assert "schedule" in entry, name


def test_beat_schedule_task_names_are_unique():
    task_names = [e["task"] for e in PHASE_1_BEAT_SCHEDULE.values()]
    assert len(task_names) == len(set(task_names))
```

- [ ] **Step 8: Run tests**

```bash
poetry run pytest apps/schedule/tests/test_beat_schedule.py -v
```

Expected:
```
4 passed
```

- [ ] **Step 9: Commit**

```bash
git add apps/schedule/fixtures apps/schedule/management apps/schedule/beat_schedule.py apps/schedule/tests/test_seed_buckets.py apps/schedule/tests/test_beat_schedule.py interactome/settings/base.py
git commit -m "feat(schedule): seed rate-limit buckets and wire Phase 1 Beat schedule"
```

---

## Task 9: `networks` app models (TDD)

(per spec §2, "the 200+ network registry, per-network search queries, eligible protein families, status".)

**Files:**
- Create: `apps/networks/tests/test_models.py`
- Modify: `apps/networks/models.py`

- [ ] **Step 1: Write failing tests in `apps/networks/tests/test_models.py`**

```python
"""Tests for networks.models."""
from __future__ import annotations

import pytest
from django.db import IntegrityError

from networks.models import FamilyFilter, Network, NetworkQuery


def test_network_round_trip(db):
    n = Network.objects.create(
        code="nfkb_axis",
        category="I",
        title="NF-κB Axis",
        description="Canonical NF-κB pathway driving catabolic gene expression.",
        is_active=True,
    )
    assert n.pk is not None
    assert n.pipeline_status == "idle"


def test_network_code_is_unique(db):
    Network.objects.create(code="nfkb_axis", category="I", title="NF-κB Axis")
    with pytest.raises(IntegrityError):
        Network.objects.create(code="nfkb_axis", category="I", title="dup")


def test_network_keywords_list(db):
    n = Network.objects.create(
        code="nfkb_axis",
        category="I",
        title="NF-κB Axis",
        keywords=["NF-kB", "RELA", "p65", "IKK"],
    )
    n.refresh_from_db()
    assert "RELA" in n.keywords


def test_network_root_entity_aliases(db):
    n = Network.objects.create(
        code="nfkb_axis",
        category="I",
        title="NF-κB Axis",
        root_entity_aliases=["NFKB1", "NFKB2", "RELA", "RELB"],
    )
    n.refresh_from_db()
    assert "NFKB1" in n.root_entity_aliases


def test_network_pipeline_status_choices(db):
    n = Network.objects.create(code="nfkb_axis", category="I", title="NF-κB Axis")
    for status in ["idle", "refreshing", "stale", "version_draft", "verified"]:
        n.pipeline_status = status
        n.save()
        n.refresh_from_db()
        assert n.pipeline_status == status


def test_network_query_round_trip(db):
    n = Network.objects.create(code="nfkb_axis", category="I", title="NF-κB Axis")
    q = NetworkQuery.objects.create(
        network=n,
        purpose="discovery",
        query='"NF-kB"[TIAB] OR RELA[TIAB]',
    )
    assert q.pk is not None
    assert q.network == n


def test_network_query_purpose_choices(db):
    n = Network.objects.create(code="nfkb_axis", category="I", title="NF-κB Axis")
    for p in ["discovery", "triage_cheap", "expansion"]:
        NetworkQuery.objects.create(network=n, purpose=p, query="x")


def test_family_filter_round_trip(db):
    n = Network.objects.create(code="nfkb_axis", category="I", title="NF-κB Axis")
    f = FamilyFilter.objects.create(
        network=n,
        family_name="NF-kB transcription factors",
        uniprot_family_id="UF000123",
        members=["NFKB1", "NFKB2", "RELA", "RELB", "REL"],
    )
    assert f.pk is not None
    assert "REL" in f.members


def test_network_str(db):
    n = Network.objects.create(code="nfkb_axis", category="I", title="NF-κB Axis")
    assert "nfkb_axis" in str(n)
```

- [ ] **Step 2: Run failing tests**

```bash
poetry run pytest apps/networks/tests/test_models.py -v
```

Expected: ImportError on `networks.models`.

- [ ] **Step 3: Implement `apps/networks/models.py`**

```python
"""networks models — Network, NetworkQuery, FamilyFilter.

A Network is a regulatory module the system is trying to assemble
(e.g. "NF-κB axis", "TGF-β / BMP / SMAD"). It carries the metadata
needed by every downstream stage:

- ``keywords`` and ``root_entity_aliases`` drive the cheap relevance
  pass in ``corpus.triage_relevance_cheap``.
- ``pipeline_status`` is the per-network state machine from spec §7.
- NetworkQuery rows hold the PubMed/Europe PMC query strings used by
  ``corpus.refresh_pubmed`` for network-targeted discovery.
- FamilyFilter constrains which protein families are eligible to
  appear in this network (per spec §2).
"""
from __future__ import annotations

from django.db import models

from core.models import TimestampedModel


class Network(TimestampedModel):
    PIPELINE_STATUS_CHOICES = [
        ("idle", "idle"),
        ("refreshing", "refreshing"),
        ("stale", "stale"),
        ("version_draft", "version_draft"),
        ("verified", "verified"),
    ]

    code = models.SlugField(max_length=64, unique=True)
    category = models.CharField(max_length=8)
    title = models.CharField(max_length=256)
    description = models.TextField(blank=True, default="")
    keywords = models.JSONField(default=list, blank=True)
    # Free-text alias strings ("NF-κB", "RelA", "p65") for cheap keyword
    # relevance triage.
    root_entity_aliases = models.JSONField(default=list, blank=True)
    # Structured identifier dicts ({"scheme": "HGNC", "value": "7794"}) used by
    # Phase 3's NetworkEdgeMembership assignment. Distinct from the aliases
    # above. See cross-plan reconciliation doc §6/§8.
    root_entities = models.JSONField(default=list, blank=True)
    pipeline_status = models.CharField(
        max_length=24, choices=PIPELINE_STATUS_CHOICES, default="idle"
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "networks_network"
        ordering = ["category", "code"]

    def __str__(self) -> str:
        return f"Network<{self.code}>"


class NetworkQuery(TimestampedModel):
    PURPOSE_CHOICES = [
        ("discovery", "discovery"),
        ("triage_cheap", "triage_cheap"),
        ("expansion", "expansion"),
    ]

    network = models.ForeignKey(Network, related_name="queries", on_delete=models.CASCADE)
    purpose = models.CharField(max_length=24, choices=PURPOSE_CHOICES)
    query = models.TextField()
    notes = models.TextField(blank=True, default="")

    class Meta:
        db_table = "networks_networkquery"
        constraints = [
            models.UniqueConstraint(
                fields=["network", "purpose"], name="uniq_network_query_purpose"
            )
        ]


class FamilyFilter(TimestampedModel):
    network = models.ForeignKey(Network, related_name="family_filters", on_delete=models.CASCADE)
    family_name = models.CharField(max_length=128)
    uniprot_family_id = models.CharField(max_length=32, blank=True, default="")
    members = models.JSONField(default=list, blank=True)
    is_inclusion = models.BooleanField(default=True)

    class Meta:
        db_table = "networks_familyfilter"
```

- [ ] **Step 4: Generate the migration**

```bash
poetry run python manage.py makemigrations networks
```

Expected:
```
Migrations for 'networks':
  apps/networks/migrations/0001_initial.py
    + Create model Network
    + Create model FamilyFilter
    + Create model NetworkQuery
```

- [ ] **Step 5: Run the tests**

```bash
poetry run pytest apps/networks/tests/test_models.py -v
```

Expected:
```
9 passed
```

- [ ] **Step 6: Commit**

```bash
git add apps/networks/models.py apps/networks/migrations/ apps/networks/tests/test_models.py
git commit -m "feat(networks): add Network, NetworkQuery, FamilyFilter models"
```

---

## Task 10: Networks taxonomy fixture and loader (TDD)

(per spec Appendix A, "Full enumeration lives in `networks/fixtures/0001_taxonomy.yaml`".)

The implementer must populate all 200+ networks across the 17 categories per spec Appendix A. This task seeds 10 representative entries inline that span 4 categories; the implementer fills out the remaining ~190 using the same schema.

**Files:**
- Create: `apps/networks/fixtures/0001_taxonomy.yaml`
- Create: `apps/networks/management/__init__.py`
- Create: `apps/networks/management/commands/__init__.py`
- Create: `apps/networks/management/commands/load_network_taxonomy.py`
- Create: `apps/networks/tests/test_load_taxonomy.py`

- [ ] **Step 1: Create `apps/networks/fixtures/0001_taxonomy.yaml`**

```yaml
# IVD Regulatory Network Taxonomy (spec Appendix A)
#
# Each entry seeds one Network row. The implementer MUST populate every
# network listed in spec Appendix A, organised by Roman-numeral category.
# The 10 examples below illustrate the schema; copy/paste pattern for the
# rest.
#
# Categories (use these exact Roman numerals):
#   I    Core Signaling Pathway Networks (~16 entries)
#   II   Transcription Factor Networks (~12 entries)
#   III  Epigenetic Regulatory Networks (~10 entries)
#   IV   Non-Coding RNA Networks (~12 entries)
#   V    ECM / Matrix Remodeling Networks (~12 entries)
#   VI   Growth Factor / Cytokine Networks (~14 entries)
#   VII  Metabolic Regulatory Networks (~10 entries)
#   VIII Mechanobiology Networks (~10 entries)
#   IX   Cell Type-Specific Networks (~8 entries)
#   X    Neurovascular Networks (~8 entries)
#   XI   Cell Fate / Differentiation Networks (~10 entries)
#   XII  Inter-Tissue / Systemic Crosstalk Networks (~10 entries)
#   XIII GWAS / Genetic Regulatory Networks (~8 entries)
#   XIV  Disease-Specific Regulatory Networks (~12 entries)
#   XV   Therapeutic / Regenerative Networks (~10 entries)
#   XVI  Proteostasis / UPR Networks (~8 entries)
#   XVII Multi-Omics Integration Networks (~10 entries)
#
# Target total: 200+ Network rows.

networks:
  # === Category I: Core Signaling Pathway Networks ===
  - code: nfkb_axis
    category: I
    title: "NF-κB Axis (MMP/ADAMTS catabolic output)"
    description: >
      Canonical NF-κB pathway driving catabolic gene expression in
      nucleus pulposus cells under IL-1β / TNF-α stimulation.
    keywords:
      - "NF-kB"
      - "NF-κB"
      - "NFKB"
      - "RELA"
      - "p65"
      - "IKK"
      - "IkBalpha"
    root_entity_aliases:
      - "NFKB1"
      - "NFKB2"
      - "RELA"
      - "RELB"
      - "REL"
      - "IKBKB"
      - "IKBKG"
      - "CHUK"

  - code: tgfb_bmp_smad
    category: I
    title: "TGF-β / BMP / SMAD pathway"
    description: >
      TGF-β and BMP ligands signalling through SMAD2/3 and SMAD1/5/8;
      central to ECM homeostasis and disc differentiation.
    keywords:
      - "TGF-beta"
      - "TGF-β"
      - "BMP"
      - "SMAD"
      - "TGFBR"
      - "BMPR"
    root_entity_aliases:
      - "TGFB1"
      - "TGFB2"
      - "TGFB3"
      - "BMP2"
      - "BMP7"
      - "SMAD2"
      - "SMAD3"
      - "SMAD4"

  - code: wnt_beta_catenin
    category: I
    title: "Wnt / β-catenin pathway"
    description: >
      Canonical Wnt signalling via β-catenin nuclear translocation;
      implicated in notochordal-cell fate and degeneration progression.
    keywords:
      - "Wnt"
      - "beta-catenin"
      - "β-catenin"
      - "CTNNB1"
      - "DKK"
      - "Frizzled"
    root_entity_aliases:
      - "WNT3A"
      - "WNT5A"
      - "CTNNB1"
      - "DKK1"
      - "DKK3"
      - "LRP5"
      - "LRP6"
      - "FZD7"

  - code: pi3k_akt_mtor
    category: I
    title: "PI3K / AKT / mTOR pathway"
    description: >
      Growth and survival signalling axis; modulates autophagy and
      anabolic ECM synthesis in disc cells.
    keywords:
      - "PI3K"
      - "AKT"
      - "mTOR"
      - "PTEN"
      - "S6K"
      - "4EBP1"
    root_entity_aliases:
      - "PIK3CA"
      - "AKT1"
      - "MTOR"
      - "PTEN"
      - "RPS6KB1"
      - "EIF4EBP1"

  - code: hif_hypoxia
    category: I
    title: "Hypoxia / HIF pathway"
    description: >
      HIF-1α / HIF-2α responses to the avascular, low-O₂ disc niche;
      master regulator of NP-cell metabolism.
    keywords:
      - "hypoxia"
      - "HIF"
      - "HIF-1"
      - "HIF-2"
      - "VHL"
      - "PHD"
    root_entity_aliases:
      - "HIF1A"
      - "EPAS1"
      - "ARNT"
      - "VHL"
      - "EGLN1"
      - "EGLN2"
      - "EGLN3"

  # === Category II: Transcription Factor Networks ===
  - code: tf_sox9
    category: II
    title: "Sox9 transcription factor network"
    description: >
      SOX9-driven chondrogenic / NP-progenitor gene programme.
    keywords:
      - "SOX9"
      - "Sox9"
      - "L-Sox5"
      - "Sox6"
    root_entity_aliases:
      - "SOX9"
      - "SOX5"
      - "SOX6"

  - code: tf_brachyury
    category: II
    title: "Brachyury (T/TBXT) network"
    description: >
      Brachyury / TBXT master regulator of notochordal-cell identity
      and persistence.
    keywords:
      - "Brachyury"
      - "TBXT"
    root_entity_aliases:
      - "TBXT"
      - "T"
      - "TBX6"

  # === Category V: ECM / Matrix Remodeling Networks ===
  - code: ecm_mmp
    category: V
    title: "Matrix metalloproteinase (MMP) network"
    description: >
      MMP-1/2/3/9/13 mediated ECM catabolism in disc degeneration.
    keywords:
      - "MMP"
      - "MMP1"
      - "MMP3"
      - "MMP9"
      - "MMP13"
      - "matrix metalloproteinase"
    root_entity_aliases:
      - "MMP1"
      - "MMP2"
      - "MMP3"
      - "MMP9"
      - "MMP13"
      - "MMP14"

  - code: ecm_adamts
    category: V
    title: "ADAMTS aggrecanase network"
    description: >
      ADAMTS-4/-5 mediated aggrecan cleavage; central disc-catabolic
      output.
    keywords:
      - "ADAMTS"
      - "ADAMTS4"
      - "ADAMTS5"
      - "aggrecanase"
    root_entity_aliases:
      - "ADAMTS4"
      - "ADAMTS5"
      - "ADAMTS7"
      - "ADAMTS12"

  # === Category VIII: Mechanobiology Networks ===
  - code: mechano_piezo
    category: VIII
    title: "Piezo channel mechanotransduction"
    description: >
      Piezo1/Piezo2 mechanosensitive ion channels mediating
      compression-induced calcium signalling in disc cells.
    keywords:
      - "Piezo1"
      - "Piezo2"
      - "PIEZO"
      - "mechanosensitive"
    root_entity_aliases:
      - "PIEZO1"
      - "PIEZO2"

  # IMPLEMENTER: continue populating Categories I-XVII per spec
  # Appendix A until ~200 entries are present.
```

- [ ] **Step 2: Create management command stubs**

`apps/networks/management/__init__.py` — empty file.

`apps/networks/management/commands/__init__.py` — empty file.

`apps/networks/management/commands/load_network_taxonomy.py`:

```python
"""Management command: load the Network taxonomy from YAML fixture.

Idempotent: re-running updates existing rows by ``code``.
"""
from __future__ import annotations

from pathlib import Path

import yaml
from django.core.management.base import BaseCommand

from networks.models import Network


class Command(BaseCommand):
    help = "Load the Network taxonomy from apps/networks/fixtures/0001_taxonomy.yaml"

    def handle(self, *args: object, **options: object) -> None:
        fixture = Path(__file__).resolve().parents[2] / "fixtures" / "0001_taxonomy.yaml"
        data = yaml.safe_load(fixture.read_text())
        created = 0
        updated = 0
        for entry in data["networks"]:
            _, was_created = Network.objects.update_or_create(
                code=entry["code"],
                defaults={
                    "category": entry["category"],
                    "title": entry["title"],
                    "description": entry.get("description", ""),
                    "keywords": entry.get("keywords", []),
                    "root_entity_aliases": entry.get("root_entity_aliases", []),
                    "is_active": entry.get("is_active", True),
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1
        self.stdout.write(
            self.style.SUCCESS(f"Loaded {created} new networks, updated {updated}.")
        )
```

- [ ] **Step 3: Write the test in `apps/networks/tests/test_load_taxonomy.py`**

```python
"""Tests for the load_network_taxonomy management command."""
from __future__ import annotations

from django.core.management import call_command

from networks.models import Network


def test_load_taxonomy_creates_networks(db):
    call_command("load_network_taxonomy")
    codes = set(Network.objects.values_list("code", flat=True))
    assert "nfkb_axis" in codes
    assert "tgfb_bmp_smad" in codes
    assert "ecm_mmp" in codes


def test_load_taxonomy_is_idempotent(db):
    call_command("load_network_taxonomy")
    n1 = Network.objects.count()
    call_command("load_network_taxonomy")
    n2 = Network.objects.count()
    assert n1 == n2


def test_load_taxonomy_populates_keywords(db):
    call_command("load_network_taxonomy")
    nfkb = Network.objects.get(code="nfkb_axis")
    assert "RELA" in nfkb.keywords or "NF-kB" in nfkb.keywords


def test_load_taxonomy_populates_root_aliases(db):
    call_command("load_network_taxonomy")
    nfkb = Network.objects.get(code="nfkb_axis")
    assert "NFKB1" in nfkb.root_entity_aliases


def test_load_taxonomy_categories_use_roman_numerals(db):
    call_command("load_network_taxonomy")
    for cat in Network.objects.values_list("category", flat=True).distinct():
        assert cat in {
            "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX",
            "X", "XI", "XII", "XIII", "XIV", "XV", "XVI", "XVII",
        }
```

- [ ] **Step 4: Run the tests**

```bash
poetry run pytest apps/networks/tests/test_load_taxonomy.py -v
```

Expected:
```
5 passed
```

- [ ] **Step 5: Commit**

```bash
git add apps/networks/fixtures apps/networks/management apps/networks/tests/test_load_taxonomy.py
git commit -m "feat(networks): seed network taxonomy fixture + loader command"
```

---

## Task 11: `networks.services` — public API (TDD)

**Files:**
- Create: `apps/networks/tests/test_services.py`
- Modify: `apps/networks/services.py`

- [ ] **Step 1: Write failing tests in `apps/networks/tests/test_services.py`**

```python
"""Tests for networks.services."""
from __future__ import annotations

import pytest

from networks.models import Network
from networks.services import (
    NetworkNotFound,
    get_network,
    list_active_networks,
    networks_by_category,
)


@pytest.fixture
def seeded_networks(db):
    a = Network.objects.create(code="nfkb_axis", category="I", title="NF-κB Axis")
    b = Network.objects.create(code="tgfb_bmp_smad", category="I", title="TGF-β/BMP/SMAD")
    c = Network.objects.create(
        code="archived_x", category="I", title="Archived", is_active=False
    )
    return a, b, c


def test_get_network_returns_match(db, seeded_networks):
    n = get_network("nfkb_axis")
    assert n.code == "nfkb_axis"


def test_get_network_unknown_raises(db):
    with pytest.raises(NetworkNotFound):
        get_network("does_not_exist")


def test_list_active_networks_excludes_inactive(db, seeded_networks):
    codes = {n.code for n in list_active_networks()}
    assert "nfkb_axis" in codes
    assert "archived_x" not in codes


def test_networks_by_category_groups(db, seeded_networks):
    by_cat = networks_by_category()
    assert "I" in by_cat
    codes = {n.code for n in by_cat["I"]}
    assert "nfkb_axis" in codes
    assert "tgfb_bmp_smad" in codes
```

- [ ] **Step 2: Run failing tests**

```bash
poetry run pytest apps/networks/tests/test_services.py -v
```

Expected: ImportError on `networks.services`.

- [ ] **Step 3: Implement `apps/networks/services.py`**

```python
"""Public API for the networks app.

Other apps (corpus, papers, dashboard, ...) call functions here, not
the underlying models, per spec §2's boundary discipline.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from networks.models import Network


class NetworkNotFound(LookupError):
    """Raised by ``get_network`` when ``code`` does not exist."""


def get_network(code: str) -> Network:
    try:
        return Network.objects.get(code=code)
    except Network.DoesNotExist as exc:
        raise NetworkNotFound(code) from exc


def list_active_networks() -> Iterable[Network]:
    return Network.objects.filter(is_active=True).order_by("category", "code")


def networks_by_category() -> dict[str, list[Network]]:
    grouped: dict[str, list[Network]] = defaultdict(list)
    for n in list_active_networks():
        grouped[n.category].append(n)
    return dict(grouped)
```

- [ ] **Step 4: Run tests**

```bash
poetry run pytest apps/networks/tests/test_services.py -v
```

Expected:
```
4 passed
```

- [ ] **Step 5: Commit**

```bash
git add apps/networks/services.py apps/networks/tests/test_services.py
git commit -m "feat(networks): add services.py public API"
```

---

## Task 12: `core.OllamaClient` with Authelia first-factor auth (TDD)

The Ollama gateway sits behind Authelia. The client must `POST /api/firstfactor` with credentials, capture the `authelia_session` cookie, and reuse it for every Ollama API call. Re-authenticate once on a 401 (cookie expired). Credentials come from env vars set at deploy time.

**Files:**
- Create: `apps/core/tests/test_ollama.py`
- Create: `apps/core/ollama.py`

- [ ] **Step 1: Write failing tests in `apps/core/tests/test_ollama.py`**

```python
"""Tests for core.ollama.OllamaClient."""
from __future__ import annotations

import json

import pytest
from pytest_httpx import HTTPXMock

from core.ollama import OllamaAuthError, OllamaClient, OllamaResponseError


@pytest.fixture
def client(settings):
    settings.OLLAMA_BASE_URL = "https://ollama.example.com"
    settings.OLLAMA_AUTHELIA_BASE = "https://authelia.example.com"
    settings.OLLAMA_USER = "alice"
    settings.OLLAMA_PASSWORD = "s3cret"
    settings.OLLAMA_DEFAULT_TIMEOUT = 30.0
    settings.OLLAMA_KEEP_ALIVE = "2h"
    return OllamaClient()


def test_ollama_client_authenticates_via_authelia(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="POST",
        url="https://authelia.example.com/api/firstfactor",
        json={"status": "OK"},
        headers={"Set-Cookie": "authelia_session=abc123; Path=/"},
    )
    httpx_mock.add_response(
        method="POST",
        url="https://ollama.example.com/api/generate",
        json={"response": "hello world", "done": True},
    )
    result = client.generate(model="qwen3:8b", prompt="hi")
    assert result["response"] == "hello world"


def test_ollama_client_sends_session_cookie_on_generate(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="POST",
        url="https://authelia.example.com/api/firstfactor",
        json={"status": "OK"},
        headers={"Set-Cookie": "authelia_session=cookieval; Path=/"},
    )
    httpx_mock.add_response(
        method="POST",
        url="https://ollama.example.com/api/generate",
        json={"response": "x", "done": True},
    )
    client.generate(model="qwen3:8b", prompt="hi")
    second_request = httpx_mock.get_requests()[1]
    assert "authelia_session=cookieval" in second_request.headers.get("cookie", "")


def test_ollama_client_raises_on_authelia_401(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="POST",
        url="https://authelia.example.com/api/firstfactor",
        status_code=401,
        json={"status": "KO", "message": "bad credentials"},
    )
    with pytest.raises(OllamaAuthError):
        client.generate(model="qwen3:8b", prompt="hi")


def test_ollama_client_raises_on_ollama_5xx(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="POST",
        url="https://authelia.example.com/api/firstfactor",
        json={"status": "OK"},
        headers={"Set-Cookie": "authelia_session=ok; Path=/"},
    )
    httpx_mock.add_response(
        method="POST",
        url="https://ollama.example.com/api/generate",
        status_code=503,
        text="service unavailable",
    )
    with pytest.raises(OllamaResponseError):
        client.generate(model="qwen3:8b", prompt="hi")


def test_ollama_client_reuses_session_across_calls(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="POST",
        url="https://authelia.example.com/api/firstfactor",
        json={"status": "OK"},
        headers={"Set-Cookie": "authelia_session=once; Path=/"},
    )
    for _ in range(2):
        httpx_mock.add_response(
            method="POST",
            url="https://ollama.example.com/api/generate",
            json={"response": "y", "done": True},
        )
    client.generate(model="qwen3:8b", prompt="a")
    client.generate(model="qwen3:8b", prompt="b")
    auth_calls = [r for r in httpx_mock.get_requests() if "firstfactor" in str(r.url)]
    assert len(auth_calls) == 1


def test_ollama_client_format_constraint_passed_through(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="POST",
        url="https://authelia.example.com/api/firstfactor",
        json={"status": "OK"},
        headers={"Set-Cookie": "authelia_session=z; Path=/"},
    )
    httpx_mock.add_response(
        method="POST",
        url="https://ollama.example.com/api/generate",
        json={"response": '{"is_original": true}', "done": True},
    )
    schema = {"type": "object", "properties": {"is_original": {"type": "boolean"}}}
    client.generate(model="qwen3:8b", prompt="hi", format=schema)
    gen_request = [r for r in httpx_mock.get_requests() if "/api/generate" in str(r.url)][0]
    body = json.loads(gen_request.content)
    assert body["format"] == schema
    assert body["model"] == "qwen3:8b"
    assert body["prompt"] == "hi"


def test_ollama_client_chat_endpoint(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="POST",
        url="https://authelia.example.com/api/firstfactor",
        json={"status": "OK"},
        headers={"Set-Cookie": "authelia_session=z; Path=/"},
    )
    httpx_mock.add_response(
        method="POST",
        url="https://ollama.example.com/api/chat",
        json={"message": {"role": "assistant", "content": "hello"}, "done": True},
    )
    result = client.chat(
        model="qwen3:8b",
        messages=[{"role": "user", "content": "hi"}],
    )
    assert result["message"]["content"] == "hello"
```

- [ ] **Step 2: Run failing tests**

```bash
poetry run pytest apps/core/tests/test_ollama.py -v
```

Expected: ImportError on `core.ollama`.

- [ ] **Step 3: Implement `apps/core/ollama.py`**

```python
"""Ollama HTTP client with Authelia first-factor authentication.

Flow:
1. ``_login()`` POSTs ``{username, password}`` to
   ``{AUTHELIA_BASE}/api/firstfactor``. Authelia returns 200 plus a
   ``Set-Cookie: authelia_session=...`` cookie on success.
2. The cookie persists in the httpx Client cookie jar and is reused on
   every subsequent Ollama API call.
3. ``generate()`` and ``chat()`` POST against the Ollama API,
   automatically including the cookie. A 401 (cookie expired) triggers
   one re-login attempt before raising.

Settings:
    OLLAMA_BASE_URL — Ollama gateway URL (https://ollama.<cluster>)
    OLLAMA_AUTHELIA_BASE — Authelia URL (https://authelia.<cluster>)
    OLLAMA_USER / OLLAMA_PASSWORD — env-injected credentials
    OLLAMA_DEFAULT_TIMEOUT — seconds (default 120)
    OLLAMA_KEEP_ALIVE — Ollama model-keep-alive hint (default "2h")
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)


class OllamaAuthError(RuntimeError):
    """Authelia rejected the username/password."""


class OllamaResponseError(RuntimeError):
    """Ollama returned a non-2xx outside the auth domain."""


class OllamaClient:
    """One instance per worker process is the intended use.

    Reuses a single httpx.Client with HTTP/2 + cookie persistence so we
    don't redo the Authelia handshake on every call.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        authelia_base: str | None = None,
        username: str | None = None,
        password: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.authelia_base = (
            authelia_base or settings.OLLAMA_AUTHELIA_BASE
        ).rstrip("/")
        self.username = username or settings.OLLAMA_USER
        self.password = password or settings.OLLAMA_PASSWORD
        self.timeout = timeout if timeout is not None else settings.OLLAMA_DEFAULT_TIMEOUT
        self.keep_alive = settings.OLLAMA_KEEP_ALIVE
        self._client = httpx.Client(
            http2=True,
            timeout=self.timeout,
            follow_redirects=True,
        )
        self._authenticated = False

    # ------------------------- auth -------------------------

    def _login(self) -> None:
        url = f"{self.authelia_base}/api/firstfactor"
        response = self._client.post(
            url,
            json={
                "username": self.username,
                "password": self.password,
                "keepMeLoggedIn": True,
            },
        )
        if response.status_code != 200:
            raise OllamaAuthError(
                f"Authelia /api/firstfactor returned {response.status_code}: "
                f"{response.text[:200]}"
            )
        self._authenticated = True

    def _ensure_authenticated(self) -> None:
        if not self._authenticated:
            self._login()

    # ------------------------- API --------------------------

    def generate(
        self,
        *,
        model: str,
        prompt: str,
        format: dict | str | None = None,
        options: dict | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": stream,
            "keep_alive": self.keep_alive,
        }
        if format is not None:
            payload["format"] = format
        if options is not None:
            payload["options"] = options
        return self._post_with_auth("/api/generate", payload)

    def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        format: dict | str | None = None,
        options: dict | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "keep_alive": self.keep_alive,
        }
        if format is not None:
            payload["format"] = format
        if options is not None:
            payload["options"] = options
        return self._post_with_auth("/api/chat", payload)

    # ------------------------- internals -------------------

    def _post_with_auth(self, path: str, payload: dict) -> dict[str, Any]:
        self._ensure_authenticated()
        url = f"{self.base_url}{path}"
        response = self._client.post(url, json=payload)

        if response.status_code == 401:
            # Cookie expired; re-login once and retry.
            self._authenticated = False
            self._login()
            response = self._client.post(url, json=payload)

        if not response.is_success:
            raise OllamaResponseError(
                f"Ollama {path} returned {response.status_code}: "
                f"{response.text[:200]}"
            )
        return response.json()

    def close(self) -> None:
        self._client.close()
```

- [ ] **Step 4: Run tests**

```bash
poetry run pytest apps/core/tests/test_ollama.py -v
```

Expected:
```
7 passed
```

- [ ] **Step 5: Commit**

```bash
git add apps/core/ollama.py apps/core/tests/test_ollama.py
git commit -m "feat(core): add OllamaClient with Authelia first-factor auth"
```

---

## Task 13: `core.MinioClient` wrapper (TDD)

A thin wrapper around boto3 S3 that knows about our two buckets (`papers`, `sbml-artifacts`) and the PMID-prefix sharding scheme (per spec §5 storage table: `papers/<pmid_prefix>/<pmid>.{xml,pdf,tei}`).

**Files:**
- Create: `apps/core/tests/test_minio_client.py`
- Create: `apps/core/minio_client.py`

- [ ] **Step 1: Write failing tests in `apps/core/tests/test_minio_client.py`**

```python
"""Tests for core.minio_client.MinioClient."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.minio_client import MinioClient, paper_object_key


def test_paper_object_key_shards_by_first_four_digits():
    assert paper_object_key(38000123, "xml") == "papers/3800/38000123.xml"


def test_paper_object_key_zero_pads_short_pmids():
    assert paper_object_key(12345, "pdf") == "papers/0001/12345.pdf"


def test_paper_object_key_supports_tei_extension():
    assert paper_object_key(38000123, "tei") == "papers/3800/38000123.tei"


def test_paper_object_key_rejects_unknown_extension():
    with pytest.raises(ValueError):
        paper_object_key(1, "exe")


def test_minio_client_put_object_calls_boto3():
    fake_boto = MagicMock()
    with patch("core.minio_client._build_s3_client", return_value=fake_boto):
        client = MinioClient()
        client.put_object("papers", "papers/3800/38000123.xml", b"<xml/>", "application/xml")
    fake_boto.put_object.assert_called_once()
    kwargs = fake_boto.put_object.call_args.kwargs
    assert kwargs["Bucket"] == "papers"
    assert kwargs["Key"] == "papers/3800/38000123.xml"
    assert kwargs["Body"] == b"<xml/>"
    assert kwargs["ContentType"] == "application/xml"


def test_minio_client_get_object_returns_bytes():
    fake_boto = MagicMock()
    fake_boto.get_object.return_value = {"Body": MagicMock(read=MagicMock(return_value=b"data"))}
    with patch("core.minio_client._build_s3_client", return_value=fake_boto):
        client = MinioClient()
        data = client.get_object("papers", "papers/3800/38000123.xml")
    assert data == b"data"


def test_minio_client_ensure_buckets_creates_missing(settings):
    settings.MINIO_BUCKET_PAPERS = "papers"
    settings.MINIO_BUCKET_SBML = "sbml-artifacts"
    fake_boto = MagicMock()
    fake_boto.head_bucket.side_effect = Exception("not found")
    with patch("core.minio_client._build_s3_client", return_value=fake_boto):
        client = MinioClient()
        client.ensure_buckets()
    assert fake_boto.create_bucket.call_count >= 2
```

- [ ] **Step 2: Run failing tests**

```bash
poetry run pytest apps/core/tests/test_minio_client.py -v
```

Expected: ImportError on `core.minio_client`.

- [ ] **Step 3: Implement `apps/core/minio_client.py`**

```python
"""MinIO / S3-compatible blob storage wrapper.

Holds the PMID-prefix sharding scheme and the small set of buckets the
project uses. Boto3 is used for the wire protocol; MinIO speaks S3.

(per spec §5 storage table — papers/<pmid_prefix>/<pmid>.{xml,pdf,tei})
"""
from __future__ import annotations

import logging
from typing import Any

import boto3
from botocore.client import Config
from django.conf import settings

logger = logging.getLogger(__name__)

ALLOWED_PAPER_EXTENSIONS = {"xml", "pdf", "tei", "json"}


def paper_object_key(pmid: int, extension: str) -> str:
    """Return the canonical object key for a paper artifact.

    Sharding: first 4 digits of the zero-padded PMID. PMID 12345 →
    "papers/0001/12345.pdf"; PMID 38000123 → "papers/3800/38000123.xml".
    """
    if extension not in ALLOWED_PAPER_EXTENSIONS:
        raise ValueError(f"unknown extension {extension!r}")
    padded = f"{pmid:08d}"
    prefix = padded[:4]
    return f"papers/{prefix}/{pmid}.{extension}"


def _build_s3_client() -> Any:
    return boto3.client(
        "s3",
        endpoint_url=settings.MINIO_ENDPOINT_URL,
        aws_access_key_id=settings.MINIO_ACCESS_KEY,
        aws_secret_access_key=settings.MINIO_SECRET_KEY,
        region_name=settings.MINIO_REGION,
        config=Config(signature_version="s3v4"),
    )


class MinioClient:
    """Thin facade over boto3. One instance per worker process is fine."""

    def __init__(self) -> None:
        self._s3 = _build_s3_client()

    def put_object(
        self,
        bucket: str,
        key: str,
        body: bytes,
        content_type: str,
    ) -> None:
        self._s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=body,
            ContentType=content_type,
        )

    def get_object(self, bucket: str, key: str) -> bytes:
        response = self._s3.get_object(Bucket=bucket, Key=key)
        return response["Body"].read()

    def object_exists(self, bucket: str, key: str) -> bool:
        try:
            self._s3.head_object(Bucket=bucket, Key=key)
            return True
        except Exception:
            return False

    def ensure_buckets(self) -> None:
        """Create the project's buckets if they don't exist (idempotent)."""
        for bucket in (settings.MINIO_BUCKET_PAPERS, settings.MINIO_BUCKET_SBML):
            try:
                self._s3.head_bucket(Bucket=bucket)
            except Exception:
                logger.info("creating bucket %s", bucket)
                self._s3.create_bucket(Bucket=bucket)
```

- [ ] **Step 4: Run tests**

```bash
poetry run pytest apps/core/tests/test_minio_client.py -v
```

Expected:
```
7 passed
```

- [ ] **Step 5: Commit**

```bash
git add apps/core/minio_client.py apps/core/tests/test_minio_client.py
git commit -m "feat(core): add MinioClient wrapper with PMID-prefix sharding"
```

---

## Task 14: `corpus` models — Paper, PaperRelevance, IngestRun (TDD)

(per spec §3 tables; `Paper` is "PK = pmid", with the status fields driving the pipeline; the whole corpus = `SELECT * FROM corpus_paper`.)

**Files:**
- Create: `apps/corpus/tests/conftest.py`
- Create: `apps/corpus/tests/test_models.py`
- Modify: `apps/corpus/models.py`

- [ ] **Step 1: Create `apps/corpus/tests/conftest.py`**

```python
"""Shared pytest fixtures for the corpus app."""
from __future__ import annotations

from datetime import date

import pytest

from corpus.models import Paper
from networks.models import Network


@pytest.fixture
def paper_minimal(db) -> Paper:
    return Paper.objects.create(
        pmid=38000123,
        title="A study of nucleus pulposus cells under hypoxia",
        abstract="Abstract goes here.",
        journal="Spine",
        publication_date=date(2024, 5, 1),
        entrez_date=date(2024, 5, 2),
        publication_types=["Journal Article"],
        mesh_terms=["Intervertebral Disc"],
        authors=[{"last": "Doe", "first": "Jane"}],
    )


@pytest.fixture
def nfkb_network(db) -> Network:
    return Network.objects.create(
        code="nfkb_axis", category="I", title="NF-κB Axis",
        keywords=["NF-kB", "RELA"], root_entity_aliases=["NFKB1", "RELA"],
    )
```

- [ ] **Step 2: Write failing tests in `apps/corpus/tests/test_models.py`**

```python
"""Tests for corpus.models."""
from __future__ import annotations

from datetime import date

import pytest
from django.db import IntegrityError

from corpus.models import IngestRun, Paper, PaperRelevance


def test_paper_uses_pmid_as_primary_key(db, paper_minimal):
    assert paper_minimal.pk == 38000123
    assert paper_minimal.pmid == 38000123


def test_paper_pmid_is_unique(db, paper_minimal):
    with pytest.raises(IntegrityError):
        Paper.objects.create(pmid=38000123, title="dup")


def test_paper_default_ingest_status_pending(db, paper_minimal):
    assert paper_minimal.ingest_status == "pending"


def test_paper_ingest_status_transitions(db, paper_minimal):
    for status in [
        "ingested", "classified", "fetched", "chunked", "done", "failed",
    ]:
        paper_minimal.ingest_status = status
        paper_minimal.save()
        paper_minimal.refresh_from_db()
        assert paper_minimal.ingest_status == status


def test_paper_full_text_status_default_none(db, paper_minimal):
    assert paper_minimal.full_text_status == "none"


def test_paper_full_text_status_choices(db, paper_minimal):
    for status in ["none", "abstract_only", "pmc_jats", "grobid_tei", "fetch_failed"]:
        paper_minimal.full_text_status = status
        paper_minimal.save()


def test_paper_is_original_nullable(db, paper_minimal):
    assert paper_minimal.is_original is None
    paper_minimal.is_original = True
    paper_minimal.save()
    paper_minimal.refresh_from_db()
    assert paper_minimal.is_original is True


def test_paper_jsonb_fields(db):
    p = Paper.objects.create(
        pmid=1,
        title="t",
        authors=[{"last": "A"}, {"last": "B"}],
        mesh_terms=["X", "Y"],
        publication_types=["Review"],
    )
    p.refresh_from_db()
    assert len(p.authors) == 2
    assert "X" in p.mesh_terms


def test_paper_doi_indexed(db, paper_minimal):
    paper_minimal.doi = "10.1234/abc"
    paper_minimal.save()
    found = Paper.objects.filter(doi="10.1234/abc").first()
    assert found == paper_minimal


def test_paper_heartbeat_field(db, paper_minimal):
    assert paper_minimal.ingest_heartbeat is None


def test_paper_attempts_default_zero(db, paper_minimal):
    assert paper_minimal.ingest_attempts == 0


def test_paper_pmcid_optional(db):
    p = Paper.objects.create(pmid=2, title="t", pmcid="PMC1234567")
    p.refresh_from_db()
    assert p.pmcid == "PMC1234567"


def test_paper_fulltext_s3_key_stored(db, paper_minimal):
    paper_minimal.fulltext_s3_key = "papers/3800/38000123.xml"
    paper_minimal.save()
    paper_minimal.refresh_from_db()
    assert paper_minimal.fulltext_s3_key.startswith("papers/")


def test_paper_relevance_round_trip(db, paper_minimal, nfkb_network):
    pr = PaperRelevance.objects.create(
        paper=paper_minimal,
        network=nfkb_network,
        score=0.85,
        classified_by="llm:qwen3:8b",
    )
    assert pr.pk is not None


def test_paper_relevance_unique_per_paper_network(db, paper_minimal, nfkb_network):
    PaperRelevance.objects.create(
        paper=paper_minimal, network=nfkb_network, score=0.5
    )
    with pytest.raises(IntegrityError):
        PaperRelevance.objects.create(
            paper=paper_minimal, network=nfkb_network, score=0.9
        )


def test_ingest_run_round_trip(db):
    run = IngestRun.objects.create(
        source="pubmed",
        query="dummy",
        n_pmids_seen=5,
        n_papers_created=3,
        n_papers_updated=2,
    )
    assert run.pk is not None
    assert run.finished_at is None
```

- [ ] **Step 3: Run failing tests**

```bash
poetry run pytest apps/corpus/tests/test_models.py -v
```

Expected: ImportError on `corpus.models`.

- [ ] **Step 4: Implement `apps/corpus/models.py`**

```python
"""corpus models — Paper, PaperRelevance, IngestRun.

Paper.pmid is the primary key (per spec §3). All ingest pipeline state
lives on Paper rows so resumability is automatic.
"""
from __future__ import annotations

from django.db import models

from core.models import TimestampedModel
from networks.models import Network


class Paper(TimestampedModel):
    INGEST_STATUS_CHOICES = [
        ("pending", "pending"),
        ("running", "running"),
        ("ingested", "ingested"),
        ("classified", "classified"),
        ("fetched", "fetched"),
        ("chunked", "chunked"),
        ("done", "done"),
        ("failed", "failed"),
        ("ingest_failed", "ingest_failed"),
    ]
    FULL_TEXT_STATUS_CHOICES = [
        ("none", "none"),
        ("abstract_only", "abstract_only"),
        ("pmc_jats", "pmc_jats"),
        ("grobid_tei", "grobid_tei"),
        ("fetch_failed", "fetch_failed"),
    ]

    pmid = models.BigIntegerField(primary_key=True)
    doi = models.CharField(max_length=128, blank=True, default="", db_index=True)
    pmcid = models.CharField(max_length=32, blank=True, default="", db_index=True)
    title = models.TextField()
    abstract = models.TextField(blank=True, default="")
    authors = models.JSONField(default=list, blank=True)
    journal = models.CharField(max_length=256, blank=True, default="")
    publication_date = models.DateField(null=True, blank=True)
    entrez_date = models.DateField(null=True, blank=True, db_index=True)
    publication_types = models.JSONField(default=list, blank=True)
    mesh_terms = models.JSONField(default=list, blank=True)
    pubtator_entities = models.JSONField(default=list, blank=True)

    is_original = models.BooleanField(null=True, blank=True)
    classification_confidence = models.FloatField(null=True, blank=True)
    classification_reason = models.TextField(blank=True, default="")

    full_text_status = models.CharField(
        max_length=24, choices=FULL_TEXT_STATUS_CHOICES, default="none"
    )
    fulltext_s3_key = models.CharField(max_length=256, blank=True, default="")
    fulltext_fetch_error = models.TextField(blank=True, default="")

    ingest_status = models.CharField(
        max_length=24, choices=INGEST_STATUS_CHOICES, default="pending", db_index=True
    )
    ingest_attempts = models.PositiveIntegerField(default=0)
    ingest_heartbeat = models.DateTimeField(null=True, blank=True)
    ingest_error = models.TextField(blank=True, default="")

    class Meta:
        db_table = "corpus_paper"
        indexes = [
            models.Index(fields=["ingest_status", "entrez_date"]),
            models.Index(fields=["is_original"]),
            models.Index(fields=["full_text_status"]),
        ]

    def __str__(self) -> str:
        return f"Paper<pmid={self.pmid}>"


class PaperRelevance(TimestampedModel):
    """Many-to-many between Paper and Network with relevance metadata.

    (per spec §5: "Result: many-to-many PaperRelevance. The corpus for
    network X is SELECT paper FROM PaperRelevance WHERE network=X AND
    relevance > 0.5".)
    """

    CLASSIFIED_BY_CHOICES = [
        ("cheap_keyword", "cheap_keyword"),
        ("cheap_pubtator", "cheap_pubtator"),
        ("llm:qwen3:8b", "llm:qwen3:8b"),
    ]

    paper = models.ForeignKey(Paper, related_name="relevances", on_delete=models.CASCADE)
    network = models.ForeignKey(Network, related_name="paper_relevances", on_delete=models.CASCADE)
    score = models.FloatField()
    classified_by = models.CharField(max_length=32, choices=CLASSIFIED_BY_CHOICES, default="cheap_keyword")
    reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "corpus_paperrelevance"
        constraints = [
            models.UniqueConstraint(
                fields=["paper", "network"], name="uniq_paper_network_relevance"
            )
        ]
        indexes = [
            models.Index(fields=["network", "score"]),
        ]


class IngestRun(TimestampedModel):
    """One row per refresh-cycle. Audits how many papers came in per source."""

    SOURCE_CHOICES = [
        ("pubmed", "pubmed"),
        ("pubmed_full", "pubmed_full"),
        ("elink", "elink"),
        ("europe_pmc", "europe_pmc"),
    ]

    source = models.CharField(max_length=24, choices=SOURCE_CHOICES)
    query = models.TextField(blank=True, default="")
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    n_pmids_seen = models.PositiveIntegerField(default=0)
    n_papers_created = models.PositiveIntegerField(default=0)
    n_papers_updated = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True, default="")

    class Meta:
        db_table = "corpus_ingestrun"
        indexes = [models.Index(fields=["source", "-started_at"])]
```

- [ ] **Step 5: Generate the migration**

```bash
poetry run python manage.py makemigrations corpus
```

Expected:
```
Migrations for 'corpus':
  apps/corpus/migrations/0001_initial.py
    + Create model Paper
    + Create model IngestRun
    + Create model PaperRelevance
```

- [ ] **Step 6: Run tests**

```bash
poetry run pytest apps/corpus/tests/test_models.py -v
```

Expected:
```
17 passed
```

- [ ] **Step 7: Commit**

```bash
git add apps/corpus/models.py apps/corpus/migrations/ apps/corpus/tests/
git commit -m "feat(corpus): add Paper, PaperRelevance, IngestRun models"
```

---

## Task 15: PubMed master query builder (TDD)

(per spec §5, the exact MeSH-anchored + free-text query string.)

**Files:**
- Create: `apps/corpus/tests/test_pubmed_query.py`
- Create: `apps/corpus/pubmed_query.py`

- [ ] **Step 1: Write failing tests in `apps/corpus/tests/test_pubmed_query.py`**

```python
"""Tests for the canonical IDD PubMed query."""
from __future__ import annotations

from datetime import date

from corpus.pubmed_query import (
    MASTER_IDD_QUERY,
    build_incremental_query,
)


def test_master_query_includes_mesh_terms():
    assert '"Intervertebral Disc"[MeSH]' in MASTER_IDD_QUERY
    assert '"Intervertebral Disc Degeneration"[MeSH]' in MASTER_IDD_QUERY
    assert '"Intervertebral Disc Displacement"[MeSH]' in MASTER_IDD_QUERY
    assert '"Nucleus Pulposus"[MeSH]' in MASTER_IDD_QUERY


def test_master_query_includes_tiab_terms():
    assert '"intervertebral disc"[TIAB]' in MASTER_IDD_QUERY
    assert '"intervertebral disk"[TIAB]' in MASTER_IDD_QUERY
    assert '"nucleus pulposus"[TIAB]' in MASTER_IDD_QUERY
    assert '"annulus fibrosus"[TIAB]' in MASTER_IDD_QUERY
    assert '"disc degeneration"[TIAB]' in MASTER_IDD_QUERY
    assert '"disc herniation"[TIAB]' in MASTER_IDD_QUERY
    assert '"cartilage endplate"[TIAB]' in MASTER_IDD_QUERY
    assert '"spinal disc"[TIAB]' in MASTER_IDD_QUERY


def test_master_query_language_and_date_filters():
    assert "English[Language]" in MASTER_IDD_QUERY
    assert '("1980"[PDAT] : "3000"[PDAT])' in MASTER_IDD_QUERY


def test_build_incremental_query_includes_mindate():
    q = build_incremental_query(since=date(2024, 5, 1))
    assert "2024/05/01" in q
    assert "EDAT" in q


def test_build_incremental_query_uses_overlap_window():
    q = build_incremental_query(since=date(2024, 5, 8), overlap_days=7)
    # 8th minus 7 days = 1st
    assert "2024/05/01" in q


def test_build_incremental_query_none_since_returns_master():
    q = build_incremental_query(since=None)
    assert q == MASTER_IDD_QUERY
```

- [ ] **Step 2: Run failing tests**

```bash
poetry run pytest apps/corpus/tests/test_pubmed_query.py -v
```

Expected: ImportError on `corpus.pubmed_query`.

- [ ] **Step 3: Implement `apps/corpus/pubmed_query.py`**

```python
"""The canonical IDD PubMed query string.

(per spec §5 — hybrid MeSH-anchored + free-text, weighted by date.
~30,000–40,000 historical hits, ~3,000–5,000 new papers/year.)
"""
from __future__ import annotations

from datetime import date, timedelta

MASTER_IDD_QUERY = (
    "("
    '"Intervertebral Disc"[MeSH] OR '
    '"Intervertebral Disc Degeneration"[MeSH] OR '
    '"Intervertebral Disc Displacement"[MeSH] OR '
    '"Nucleus Pulposus"[MeSH] OR '
    '"intervertebral disc"[TIAB] OR '
    '"intervertebral disk"[TIAB] OR '
    '"nucleus pulposus"[TIAB] OR '
    '"annulus fibrosus"[TIAB] OR '
    '"disc degeneration"[TIAB] OR '
    '"disc herniation"[TIAB] OR '
    '"cartilage endplate"[TIAB] OR '
    '"spinal disc"[TIAB]'
    ") "
    "AND English[Language] "
    'AND ("1980"[PDAT] : "3000"[PDAT])'
)


def build_incremental_query(
    *, since: date | None, overlap_days: int = 7
) -> str:
    """Build a date-bounded variant for incremental refresh.

    ``since`` is the watermark's ``last_entrez_date``. The query subtracts
    ``overlap_days`` to catch late-indexed papers (per spec §5 watermark
    section: "7-day overlap to catch late-indexed papers").
    """
    if since is None:
        return MASTER_IDD_QUERY
    mindate = since - timedelta(days=overlap_days)
    mindate_str = mindate.strftime("%Y/%m/%d")
    return f'{MASTER_IDD_QUERY} AND ("{mindate_str}"[EDAT] : "3000"[EDAT])'
```

- [ ] **Step 4: Run tests**

```bash
poetry run pytest apps/corpus/tests/test_pubmed_query.py -v
```

Expected:
```
6 passed
```

- [ ] **Step 5: Commit**

```bash
git add apps/corpus/pubmed_query.py apps/corpus/tests/test_pubmed_query.py
git commit -m "feat(corpus): add canonical IDD PubMed master query + incremental builder"
```

---

## Task 16: NCBI E-utilities client — ESearch + EFetch + ELink (TDD)

(per spec §5 discovery sources table.)

**Files:**
- Create: `apps/corpus/tests/fixtures/esearch_response.xml`
- Create: `apps/corpus/tests/fixtures/efetch_response.xml`
- Create: `apps/corpus/tests/fixtures/elink_response.xml`
- Create: `apps/corpus/tests/test_ncbi_client.py`
- Create: `apps/corpus/clients/ncbi.py`

- [ ] **Step 1: Create `apps/corpus/tests/fixtures/esearch_response.xml`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<eSearchResult>
  <Count>3</Count>
  <RetMax>3</RetMax>
  <RetStart>0</RetStart>
  <WebEnv>NCID_1_abc</WebEnv>
  <QueryKey>1</QueryKey>
  <IdList>
    <Id>38000123</Id>
    <Id>38000124</Id>
    <Id>38000125</Id>
  </IdList>
</eSearchResult>
```

- [ ] **Step 2: Create `apps/corpus/tests/fixtures/efetch_response.xml`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <PMID Version="1">38000123</PMID>
      <Article>
        <Journal>
          <Title>Spine</Title>
        </Journal>
        <ArticleTitle>A study of NP cells under hypoxia.</ArticleTitle>
        <Abstract>
          <AbstractText>Hypoxic NP cells upregulate HIF1A.</AbstractText>
        </Abstract>
        <AuthorList>
          <Author>
            <LastName>Doe</LastName>
            <ForeName>Jane</ForeName>
          </Author>
        </AuthorList>
        <PublicationTypeList>
          <PublicationType UI="D016428">Journal Article</PublicationType>
        </PublicationTypeList>
        <ArticleDate DateType="Electronic">
          <Year>2024</Year>
          <Month>05</Month>
          <Day>01</Day>
        </ArticleDate>
        <ELocationID EIdType="doi">10.1234/spine.2024.123</ELocationID>
      </Article>
      <MeshHeadingList>
        <MeshHeading>
          <DescriptorName UI="D007690">Intervertebral Disc</DescriptorName>
        </MeshHeading>
      </MeshHeadingList>
      <DateRevised>
        <Year>2024</Year><Month>05</Month><Day>02</Day>
      </DateRevised>
    </MedlineCitation>
    <PubmedData>
      <History>
        <PubMedPubDate PubStatus="entrez">
          <Year>2024</Year><Month>05</Month><Day>02</Day>
        </PubMedPubDate>
      </History>
      <ArticleIdList>
        <ArticleId IdType="pmc">PMC11000000</ArticleId>
      </ArticleIdList>
    </PubmedData>
  </PubmedArticle>
</PubmedArticleSet>
```

- [ ] **Step 3: Create `apps/corpus/tests/fixtures/elink_response.xml`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<eLinkResult>
  <LinkSet>
    <DbFrom>pubmed</DbFrom>
    <IdList><Id>38000123</Id></IdList>
    <LinkSetDb>
      <DbTo>pubmed</DbTo>
      <LinkName>pubmed_pubmed_refs</LinkName>
      <Link><Id>30000001</Id></Link>
      <Link><Id>30000002</Id></Link>
      <Link><Id>30000003</Id></Link>
    </LinkSetDb>
  </LinkSet>
</eLinkResult>
```

- [ ] **Step 4: Write failing tests in `apps/corpus/tests/test_ncbi_client.py`**

```python
"""Tests for corpus.clients.ncbi.NcbiClient."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from corpus.clients.ncbi import NcbiClient, PaperMetadata
from schedule.models import RateLimitBucket

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _ncbi_bucket(db):
    RateLimitBucket.objects.create(
        provider="ncbi_eutils", capacity=10, refill_per_sec=10.0, current_tokens=10.0
    )


@pytest.fixture
def client(settings):
    settings.NCBI_API_KEY = "test-key"
    settings.NCBI_CONTACT_EMAIL = "test@example.com"
    return NcbiClient()


def test_esearch_parses_pmids(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url__startswith="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        content=(FIXTURE_DIR / "esearch_response.xml").read_bytes(),
    )
    pmids = client.esearch(query="test", retmax=10)
    assert pmids == [38000123, 38000124, 38000125]


def test_esearch_includes_api_key_and_tool(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url__startswith="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        content=(FIXTURE_DIR / "esearch_response.xml").read_bytes(),
    )
    client.esearch(query="test")
    req = httpx_mock.get_requests()[0]
    assert "api_key=test-key" in str(req.url)
    assert "tool=" in str(req.url)
    assert "email=" in str(req.url)


def test_esearch_consumes_rate_limit_token(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url__startswith="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        content=(FIXTURE_DIR / "esearch_response.xml").read_bytes(),
    )
    before = RateLimitBucket.objects.get(provider="ncbi_eutils").current_tokens
    client.esearch(query="test")
    after = RateLimitBucket.objects.get(provider="ncbi_eutils").current_tokens
    assert after < before


def test_efetch_parses_paper_metadata(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url__startswith="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
        content=(FIXTURE_DIR / "efetch_response.xml").read_bytes(),
    )
    papers = client.efetch(pmids=[38000123])
    assert len(papers) == 1
    p: PaperMetadata = papers[0]
    assert p.pmid == 38000123
    assert "hypoxia" in p.title.lower()
    assert p.doi == "10.1234/spine.2024.123"
    assert p.pmcid == "PMC11000000"
    assert p.journal == "Spine"
    assert p.publication_date == date(2024, 5, 1)
    assert p.entrez_date == date(2024, 5, 2)
    assert "Intervertebral Disc" in p.mesh_terms
    assert "Journal Article" in p.publication_types
    assert p.authors[0]["last"] == "Doe"


def test_elink_returns_referenced_pmids(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url__startswith="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi",
        content=(FIXTURE_DIR / "elink_response.xml").read_bytes(),
    )
    refs = client.elink_refs(pmid=38000123)
    assert refs == [30000001, 30000002, 30000003]


def test_esearch_paginates_via_retstart(client, httpx_mock: HTTPXMock):
    # The fixture has count=3, retmax=3; an explicit retstart should appear
    httpx_mock.add_response(
        method="GET",
        url__startswith="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        content=(FIXTURE_DIR / "esearch_response.xml").read_bytes(),
    )
    client.esearch(query="test", retstart=200, retmax=100)
    req = httpx_mock.get_requests()[0]
    assert "retstart=200" in str(req.url)
    assert "retmax=100" in str(req.url)
```

- [ ] **Step 5: Run failing tests**

```bash
poetry run pytest apps/corpus/tests/test_ncbi_client.py -v
```

Expected: ImportError on `corpus.clients.ncbi`.

- [ ] **Step 6: Implement `apps/corpus/clients/ncbi.py`**

```python
"""NCBI E-utilities client: ESearch, EFetch, ELink.

Spec §5 calls out these three endpoints as the primary discovery + metadata
+ citation-traversal mechanism. All calls are gated by the `ncbi_eutils`
rate-limit bucket (10 req/s with API key).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import httpx
from django.conf import settings
from lxml import etree

from schedule.ratelimit import require_token

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
ELINK_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/elink.fcgi"


@dataclass
class PaperMetadata:
    pmid: int
    title: str
    abstract: str = ""
    journal: str = ""
    doi: str = ""
    pmcid: str = ""
    publication_date: date | None = None
    entrez_date: date | None = None
    publication_types: list[str] = field(default_factory=list)
    mesh_terms: list[str] = field(default_factory=list)
    authors: list[dict[str, str]] = field(default_factory=list)


class NcbiClient:
    """Wraps the three E-utilities endpoints we care about."""

    def __init__(self, *, timeout: float = 30.0) -> None:
        self._client = httpx.Client(timeout=timeout)
        self._base_params = {
            "tool": settings.NCBI_TOOL_NAME,
            "email": settings.NCBI_CONTACT_EMAIL,
        }
        if settings.NCBI_API_KEY:
            self._base_params["api_key"] = settings.NCBI_API_KEY

    @require_token("ncbi_eutils", cost=1)
    def esearch(
        self,
        *,
        query: str,
        retmax: int = 1000,
        retstart: int = 0,
        db: str = "pubmed",
    ) -> list[int]:
        params: dict[str, Any] = {
            **self._base_params,
            "db": db,
            "term": query,
            "retmax": retmax,
            "retstart": retstart,
            "usehistory": "n",
        }
        resp = self._client.get(ESEARCH_URL, params=params)
        resp.raise_for_status()
        tree = etree.fromstring(resp.content)
        return [int(id_el.text) for id_el in tree.findall(".//IdList/Id")]

    @require_token("ncbi_eutils", cost=1)
    def efetch(self, *, pmids: list[int], db: str = "pubmed") -> list[PaperMetadata]:
        if not pmids:
            return []
        params = {
            **self._base_params,
            "db": db,
            "id": ",".join(str(p) for p in pmids),
            "retmode": "xml",
            "rettype": "abstract",
        }
        resp = self._client.get(EFETCH_URL, params=params)
        resp.raise_for_status()
        tree = etree.fromstring(resp.content)
        return [self._parse_article(art) for art in tree.findall(".//PubmedArticle")]

    @require_token("ncbi_eutils", cost=1)
    def elink_refs(self, *, pmid: int) -> list[int]:
        """Reference list (cited papers) via linkname=pubmed_pubmed_refs."""
        params = {
            **self._base_params,
            "dbfrom": "pubmed",
            "db": "pubmed",
            "linkname": "pubmed_pubmed_refs",
            "id": str(pmid),
        }
        resp = self._client.get(ELINK_URL, params=params)
        resp.raise_for_status()
        tree = etree.fromstring(resp.content)
        return [int(el.text) for el in tree.findall(".//LinkSetDb/Link/Id")]

    @staticmethod
    def _parse_article(art: etree._Element) -> PaperMetadata:
        pmid = int(art.findtext(".//MedlineCitation/PMID"))
        title = (art.findtext(".//Article/ArticleTitle") or "").strip()
        abstract = " ".join(
            (el.text or "") for el in art.findall(".//Article/Abstract/AbstractText")
        ).strip()
        journal = (art.findtext(".//Article/Journal/Title") or "").strip()
        doi = ""
        pmcid = ""
        for el in art.findall(".//Article/ELocationID"):
            if el.get("EIdType") == "doi":
                doi = (el.text or "").strip()
        for el in art.findall(".//PubmedData/ArticleIdList/ArticleId"):
            if el.get("IdType") == "pmc":
                pmcid = (el.text or "").strip()
        pub_date = _parse_article_date(art)
        entrez_date = _parse_entrez_date(art)
        pub_types = [
            (el.text or "").strip()
            for el in art.findall(".//PublicationTypeList/PublicationType")
        ]
        mesh = [
            (el.text or "").strip()
            for el in art.findall(".//MeshHeadingList/MeshHeading/DescriptorName")
        ]
        authors = []
        for au in art.findall(".//AuthorList/Author"):
            authors.append({
                "last": (au.findtext("LastName") or "").strip(),
                "first": (au.findtext("ForeName") or "").strip(),
            })
        return PaperMetadata(
            pmid=pmid,
            title=title,
            abstract=abstract,
            journal=journal,
            doi=doi,
            pmcid=pmcid,
            publication_date=pub_date,
            entrez_date=entrez_date,
            publication_types=pub_types,
            mesh_terms=mesh,
            authors=authors,
        )


def _parse_article_date(art: etree._Element) -> date | None:
    el = art.find(".//Article/ArticleDate")
    if el is None:
        return None
    try:
        return date(
            int(el.findtext("Year") or 0),
            int(el.findtext("Month") or 0),
            int(el.findtext("Day") or 0),
        )
    except (TypeError, ValueError):
        return None


def _parse_entrez_date(art: etree._Element) -> date | None:
    el = art.find(".//PubmedData/History/PubMedPubDate[@PubStatus='entrez']")
    if el is None:
        return None
    try:
        return date(
            int(el.findtext("Year") or 0),
            int(el.findtext("Month") or 0),
            int(el.findtext("Day") or 0),
        )
    except (TypeError, ValueError):
        return None
```

- [ ] **Step 7: Run tests**

```bash
poetry run pytest apps/corpus/tests/test_ncbi_client.py -v
```

Expected:
```
6 passed
```

- [ ] **Step 8: Commit**

```bash
git add apps/corpus/clients/ncbi.py apps/corpus/tests/fixtures/ apps/corpus/tests/test_ncbi_client.py
git commit -m "feat(corpus): add NCBI E-utilities client (ESearch, EFetch, ELink)"
```

---

## Task 17: Europe PMC OAI-PMH full-text client (TDD)

**Files:**
- Create: `apps/corpus/tests/fixtures/europepmc_jats.xml`
- Create: `apps/corpus/tests/test_europepmc_client.py`
- Create: `apps/corpus/clients/europepmc.py`

- [ ] **Step 1: Create `apps/corpus/tests/fixtures/europepmc_jats.xml`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
  <GetRecord>
    <record>
      <header>
        <identifier>oai:europepmc.org:PMC11000000</identifier>
      </header>
      <metadata>
        <article xmlns="http://jats.nlm.nih.gov/ns/archiving/1.3/">
          <front>
            <article-meta>
              <article-id pub-id-type="pmc">11000000</article-id>
              <article-id pub-id-type="pmid">38000123</article-id>
              <title-group>
                <article-title>A study of NP cells under hypoxia.</article-title>
              </title-group>
            </article-meta>
          </front>
          <body>
            <sec sec-type="intro">
              <title>Introduction</title>
              <p>Intervertebral disc degeneration is common.</p>
            </sec>
            <sec sec-type="results">
              <title>Results</title>
              <p>Hypoxia upregulated HIF1A expression 5-fold (p&lt;0.001).</p>
              <p>NF-κB signalling was suppressed under low oxygen.</p>
            </sec>
            <sec sec-type="conclusions">
              <title>Conclusions</title>
              <p>HIF1A is central to NP cell survival.</p>
            </sec>
          </body>
        </article>
      </metadata>
    </record>
  </GetRecord>
</OAI-PMH>
```

- [ ] **Step 2: Write failing tests in `apps/corpus/tests/test_europepmc_client.py`**

```python
"""Tests for corpus.clients.europepmc.EuropePmcClient."""
from __future__ import annotations

from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from corpus.clients.europepmc import EuropePmcClient, EuropePmcNotFound
from schedule.models import RateLimitBucket

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _bucket(db):
    RateLimitBucket.objects.create(
        provider="europe_pmc_oai", capacity=10, refill_per_sec=5.0, current_tokens=10.0
    )


@pytest.fixture
def client():
    return EuropePmcClient()


def test_get_jats_returns_xml(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url__startswith="https://europepmc.org/oai.cgi",
        content=(FIXTURE_DIR / "europepmc_jats.xml").read_bytes(),
    )
    xml = client.get_jats_for_pmcid("PMC11000000")
    assert b"<article" in xml or b"article xmlns" in xml


def test_get_jats_not_found(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url__startswith="https://europepmc.org/oai.cgi",
        content=b"<OAI-PMH><error code='idDoesNotExist'>x</error></OAI-PMH>",
    )
    with pytest.raises(EuropePmcNotFound):
        client.get_jats_for_pmcid("PMC99999999")


def test_get_jats_consumes_rate_limit_token(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url__startswith="https://europepmc.org/oai.cgi",
        content=(FIXTURE_DIR / "europepmc_jats.xml").read_bytes(),
    )
    before = RateLimitBucket.objects.get(provider="europe_pmc_oai").current_tokens
    client.get_jats_for_pmcid("PMC11000000")
    after = RateLimitBucket.objects.get(provider="europe_pmc_oai").current_tokens
    assert after < before


def test_get_jats_includes_correct_oai_verb(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url__startswith="https://europepmc.org/oai.cgi",
        content=(FIXTURE_DIR / "europepmc_jats.xml").read_bytes(),
    )
    client.get_jats_for_pmcid("PMC11000000")
    req = httpx_mock.get_requests()[0]
    assert "verb=GetRecord" in str(req.url)
    assert "metadataPrefix=pmc" in str(req.url)
    assert "oai%3Aeuropepmc.org%3APMC11000000" in str(req.url) or \
           "oai:europepmc.org:PMC11000000" in str(req.url)
```

- [ ] **Step 3: Run failing tests**

```bash
poetry run pytest apps/corpus/tests/test_europepmc_client.py -v
```

Expected: ImportError on `corpus.clients.europepmc`.

- [ ] **Step 4: Implement `apps/corpus/clients/europepmc.py`**

```python
"""Europe PMC OAI-PMH full-text client.

Returns the raw JATS XML bytes for a PMCID. The caller (papers.jats)
parses the structure; this layer only does HTTP + error mapping.

(per spec §5: "Europe PMC OAI-PMH | Full-text JATS XML for PMC
open-access papers")
"""
from __future__ import annotations

import httpx
from django.conf import settings

from schedule.ratelimit import require_token


class EuropePmcNotFound(Exception):
    """Raised when the PMCID isn't in Europe PMC's open-access set."""


class EuropePmcClient:
    def __init__(self, *, timeout: float = 60.0) -> None:
        self._client = httpx.Client(timeout=timeout)
        self._oai_url = settings.EUROPE_PMC_OAI_URL

    @require_token("europe_pmc_oai", cost=1)
    def get_jats_for_pmcid(self, pmcid: str) -> bytes:
        """GET the JATS XML for a PMC open-access paper."""
        identifier = f"oai:europepmc.org:{pmcid}"
        params = {
            "verb": "GetRecord",
            "identifier": identifier,
            "metadataPrefix": "pmc",
        }
        resp = self._client.get(self._oai_url, params=params)
        resp.raise_for_status()
        content = resp.content
        if b"idDoesNotExist" in content or b"cannotDisseminateFormat" in content:
            raise EuropePmcNotFound(pmcid)
        return content
```

- [ ] **Step 5: Run tests**

```bash
poetry run pytest apps/corpus/tests/test_europepmc_client.py -v
```

Expected:
```
4 passed
```

- [ ] **Step 6: Commit**

```bash
git add apps/corpus/clients/europepmc.py apps/corpus/tests/fixtures/europepmc_jats.xml apps/corpus/tests/test_europepmc_client.py
git commit -m "feat(corpus): add Europe PMC OAI-PMH JATS client"
```

---

## Task 18: PubTator3 REST client (TDD)

**Files:**
- Create: `apps/corpus/tests/fixtures/pubtator_response.json`
- Create: `apps/corpus/tests/test_pubtator_client.py`
- Create: `apps/corpus/clients/pubtator.py`

- [ ] **Step 1: Create `apps/corpus/tests/fixtures/pubtator_response.json`**

```json
{
  "PubTator3": [
    {
      "pmid": 38000123,
      "passages": [
        {
          "infons": {"type": "title"},
          "text": "A study of NP cells under hypoxia.",
          "annotations": [
            {
              "text": "HIF1A",
              "infons": {"type": "Gene", "identifier": "3091", "database": "NCBI Gene"},
              "locations": [{"offset": 32, "length": 5}]
            }
          ]
        },
        {
          "infons": {"type": "abstract"},
          "text": "Hypoxic NP cells upregulate HIF1A and downregulate NFKB1.",
          "annotations": [
            {
              "text": "HIF1A",
              "infons": {"type": "Gene", "identifier": "3091"},
              "locations": [{"offset": 28, "length": 5}]
            },
            {
              "text": "NFKB1",
              "infons": {"type": "Gene", "identifier": "4790"},
              "locations": [{"offset": 51, "length": 5}]
            }
          ]
        }
      ]
    }
  ]
}
```

- [ ] **Step 2: Write failing tests in `apps/corpus/tests/test_pubtator_client.py`**

```python
"""Tests for corpus.clients.pubtator.PubtatorClient."""
from __future__ import annotations

from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from corpus.clients.pubtator import PubtatorClient
from schedule.models import RateLimitBucket

FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _bucket(db):
    RateLimitBucket.objects.create(
        provider="pubtator3", capacity=10, refill_per_sec=10.0, current_tokens=10.0
    )


@pytest.fixture
def client():
    return PubtatorClient()


def test_get_annotations_returns_entity_list(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url__startswith="https://www.ncbi.nlm.nih.gov/research/pubtator3-api",
        text=(FIXTURE_DIR / "pubtator_response.json").read_text(),
    )
    entities = client.get_annotations(pmid=38000123)
    assert len(entities) == 3
    types = {e["type"] for e in entities}
    assert "Gene" in types
    texts = {e["text"] for e in entities}
    assert "HIF1A" in texts
    assert "NFKB1" in texts


def test_get_annotations_uses_correct_url(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url__startswith="https://www.ncbi.nlm.nih.gov/research/pubtator3-api",
        text=(FIXTURE_DIR / "pubtator_response.json").read_text(),
    )
    client.get_annotations(pmid=38000123)
    req = httpx_mock.get_requests()[0]
    assert "38000123" in str(req.url)


def test_get_annotations_consumes_token(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url__startswith="https://www.ncbi.nlm.nih.gov/research/pubtator3-api",
        text=(FIXTURE_DIR / "pubtator_response.json").read_text(),
    )
    before = RateLimitBucket.objects.get(provider="pubtator3").current_tokens
    client.get_annotations(pmid=38000123)
    after = RateLimitBucket.objects.get(provider="pubtator3").current_tokens
    assert after < before


def test_get_annotations_empty_on_404(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url__startswith="https://www.ncbi.nlm.nih.gov/research/pubtator3-api",
        status_code=404,
        text="not found",
    )
    entities = client.get_annotations(pmid=99999999)
    assert entities == []
```

- [ ] **Step 3: Run failing tests**

```bash
poetry run pytest apps/corpus/tests/test_pubtator_client.py -v
```

Expected: ImportError on `corpus.clients.pubtator`.

- [ ] **Step 4: Implement `apps/corpus/clients/pubtator.py`**

```python
"""PubTator3 REST client.

Pulls pre-annotated entities (genes, chemicals, diseases, mutations) for
a PMID. We store the flattened entity list on Paper.pubtator_entities;
spec §5 calls this the "cached entity annotations" stage.
"""
from __future__ import annotations

import httpx
from django.conf import settings

from schedule.ratelimit import require_token


class PubtatorClient:
    def __init__(self, *, timeout: float = 30.0) -> None:
        self._client = httpx.Client(timeout=timeout)
        self._base = settings.PUBTATOR3_BASE_URL.rstrip("/")

    @require_token("pubtator3", cost=1)
    def get_annotations(self, *, pmid: int) -> list[dict]:
        """Return a flat list of annotation dicts (one per entity mention)."""
        url = f"{self._base}/publications/export/biocjson"
        params = {"pmids": str(pmid)}
        resp = self._client.get(url, params=params)
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        try:
            payload = resp.json()
        except Exception:
            return []
        entities: list[dict] = []
        for doc in payload.get("PubTator3", []):
            for passage in doc.get("passages", []):
                for ann in passage.get("annotations", []):
                    infons = ann.get("infons", {})
                    entities.append({
                        "text": ann.get("text", ""),
                        "type": infons.get("type", ""),
                        "identifier": infons.get("identifier", ""),
                        "database": infons.get("database", ""),
                    })
        return entities
```

- [ ] **Step 5: Run tests**

```bash
poetry run pytest apps/corpus/tests/test_pubtator_client.py -v
```

Expected:
```
4 passed
```

- [ ] **Step 6: Commit**

```bash
git add apps/corpus/clients/pubtator.py apps/corpus/tests/fixtures/pubtator_response.json apps/corpus/tests/test_pubtator_client.py
git commit -m "feat(corpus): add PubTator3 REST client"
```

---

## Task 19: `papers` models — Section, Chunk, PaperClassification (TDD)

(per spec §3, indexed on `(paper_id, section_doco_type)` so extractors can filter `WHERE doco_type='Results'`.)

**Files:**
- Create: `apps/papers/tests/conftest.py`
- Create: `apps/papers/tests/test_models.py`
- Modify: `apps/papers/models.py`

- [ ] **Step 1: Create `apps/papers/tests/conftest.py`**

```python
"""Shared pytest fixtures for the papers app."""
from __future__ import annotations

from datetime import date

import pytest

from corpus.models import Paper


@pytest.fixture
def paper(db) -> Paper:
    return Paper.objects.create(
        pmid=38000123,
        title="A study of NP cells under hypoxia",
        publication_date=date(2024, 5, 1),
    )
```

- [ ] **Step 2: Write failing tests in `apps/papers/tests/test_models.py`**

```python
"""Tests for papers.models."""
from __future__ import annotations

import pytest
from django.db import IntegrityError

from papers.models import Chunk, PaperClassification, Section


def test_section_round_trip(db, paper):
    s = Section.objects.create(
        paper=paper,
        order_index=2,
        doco_type="Results",
        doco_iri="http://purl.org/spar/doco/Results",
        heading="Results",
        body_text="Hypoxia upregulated HIF1A.",
        token_count=12,
    )
    assert s.pk is not None


def test_section_ordered_by_index(db, paper):
    Section.objects.create(paper=paper, order_index=2, doco_type="Results", body_text="b")
    Section.objects.create(paper=paper, order_index=1, doco_type="Introduction", body_text="a")
    Section.objects.create(paper=paper, order_index=3, doco_type="Conclusions", body_text="c")
    ordered = list(paper.sections.all())
    assert [s.order_index for s in ordered] == [1, 2, 3]


def test_section_paper_index_unique(db, paper):
    Section.objects.create(paper=paper, order_index=1, doco_type="Results", body_text="a")
    with pytest.raises(IntegrityError):
        Section.objects.create(paper=paper, order_index=1, doco_type="Methods", body_text="b")


def test_chunk_round_trip(db, paper):
    s = Section.objects.create(paper=paper, order_index=1, doco_type="Results", body_text="abc")
    c = Chunk.objects.create(
        section=s,
        chunk_index=0,
        text="Hypoxia upregulated HIF1A.",
        token_count=8,
        char_offset_start=0,
        char_offset_end=27,
    )
    assert c.pk is not None
    assert c.paper_id == paper.pmid  # denormalised FK for fast filters


def test_chunk_paper_chunk_index_unique(db, paper):
    s = Section.objects.create(paper=paper, order_index=1, doco_type="Results", body_text="x")
    Chunk.objects.create(
        section=s, chunk_index=0, text="a", token_count=1, char_offset_start=0, char_offset_end=1
    )
    with pytest.raises(IntegrityError):
        Chunk.objects.create(
            section=s, chunk_index=0, text="b", token_count=1, char_offset_start=0, char_offset_end=1
        )


def test_chunk_processed_by_models_default_empty(db, paper):
    s = Section.objects.create(paper=paper, order_index=1, doco_type="Results", body_text="x")
    c = Chunk.objects.create(
        section=s, chunk_index=0, text="x", token_count=1, char_offset_start=0, char_offset_end=1
    )
    assert c.processed_by_models == []


def test_paper_classification_round_trip(db, paper):
    pc = PaperClassification.objects.create(
        paper=paper,
        is_original=True,
        confidence=0.92,
        classifier="rule:pubtype",
        reason="No 'Review' in publication_types",
    )
    assert pc.pk is not None


def test_paper_classification_one_per_paper(db, paper):
    PaperClassification.objects.create(
        paper=paper, is_original=True, confidence=0.9, classifier="rule:pubtype"
    )
    with pytest.raises(IntegrityError):
        PaperClassification.objects.create(
            paper=paper, is_original=False, confidence=0.9, classifier="llm:qwen3:8b"
        )
```

- [ ] **Step 3: Run failing tests**

```bash
poetry run pytest apps/papers/tests/test_models.py -v
```

Expected: ImportError on `papers.models`.

- [ ] **Step 4: Implement `apps/papers/models.py`**

```python
"""papers models — Section, Chunk, PaperClassification.

Section: one row per DoCO-tagged section of a paper.
Chunk: atomic LLM input. Denormalises `paper_id` so the extractor can
  filter without joining (spec §3: indexed on (paper_id, section_doco_type)).
PaperClassification: persisted output of the is_original classifier.
"""
from __future__ import annotations

from django.db import models

from core.models import TimestampedModel
from corpus.models import Paper


class Section(TimestampedModel):
    paper = models.ForeignKey(Paper, related_name="sections", on_delete=models.CASCADE)
    order_index = models.PositiveSmallIntegerField()
    doco_type = models.CharField(max_length=32, db_index=True)
    doco_iri = models.URLField(blank=True, default="")
    heading = models.CharField(max_length=512, blank=True, default="")
    body_text = models.TextField()
    token_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "papers_section"
        constraints = [
            models.UniqueConstraint(
                fields=["paper", "order_index"], name="uniq_paper_section_index"
            )
        ]
        ordering = ["paper", "order_index"]
        indexes = [models.Index(fields=["paper", "doco_type"])]


class Chunk(TimestampedModel):
    section = models.ForeignKey(Section, related_name="chunks", on_delete=models.CASCADE)
    paper = models.ForeignKey(
        Paper, related_name="chunks", on_delete=models.CASCADE, editable=False
    )
    chunk_index = models.PositiveSmallIntegerField()
    text = models.TextField()
    token_count = models.PositiveIntegerField()
    char_offset_start = models.PositiveIntegerField()
    char_offset_end = models.PositiveIntegerField()
    processed_by_models = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = "papers_chunk"
        constraints = [
            models.UniqueConstraint(
                fields=["section", "chunk_index"], name="uniq_section_chunk_index"
            )
        ]
        indexes = [
            models.Index(fields=["paper", "section"]),
        ]

    def save(self, *args, **kwargs) -> None:  # type: ignore[override]
        if self.section_id and not self.paper_id:
            self.paper_id = self.section.paper_id
        super().save(*args, **kwargs)


class PaperClassification(TimestampedModel):
    CLASSIFIER_CHOICES = [
        ("rule:pubtype", "rule:pubtype"),
        ("llm:qwen3:8b", "llm:qwen3:8b"),
    ]

    paper = models.OneToOneField(
        Paper, related_name="classification", on_delete=models.CASCADE
    )
    is_original = models.BooleanField()
    confidence = models.FloatField()
    classifier = models.CharField(max_length=32, choices=CLASSIFIER_CHOICES)
    reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "papers_paperclassification"
```

- [ ] **Step 5: Generate the migration**

```bash
poetry run python manage.py makemigrations papers
```

Expected:
```
Migrations for 'papers':
  apps/papers/migrations/0001_initial.py
    + Create model Section
    + Create model Chunk
    + Create model PaperClassification
```

- [ ] **Step 6: Run tests**

```bash
poetry run pytest apps/papers/tests/test_models.py -v
```

Expected:
```
8 passed
```

- [ ] **Step 7: Commit**

```bash
git add apps/papers/models.py apps/papers/migrations/ apps/papers/tests/
git commit -m "feat(papers): add Section, Chunk, PaperClassification models"
```

---

## Task 20: DoCO section-type mapping (TDD)

(per spec §4: "Parse XML → map section types to DoCO IRIs. Keep doco:Results sections (plus doco:Conclusions tagged as aux).")

**Files:**
- Create: `apps/papers/tests/test_doco.py`
- Create: `apps/papers/doco.py`

- [ ] **Step 1: Write failing tests in `apps/papers/tests/test_doco.py`**

```python
"""Tests for the DoCO section-type mapping."""
from __future__ import annotations

from papers.doco import (
    DOCO_IRI_PREFIX,
    map_jats_sec_type,
    map_section_heading,
)


def test_map_jats_results_to_doco_results():
    assert map_jats_sec_type("results") == ("Results", f"{DOCO_IRI_PREFIX}Results")


def test_map_jats_intro_to_doco_introduction():
    assert map_jats_sec_type("intro") == ("Introduction", f"{DOCO_IRI_PREFIX}Introduction")
    assert map_jats_sec_type("introduction") == ("Introduction", f"{DOCO_IRI_PREFIX}Introduction")


def test_map_jats_methods_to_doco_methods():
    assert map_jats_sec_type("methods") == ("Methods", f"{DOCO_IRI_PREFIX}Methods")
    assert map_jats_sec_type("materials|methods") == ("Methods", f"{DOCO_IRI_PREFIX}Methods")


def test_map_jats_discussion_to_doco_discussion():
    assert map_jats_sec_type("discussion") == ("Discussion", f"{DOCO_IRI_PREFIX}Discussion")


def test_map_jats_conclusions_to_doco_conclusion():
    assert map_jats_sec_type("conclusions") == ("Conclusion", f"{DOCO_IRI_PREFIX}Conclusion")


def test_map_jats_unknown_falls_to_other():
    label, iri = map_jats_sec_type("custom-xyz")
    assert label == "Other"
    assert "Other" in iri or iri == ""


def test_map_jats_none_returns_other():
    label, iri = map_jats_sec_type(None)
    assert label == "Other"


def test_map_section_heading_results():
    assert map_section_heading("Results")[0] == "Results"
    assert map_section_heading("3. Results and discussion")[0] in {"Results", "Discussion"}


def test_map_section_heading_methods():
    assert map_section_heading("Materials and Methods")[0] == "Methods"
    assert map_section_heading("Experimental Procedures")[0] == "Methods"


def test_map_section_heading_introduction():
    assert map_section_heading("Background")[0] == "Introduction"
    assert map_section_heading("Introduction")[0] == "Introduction"
```

- [ ] **Step 2: Run failing tests**

```bash
poetry run pytest apps/papers/tests/test_doco.py -v
```

Expected: ImportError on `papers.doco`.

- [ ] **Step 3: Implement `apps/papers/doco.py`**

```python
"""JATS / TEI section-type → DoCO IRI mapping.

DoCO (Document Components Ontology) is the SPAR vocabulary that names
canonical paper sections. We map both JATS @sec-type attributes and
free-form headings to a small set of DoCO classes:
    Introduction, Methods, Results, Discussion, Conclusion, Other.

(per spec §4 chunking stage)
"""
from __future__ import annotations

import re

DOCO_IRI_PREFIX = "http://purl.org/spar/doco/"

_DOCO_LABELS = {
    "Introduction": f"{DOCO_IRI_PREFIX}Introduction",
    "Methods": f"{DOCO_IRI_PREFIX}Methods",
    "Results": f"{DOCO_IRI_PREFIX}Results",
    "Discussion": f"{DOCO_IRI_PREFIX}Discussion",
    "Conclusion": f"{DOCO_IRI_PREFIX}Conclusion",
    "Other": f"{DOCO_IRI_PREFIX}Section",
}

_JATS_TYPE_MAP = {
    "intro": "Introduction",
    "introduction": "Introduction",
    "background": "Introduction",
    "methods": "Methods",
    "materials": "Methods",
    "materials|methods": "Methods",
    "methods|materials": "Methods",
    "results": "Results",
    "results|discussion": "Results",
    "discussion": "Discussion",
    "conclusions": "Conclusion",
    "conclusion": "Conclusion",
}

_HEADING_PATTERNS = [
    (re.compile(r"\bintroduction\b|\bbackground\b", re.I), "Introduction"),
    (re.compile(r"\bmethods?\b|\bmaterials\b|\bexperimental procedures?\b", re.I), "Methods"),
    (re.compile(r"\bresults?\b|\bfindings?\b", re.I), "Results"),
    (re.compile(r"\bdiscussion\b", re.I), "Discussion"),
    (re.compile(r"\bconclusions?\b|\bsummary\b", re.I), "Conclusion"),
]


def map_jats_sec_type(sec_type: str | None) -> tuple[str, str]:
    """Map JATS ``@sec-type`` → (label, IRI). Falls back to "Other"."""
    if not sec_type:
        return "Other", _DOCO_LABELS["Other"]
    key = sec_type.lower().strip()
    label = _JATS_TYPE_MAP.get(key, "Other")
    return label, _DOCO_LABELS[label]


def map_section_heading(heading: str | None) -> tuple[str, str]:
    """Map a free-form heading string → (label, IRI). Falls back to "Other"."""
    if not heading:
        return "Other", _DOCO_LABELS["Other"]
    for pattern, label in _HEADING_PATTERNS:
        if pattern.search(heading):
            return label, _DOCO_LABELS[label]
    return "Other", _DOCO_LABELS["Other"]
```

- [ ] **Step 4: Run tests**

```bash
poetry run pytest apps/papers/tests/test_doco.py -v
```

Expected:
```
10 passed
```

- [ ] **Step 5: Commit**

```bash
git add apps/papers/doco.py apps/papers/tests/test_doco.py
git commit -m "feat(papers): add DoCO section-type mapping (JATS + free heading)"
```

---

## Task 21: Sentence-boundary-aware chunker (TDD)

(per spec §4: "Split each Results section into chunks of ≤ 1800 tokens, 200-token overlap, sentence-boundary-aware".)

**Files:**
- Create: `apps/papers/tests/test_chunking.py`
- Create: `apps/papers/chunking.py`

- [ ] **Step 1: Write failing tests in `apps/papers/tests/test_chunking.py`**

```python
"""Tests for the sentence-aware chunker."""
from __future__ import annotations

from papers.chunking import ChunkRecord, chunk_text


def test_short_text_returns_one_chunk():
    chunks = chunk_text("This is a short result. It fits in one chunk.", max_tokens=1800)
    assert len(chunks) == 1
    assert isinstance(chunks[0], ChunkRecord)
    assert chunks[0].text.strip().startswith("This is a short result.")


def test_chunk_text_respects_sentence_boundaries():
    # 5 sentences, force chunk size that should split between them.
    text = " ".join(f"Sentence number {i} here." for i in range(50))
    chunks = chunk_text(text, max_tokens=40, overlap_tokens=5)
    assert len(chunks) > 1
    # Each chunk should end at a sentence boundary (period).
    for c in chunks[:-1]:
        assert c.text.strip().endswith(".")


def test_chunk_text_records_char_offsets():
    text = "First sentence. Second sentence. Third sentence."
    chunks = chunk_text(text, max_tokens=10, overlap_tokens=0)
    assert chunks[0].char_offset_start == 0
    for c in chunks:
        excerpt = text[c.char_offset_start:c.char_offset_end]
        assert c.text.strip() in excerpt or excerpt.strip() in c.text


def test_chunk_text_overlap_between_chunks():
    text = " ".join(f"Sentence {i} content here." for i in range(40))
    chunks = chunk_text(text, max_tokens=30, overlap_tokens=10)
    assert len(chunks) >= 2
    # The last few words of chunk N should appear in chunk N+1.
    tail = chunks[0].text.split()[-3:]
    assert any(w in chunks[1].text for w in tail)


def test_chunk_text_token_count_within_max():
    text = " ".join(f"Sentence number {i} present here." for i in range(80))
    chunks = chunk_text(text, max_tokens=40, overlap_tokens=5)
    for c in chunks:
        assert c.token_count <= 40 * 1.2  # allow modest slack for last-sentence boundary


def test_chunk_text_empty_input_returns_empty_list():
    assert chunk_text("", max_tokens=100) == []


def test_chunk_text_chunk_index_is_sequential():
    text = " ".join(f"S{i}." for i in range(200))
    chunks = chunk_text(text, max_tokens=20, overlap_tokens=2)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
```

- [ ] **Step 2: Run failing tests**

```bash
poetry run pytest apps/papers/tests/test_chunking.py -v
```

Expected: ImportError on `papers.chunking`.

- [ ] **Step 3: Implement `apps/papers/chunking.py`**

```python
"""Sentence-boundary-aware token chunker.

Splits a long text into chunks of ≤ ``max_tokens`` tokens, never cutting
mid-sentence. Adjacent chunks overlap by ``overlap_tokens`` to preserve
context for the extractor.

Token counting uses tiktoken's cl100k_base encoding. NLTK's
``punkt_tab`` sentence tokenizer provides the sentence boundaries; we
lazy-download it on first use so production containers don't have to
pre-bake the resource.
"""
from __future__ import annotations

from dataclasses import dataclass

import nltk
import tiktoken


@dataclass
class ChunkRecord:
    chunk_index: int
    text: str
    token_count: int
    char_offset_start: int
    char_offset_end: int


_ENCODER = tiktoken.get_encoding("cl100k_base")
_NLTK_READY = False


def _ensure_nltk() -> None:
    global _NLTK_READY
    if _NLTK_READY:
        return
    try:
        nltk.data.find("tokenizers/punkt_tab")
    except LookupError:
        nltk.download("punkt_tab", quiet=True)
    _NLTK_READY = True


def _count_tokens(s: str) -> int:
    return len(_ENCODER.encode(s))


def _sentences_with_offsets(text: str) -> list[tuple[str, int, int]]:
    """Return list of (sentence_text, char_start, char_end)."""
    _ensure_nltk()
    from nltk.tokenize import PunktSentenceTokenizer

    tokenizer = PunktSentenceTokenizer()
    spans = list(tokenizer.span_tokenize(text))
    return [(text[start:end], start, end) for start, end in spans]


def chunk_text(
    text: str,
    *,
    max_tokens: int = 1800,
    overlap_tokens: int = 200,
) -> list[ChunkRecord]:
    """Greedy pack sentences into chunks of ≤ max_tokens.

    Sentences exceeding max_tokens are emitted on their own (last-resort
    overflow) — never split mid-sentence even if oversized.
    """
    if not text.strip():
        return []

    sentences = _sentences_with_offsets(text)
    if not sentences:
        return []

    chunks: list[ChunkRecord] = []
    chunk_index = 0
    i = 0
    n = len(sentences)
    while i < n:
        buffer: list[tuple[str, int, int]] = []
        token_total = 0
        j = i
        while j < n:
            sent_text, start, end = sentences[j]
            sent_tokens = _count_tokens(sent_text)
            if token_total + sent_tokens > max_tokens and buffer:
                break
            buffer.append((sent_text, start, end))
            token_total += sent_tokens
            j += 1
        if not buffer:
            # Single sentence longer than max_tokens — emit anyway.
            sent_text, start, end = sentences[i]
            buffer = [(sent_text, start, end)]
            token_total = _count_tokens(sent_text)
            j = i + 1

        chunk_str = " ".join(s for s, _, _ in buffer).strip()
        start_offset = buffer[0][1]
        end_offset = buffer[-1][2]
        chunks.append(
            ChunkRecord(
                chunk_index=chunk_index,
                text=chunk_str,
                token_count=token_total,
                char_offset_start=start_offset,
                char_offset_end=end_offset,
            )
        )
        chunk_index += 1

        if j >= n:
            break

        # Walk back from j until overlap_tokens of context is captured.
        if overlap_tokens <= 0:
            i = j
            continue
        overlap_total = 0
        k = j - 1
        while k > i and overlap_total < overlap_tokens:
            overlap_total += _count_tokens(sentences[k][0])
            k -= 1
        i = max(k + 1, i + 1)

    return chunks
```

- [ ] **Step 4: Run tests**

```bash
poetry run pytest apps/papers/tests/test_chunking.py -v
```

Expected:
```
7 passed
```

- [ ] **Step 5: Commit**

```bash
git add apps/papers/chunking.py apps/papers/tests/test_chunking.py
git commit -m "feat(papers): add sentence-boundary-aware token chunker"
```

---

## Task 22: JATS XML parser (TDD)

(per spec §4: "Parse XML → map section types to DoCO IRIs. Keep doco:Results sections (plus doco:Conclusions tagged as aux)".)

**Files:**
- Create: `apps/papers/tests/fixtures/sample_jats.xml`
- Create: `apps/papers/tests/test_jats.py`
- Create: `apps/papers/jats.py`

- [ ] **Step 1: Create `apps/papers/tests/fixtures/sample_jats.xml`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<article xmlns="http://jats.nlm.nih.gov/ns/archiving/1.3/">
  <front>
    <article-meta>
      <article-id pub-id-type="pmid">38000123</article-id>
    </article-meta>
  </front>
  <body>
    <sec sec-type="intro">
      <title>Introduction</title>
      <p>Intervertebral disc degeneration is a leading cause of low-back pain.</p>
      <p>HIF1A is implicated in NP cell survival.</p>
    </sec>
    <sec sec-type="methods">
      <title>Methods</title>
      <p>Human NP cells were cultured under 1% O2.</p>
    </sec>
    <sec sec-type="results">
      <title>Results</title>
      <p>Hypoxia upregulated HIF1A 5-fold (p&lt;0.001).</p>
      <p>NF-κB signalling was suppressed under low oxygen.</p>
      <sec>
        <title>Sub-result A</title>
        <p>SOX9 levels increased.</p>
      </sec>
    </sec>
    <sec sec-type="conclusions">
      <title>Conclusions</title>
      <p>HIF1A drives NP-cell adaptation to hypoxia.</p>
    </sec>
  </body>
</article>
```

- [ ] **Step 2: Write failing tests in `apps/papers/tests/test_jats.py`**

```python
"""Tests for papers.jats."""
from __future__ import annotations

from pathlib import Path

from papers.jats import parse_jats

FIXTURE = Path(__file__).parent / "fixtures" / "sample_jats.xml"


def test_parse_jats_returns_sections():
    sections = parse_jats(FIXTURE.read_bytes())
    assert len(sections) >= 4
    labels = [s.doco_label for s in sections]
    assert "Introduction" in labels
    assert "Methods" in labels
    assert "Results" in labels
    assert "Conclusion" in labels


def test_parse_jats_results_includes_text():
    sections = parse_jats(FIXTURE.read_bytes())
    results = [s for s in sections if s.doco_label == "Results"]
    assert len(results) == 1
    assert "HIF1A" in results[0].body_text
    assert "NF-κB" in results[0].body_text or "NF" in results[0].body_text


def test_parse_jats_results_includes_subsections():
    sections = parse_jats(FIXTURE.read_bytes())
    results = [s for s in sections if s.doco_label == "Results"][0]
    assert "SOX9" in results.body_text


def test_parse_jats_assigns_doco_iri():
    sections = parse_jats(FIXTURE.read_bytes())
    for s in sections:
        assert s.doco_iri.startswith("http://purl.org/spar/doco/")


def test_parse_jats_assigns_order_index():
    sections = parse_jats(FIXTURE.read_bytes())
    indices = [s.order_index for s in sections]
    assert indices == sorted(indices)
    assert indices[0] == 0


def test_parse_jats_preserves_heading():
    sections = parse_jats(FIXTURE.read_bytes())
    headings = {s.heading for s in sections}
    assert "Introduction" in headings
    assert "Methods" in headings
```

- [ ] **Step 3: Run failing tests**

```bash
poetry run pytest apps/papers/tests/test_jats.py -v
```

Expected: ImportError on `papers.jats`.

- [ ] **Step 4: Implement `apps/papers/jats.py`**

```python
"""Parse JATS XML (Europe PMC) into section records.

Output: list[ParsedSection] in document order, with DoCO labels +
IRIs from papers.doco.
"""
from __future__ import annotations

from dataclasses import dataclass

from lxml import etree

from papers.doco import map_jats_sec_type, map_section_heading


@dataclass
class ParsedSection:
    order_index: int
    doco_label: str
    doco_iri: str
    heading: str
    body_text: str


def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _collect_text(el: etree._Element) -> str:
    """Concatenate all <p> descendants of ``el`` (including sub-sections)."""
    parts: list[str] = []
    for p in el.iter():
        if _strip_ns(p.tag) == "p":
            text = " ".join(p.itertext()).strip()
            if text:
                parts.append(text)
    return "\n\n".join(parts)


def parse_jats(xml_bytes: bytes) -> list[ParsedSection]:
    """Return one ParsedSection per top-level <sec> in <body>."""
    tree = etree.fromstring(xml_bytes)
    sections: list[ParsedSection] = []
    body_elements = [el for el in tree.iter() if _strip_ns(el.tag) == "body"]
    if not body_elements:
        return []
    body = body_elements[0]
    order = 0
    for sec in body:
        if _strip_ns(sec.tag) != "sec":
            continue
        sec_type = sec.get("sec-type")
        heading = ""
        for child in sec:
            if _strip_ns(child.tag) == "title":
                heading = " ".join(child.itertext()).strip()
                break
        if sec_type:
            label, iri = map_jats_sec_type(sec_type)
        else:
            label, iri = map_section_heading(heading)
        body_text = _collect_text(sec)
        sections.append(
            ParsedSection(
                order_index=order,
                doco_label=label,
                doco_iri=iri,
                heading=heading,
                body_text=body_text,
            )
        )
        order += 1
    return sections
```

- [ ] **Step 5: Run tests**

```bash
poetry run pytest apps/papers/tests/test_jats.py -v
```

Expected:
```
6 passed
```

- [ ] **Step 6: Commit**

```bash
git add apps/papers/jats.py apps/papers/tests/fixtures/sample_jats.xml apps/papers/tests/test_jats.py
git commit -m "feat(papers): add JATS XML parser with DoCO mapping"
```

---

## Task 23: GROBID PDF→TEI client (TDD)

(per spec §5: "GROBID (local sidecar) | PDF → TEI XML for non-PMC papers".)

**Files:**
- Create: `apps/papers/tests/fixtures/sample_grobid_tei.xml`
- Create: `apps/papers/tests/test_grobid.py`
- Create: `apps/papers/grobid.py`

- [ ] **Step 1: Create `apps/papers/tests/fixtures/sample_grobid_tei.xml`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader>
    <fileDesc>
      <titleStmt><title>Sample paper</title></titleStmt>
    </fileDesc>
  </teiHeader>
  <text>
    <body>
      <div xmlns="http://www.tei-c.org/ns/1.0">
        <head>Introduction</head>
        <p>Disc degeneration is studied here.</p>
      </div>
      <div xmlns="http://www.tei-c.org/ns/1.0">
        <head>Results</head>
        <p>HIF1A was upregulated.</p>
      </div>
    </body>
  </text>
</TEI>
```

- [ ] **Step 2: Write failing tests in `apps/papers/tests/test_grobid.py`**

```python
"""Tests for papers.grobid.GrobidClient."""
from __future__ import annotations

from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from papers.grobid import GrobidClient, GrobidFailure
from schedule.models import RateLimitBucket

FIXTURE = Path(__file__).parent / "fixtures" / "sample_grobid_tei.xml"


@pytest.fixture(autouse=True)
def _bucket(db):
    RateLimitBucket.objects.create(
        provider="grobid", capacity=4, refill_per_sec=4.0, current_tokens=4.0
    )


@pytest.fixture
def client(settings):
    settings.GROBID_BASE_URL = "http://grobid.example.com:8070"
    settings.GROBID_TIMEOUT = 60.0
    return GrobidClient()


def test_process_pdf_returns_tei(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="POST",
        url="http://grobid.example.com:8070/api/processFulltextDocument",
        content=FIXTURE.read_bytes(),
    )
    tei = client.process_pdf(pdf_bytes=b"%PDF-1.4 fake")
    assert b"<TEI" in tei
    assert b"HIF1A" in tei


def test_process_pdf_raises_on_5xx(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="POST",
        url="http://grobid.example.com:8070/api/processFulltextDocument",
        status_code=503,
        text="busy",
    )
    with pytest.raises(GrobidFailure):
        client.process_pdf(pdf_bytes=b"%PDF-1.4 fake")


def test_process_pdf_consumes_rate_limit_token(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="POST",
        url="http://grobid.example.com:8070/api/processFulltextDocument",
        content=FIXTURE.read_bytes(),
    )
    before = RateLimitBucket.objects.get(provider="grobid").current_tokens
    client.process_pdf(pdf_bytes=b"%PDF-1.4 fake")
    after = RateLimitBucket.objects.get(provider="grobid").current_tokens
    assert after < before


def test_grobid_alive_check(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="GET",
        url="http://grobid.example.com:8070/api/isalive",
        text="true",
    )
    assert client.is_alive() is True
```

- [ ] **Step 3: Run failing tests**

```bash
poetry run pytest apps/papers/tests/test_grobid.py -v
```

Expected: ImportError on `papers.grobid`.

- [ ] **Step 4: Implement `apps/papers/grobid.py`**

```python
"""GROBID PDF → TEI XML client.

GROBID runs as a local sidecar container. We POST the raw PDF and get
back a TEI XML document with structured sections (parsed downstream by
``papers.tei`` — but for Phase 1 we mostly fall through to chunking via
JATS, since most disc papers are in PMC).

(per spec §5)
"""
from __future__ import annotations

import httpx
from django.conf import settings

from schedule.ratelimit import require_token


class GrobidFailure(RuntimeError):
    """GROBID returned a non-2xx response."""


class GrobidClient:
    def __init__(self) -> None:
        self._base_url = settings.GROBID_BASE_URL.rstrip("/")
        self._timeout = settings.GROBID_TIMEOUT
        self._client = httpx.Client(timeout=self._timeout)

    @require_token("grobid", cost=1)
    def process_pdf(self, *, pdf_bytes: bytes) -> bytes:
        url = f"{self._base_url}/api/processFulltextDocument"
        files = {"input": ("paper.pdf", pdf_bytes, "application/pdf")}
        resp = self._client.post(url, files=files)
        if not resp.is_success:
            raise GrobidFailure(
                f"GROBID returned {resp.status_code}: {resp.text[:200]}"
            )
        return resp.content

    def is_alive(self) -> bool:
        try:
            resp = self._client.get(f"{self._base_url}/api/isalive", timeout=5.0)
        except httpx.HTTPError:
            return False
        return resp.is_success and resp.text.strip().lower() == "true"
```

- [ ] **Step 5: Run tests**

```bash
poetry run pytest apps/papers/tests/test_grobid.py -v
```

Expected:
```
4 passed
```

- [ ] **Step 6: Commit**

```bash
git add apps/papers/grobid.py apps/papers/tests/fixtures/sample_grobid_tei.xml apps/papers/tests/test_grobid.py
git commit -m "feat(papers): add GROBID PDF→TEI client"
```

---

## Task 24: `corpus.refresh_pubmed` task (TDD)

(per spec §4 first stage and §6 Beat schedule: "every 1 hour — incremental PubMed sweep using watermark".)

**Files:**
- Create: `apps/corpus/tests/test_refresh_pubmed.py`
- Create: `apps/corpus/tasks.py`

- [ ] **Step 1: Write failing tests in `apps/corpus/tests/test_refresh_pubmed.py`**

```python
"""Tests for corpus.tasks.refresh_pubmed."""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from corpus.models import IngestRun, Paper
from corpus.tasks import refresh_pubmed
from schedule.models import RateLimitBucket, Watermark


@pytest.fixture(autouse=True)
def _eager(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True


@pytest.fixture(autouse=True)
def _bucket(db):
    RateLimitBucket.objects.create(
        provider="ncbi_eutils", capacity=10, refill_per_sec=10.0, current_tokens=10.0
    )


def test_refresh_pubmed_calls_esearch_and_enqueues_ingest(db):
    pmids = [38000123, 38000124]
    with patch("corpus.tasks.NcbiClient") as MockCls, \
         patch("corpus.tasks.ingest_paper.delay") as mock_enqueue:
        instance = MockCls.return_value
        instance.esearch.return_value = pmids
        result = refresh_pubmed.delay().get(timeout=2)
    assert result["n_pmids_seen"] == 2
    assert mock_enqueue.call_count == 2


def test_refresh_pubmed_creates_ingest_run_row(db):
    with patch("corpus.tasks.NcbiClient") as MockCls, \
         patch("corpus.tasks.ingest_paper.delay"):
        instance = MockCls.return_value
        instance.esearch.return_value = [1, 2, 3]
        refresh_pubmed.delay().get(timeout=2)
    runs = list(IngestRun.objects.all())
    assert len(runs) == 1
    assert runs[0].source == "pubmed"
    assert runs[0].n_pmids_seen == 3
    assert runs[0].finished_at is not None


def test_refresh_pubmed_advances_watermark(db):
    with patch("corpus.tasks.NcbiClient") as MockCls, \
         patch("corpus.tasks.ingest_paper.delay"):
        instance = MockCls.return_value
        instance.esearch.return_value = [38000125, 38000123, 38000124]
        refresh_pubmed.delay().get(timeout=2)
    wm = Watermark.objects.get(source="pubmed")
    assert wm.last_pmid_seen == 38000125


def test_refresh_pubmed_uses_incremental_query_when_watermark_exists(db):
    Watermark.objects.create(source="pubmed", last_entrez_date=date(2024, 1, 1))
    with patch("corpus.tasks.NcbiClient") as MockCls, \
         patch("corpus.tasks.ingest_paper.delay"):
        instance = MockCls.return_value
        instance.esearch.return_value = []
        refresh_pubmed.delay().get(timeout=2)
        called_query = instance.esearch.call_args.kwargs["query"]
        assert "EDAT" in called_query


def test_refresh_pubmed_skips_existing_pmids(db):
    Paper.objects.create(pmid=38000123, title="already here")
    with patch("corpus.tasks.NcbiClient") as MockCls, \
         patch("corpus.tasks.ingest_paper.delay") as mock_enqueue:
        instance = MockCls.return_value
        instance.esearch.return_value = [38000123, 38000999]
        refresh_pubmed.delay().get(timeout=2)
    enqueued = {c.args[0] for c in mock_enqueue.call_args_list}
    assert enqueued == {38000999}
```

- [ ] **Step 2: Run failing tests**

```bash
poetry run pytest apps/corpus/tests/test_refresh_pubmed.py -v
```

Expected: ImportError on `corpus.tasks`.

- [ ] **Step 3: Implement `apps/corpus/tasks.py`** (the full task module is built across Tasks 24–28; this step creates it with `refresh_pubmed` + `refresh_pubmed_full` only)

```python
"""corpus.tasks — refresh_pubmed, ingest_paper, triage_relevance, ...

Each task is idempotent: first line short-circuits if work is already
done (per spec §8 resumability pattern).
"""
from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from corpus.clients.ncbi import NcbiClient
from corpus.models import IngestRun, Paper
from corpus.pubmed_query import MASTER_IDD_QUERY, build_incremental_query
from schedule.ratelimit import RateLimitExceeded
from schedule.watermarks import advance_watermark, get_watermark

logger = logging.getLogger(__name__)


@shared_task(
    name="corpus.tasks.refresh_pubmed",
    bind=True,
    autoretry_for=(RateLimitExceeded,),
    retry_backoff=True,
    max_retries=5,
)
def refresh_pubmed(self) -> dict:
    """Incremental PubMed sweep. Enqueues ingest_paper for each new PMID."""
    wm = get_watermark("pubmed")
    query = build_incremental_query(since=wm.last_entrez_date)
    client = NcbiClient()
    run = IngestRun.objects.create(source="pubmed", query=query)
    try:
        pmids = client.esearch(query=query, retmax=10000)
        existing = set(Paper.objects.filter(pmid__in=pmids).values_list("pmid", flat=True))
        new_pmids = [p for p in pmids if p not in existing]
        for pmid in new_pmids:
            ingest_paper.delay(pmid)
        run.n_pmids_seen = len(pmids)
        run.n_papers_created = 0  # incremented later by ingest_paper itself
        run.finished_at = timezone.now()
        run.save()
        if pmids:
            advance_watermark("pubmed", last_pmid_seen=max(pmids))
        return {
            "n_pmids_seen": len(pmids),
            "n_new": len(new_pmids),
        }
    except Exception as exc:
        run.error = str(exc)[:4000]
        run.finished_at = timezone.now()
        run.save()
        raise


@shared_task(
    name="corpus.tasks.refresh_pubmed_full",
    bind=True,
    autoretry_for=(RateLimitExceeded,),
    retry_backoff=True,
    max_retries=5,
)
def refresh_pubmed_full(self) -> dict:
    """Weekly full re-sweep with the unbounded master query.

    Re-finds papers that may have been missed by incremental runs.
    (per spec §6: weekly Sunday 03:00 UTC)
    """
    client = NcbiClient()
    run = IngestRun.objects.create(source="pubmed_full", query=MASTER_IDD_QUERY)
    pmids = client.esearch(query=MASTER_IDD_QUERY, retmax=100000)
    existing = set(Paper.objects.filter(pmid__in=pmids).values_list("pmid", flat=True))
    new_pmids = [p for p in pmids if p not in existing]
    for pmid in new_pmids:
        ingest_paper.delay(pmid)
    run.n_pmids_seen = len(pmids)
    run.finished_at = timezone.now()
    run.save()
    return {"n_pmids_seen": len(pmids), "n_new": len(new_pmids)}


@shared_task(
    name="corpus.tasks.ingest_paper",
    bind=True,
    autoretry_for=(RateLimitExceeded,),
    retry_backoff=True,
    max_retries=5,
)
def ingest_paper(self, pmid: int) -> str:
    """Fetch metadata for one PMID and upsert a Paper row.

    Implemented in Task 25.
    """
    raise NotImplementedError("filled in by Task 25")


@shared_task(name="corpus.tasks.triage_pending")
def triage_pending() -> dict:
    """Beat entrypoint: scan for papers needing triage. Filled in by Task 28."""
    return {"queued": 0}


@shared_task(name="corpus.tasks.triage_relevance_cheap")
def triage_relevance_cheap(paper_id: int) -> dict:
    """Filled in by Task 28."""
    return {}


@shared_task(name="corpus.tasks.triage_relevance_llm")
def triage_relevance_llm(paper_id: int, network_id: int) -> dict:
    """Filled in by Task 28."""
    return {}
```

- [ ] **Step 4: Run tests**

```bash
poetry run pytest apps/corpus/tests/test_refresh_pubmed.py -v
```

Expected:
```
5 passed
```

- [ ] **Step 5: Commit**

```bash
git add apps/corpus/tasks.py apps/corpus/tests/test_refresh_pubmed.py
git commit -m "feat(corpus): add refresh_pubmed task with watermark + incremental query"
```

---

## Task 25: `corpus.ingest_paper` task (TDD)

(per spec §4: "efetch metadata → INSERT Paper(pmid, title, abstract, pubtypes, ...); PubTator3 fetch → cached entity annotations; Status: PAPER_INGESTED".)

**Files:**
- Create: `apps/corpus/tests/test_ingest_paper.py`
- Modify: `apps/corpus/tasks.py`

- [ ] **Step 1: Write failing tests in `apps/corpus/tests/test_ingest_paper.py`**

```python
"""Tests for corpus.tasks.ingest_paper."""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from corpus.clients.ncbi import PaperMetadata
from corpus.models import Paper
from corpus.tasks import ingest_paper
from schedule.models import RateLimitBucket


@pytest.fixture(autouse=True)
def _eager(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True


@pytest.fixture(autouse=True)
def _buckets(db):
    RateLimitBucket.objects.create(
        provider="ncbi_eutils", capacity=10, refill_per_sec=10.0, current_tokens=10.0
    )
    RateLimitBucket.objects.create(
        provider="pubtator3", capacity=10, refill_per_sec=10.0, current_tokens=10.0
    )


def _stub_meta(pmid=38000123) -> PaperMetadata:
    return PaperMetadata(
        pmid=pmid,
        title="A hypoxia study",
        abstract="HIF1A upregulated.",
        journal="Spine",
        doi="10.1/x",
        pmcid="PMC11000000",
        publication_date=date(2024, 5, 1),
        entrez_date=date(2024, 5, 2),
        publication_types=["Journal Article"],
        mesh_terms=["Intervertebral Disc"],
        authors=[{"last": "Doe", "first": "Jane"}],
    )


def test_ingest_paper_creates_row(db):
    with patch("corpus.tasks.NcbiClient") as M, \
         patch("corpus.tasks.PubtatorClient") as P:
        M.return_value.efetch.return_value = [_stub_meta()]
        P.return_value.get_annotations.return_value = [
            {"text": "HIF1A", "type": "Gene", "identifier": "3091"}
        ]
        ingest_paper.delay(38000123).get(timeout=2)
    p = Paper.objects.get(pmid=38000123)
    assert p.title.startswith("A hypoxia study")
    assert p.doi == "10.1/x"
    assert p.pmcid == "PMC11000000"
    assert p.ingest_status == "ingested"


def test_ingest_paper_stores_pubtator_entities(db):
    with patch("corpus.tasks.NcbiClient") as M, \
         patch("corpus.tasks.PubtatorClient") as P:
        M.return_value.efetch.return_value = [_stub_meta()]
        P.return_value.get_annotations.return_value = [
            {"text": "HIF1A", "type": "Gene", "identifier": "3091"},
            {"text": "NFKB1", "type": "Gene", "identifier": "4790"},
        ]
        ingest_paper.delay(38000123).get(timeout=2)
    p = Paper.objects.get(pmid=38000123)
    texts = {e["text"] for e in p.pubtator_entities}
    assert "HIF1A" in texts
    assert "NFKB1" in texts


def test_ingest_paper_is_idempotent(db):
    Paper.objects.create(
        pmid=38000123, title="seed", ingest_status="ingested"
    )
    with patch("corpus.tasks.NcbiClient") as M, \
         patch("corpus.tasks.PubtatorClient"):
        M.return_value.efetch.return_value = [_stub_meta()]
        ingest_paper.delay(38000123).get(timeout=2)
    # Existing row should be preserved (no IntegrityError, no second row).
    assert Paper.objects.count() == 1


def test_ingest_paper_missing_efetch_marks_failed(db):
    with patch("corpus.tasks.NcbiClient") as M, \
         patch("corpus.tasks.PubtatorClient"):
        M.return_value.efetch.return_value = []
        ingest_paper.delay(99999).get(timeout=2)
    p = Paper.objects.get(pmid=99999)
    assert p.ingest_status == "ingest_failed"


def test_ingest_paper_pubtator_failure_does_not_block(db):
    with patch("corpus.tasks.NcbiClient") as M, \
         patch("corpus.tasks.PubtatorClient") as P:
        M.return_value.efetch.return_value = [_stub_meta()]
        P.return_value.get_annotations.side_effect = RuntimeError("pubtator down")
        ingest_paper.delay(38000123).get(timeout=2)
    p = Paper.objects.get(pmid=38000123)
    assert p.ingest_status == "ingested"
    assert p.pubtator_entities == []
```

- [ ] **Step 2: Run failing tests**

```bash
poetry run pytest apps/corpus/tests/test_ingest_paper.py -v
```

Expected: tests fail because `ingest_paper` raises NotImplementedError.

- [ ] **Step 3: Implement `ingest_paper` in `apps/corpus/tasks.py`**

Replace the placeholder `ingest_paper` body with:

```python
@shared_task(
    name="corpus.tasks.ingest_paper",
    bind=True,
    autoretry_for=(RateLimitExceeded,),
    retry_backoff=True,
    max_retries=5,
)
def ingest_paper(self, pmid: int) -> str:
    """Fetch metadata + PubTator annotations for one PMID; upsert Paper row."""
    paper, _created = Paper.objects.get_or_create(
        pmid=pmid, defaults={"title": "", "ingest_status": "pending"}
    )
    if paper.ingest_status in {"ingested", "classified", "fetched", "chunked", "done"}:
        return paper.ingest_status

    paper.ingest_status = "running"
    paper.ingest_attempts += 1
    paper.ingest_heartbeat = timezone.now()
    paper.save(update_fields=["ingest_status", "ingest_attempts", "ingest_heartbeat"])

    try:
        ncbi = NcbiClient()
        results = ncbi.efetch(pmids=[pmid])
        if not results:
            paper.ingest_status = "ingest_failed"
            paper.ingest_error = "efetch returned no records"
            paper.save(update_fields=["ingest_status", "ingest_error"])
            return "ingest_failed"
        meta = results[0]
        paper.title = meta.title
        paper.abstract = meta.abstract
        paper.journal = meta.journal
        paper.doi = meta.doi
        paper.pmcid = meta.pmcid
        paper.publication_date = meta.publication_date
        paper.entrez_date = meta.entrez_date
        paper.publication_types = meta.publication_types
        paper.mesh_terms = meta.mesh_terms
        paper.authors = meta.authors

        try:
            from corpus.clients.pubtator import PubtatorClient
            pubtator = PubtatorClient()
            paper.pubtator_entities = pubtator.get_annotations(pmid=pmid)
        except Exception as pt_exc:
            logger.warning("PubTator fetch failed for %s: %s", pmid, pt_exc)
            paper.pubtator_entities = []

        paper.ingest_status = "ingested"
        paper.ingest_error = ""
        paper.save()
        # Hand off to the classifier — wired in Task 26.
        from papers.tasks import classify_original
        classify_original.delay(pmid)
        return "ingested"
    except Exception as exc:
        paper.ingest_status = "ingest_failed"
        paper.ingest_error = str(exc)[:4000]
        paper.save(update_fields=["ingest_status", "ingest_error"])
        raise
```

Also add to the imports at the top of `corpus/tasks.py`:

```python
from corpus.clients.pubtator import PubtatorClient  # type: ignore[import-not-found]
```

(The lazy `from corpus.clients.pubtator import PubtatorClient` inside the
try block is the resilience path. The top-level import is for mocking
in tests.)

- [ ] **Step 4: Run tests**

```bash
poetry run pytest apps/corpus/tests/test_ingest_paper.py -v
```

Expected:
```
5 passed
```

- [ ] **Step 5: Commit**

```bash
git add apps/corpus/tasks.py apps/corpus/tests/test_ingest_paper.py
git commit -m "feat(corpus): implement ingest_paper task with PubTator enrichment"
```

---

## Task 26: `papers.classify_original` task (TDD)

(per spec §4: "Cheap path: if `Review`/`Meta-Analysis` in pubtypes → is_original=F. Expensive path: LLM (qwen3:8b) reads abstract+title".)

**Files:**
- Create: `apps/papers/tests/test_classify_original.py`
- Create: `apps/papers/tasks.py`

- [ ] **Step 1: Write failing tests in `apps/papers/tests/test_classify_original.py`**

```python
"""Tests for papers.tasks.classify_original."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from corpus.models import Paper
from papers.models import PaperClassification
from papers.tasks import classify_original, classify_pending


@pytest.fixture(autouse=True)
def _eager(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True


def test_cheap_path_marks_review_as_non_original(db):
    p = Paper.objects.create(
        pmid=1,
        title="A review",
        abstract="x",
        publication_types=["Review"],
        ingest_status="ingested",
    )
    classify_original.delay(1).get(timeout=2)
    p.refresh_from_db()
    assert p.is_original is False
    pc = PaperClassification.objects.get(paper=p)
    assert pc.classifier == "rule:pubtype"
    assert pc.is_original is False


def test_cheap_path_marks_meta_analysis_as_non_original(db):
    p = Paper.objects.create(
        pmid=2,
        title="A meta",
        abstract="x",
        publication_types=["Meta-Analysis"],
        ingest_status="ingested",
    )
    classify_original.delay(2).get(timeout=2)
    p.refresh_from_db()
    assert p.is_original is False


def test_cheap_path_marks_systematic_review_as_non_original(db):
    p = Paper.objects.create(
        pmid=3,
        title="x",
        abstract="x",
        publication_types=["Systematic Review"],
        ingest_status="ingested",
    )
    classify_original.delay(3).get(timeout=2)
    p.refresh_from_db()
    assert p.is_original is False


def test_llm_path_invoked_when_pubtype_ambiguous(db):
    p = Paper.objects.create(
        pmid=4,
        title="A study",
        abstract="Original data.",
        publication_types=["Journal Article"],
        ingest_status="ingested",
    )
    fake_llm_response = {
        "response": json.dumps({
            "is_original": True,
            "confidence": 0.93,
            "reason": "Reports primary experiments.",
        })
    }
    with patch("papers.tasks.OllamaClient") as M:
        M.return_value.generate.return_value = fake_llm_response
        classify_original.delay(4).get(timeout=2)
    p.refresh_from_db()
    assert p.is_original is True
    pc = PaperClassification.objects.get(paper=p)
    assert pc.classifier == "llm:qwen3:8b"
    assert 0.9 < pc.confidence < 1.0


def test_llm_path_returns_non_original(db):
    p = Paper.objects.create(
        pmid=5,
        title="An editorial",
        abstract="Opinion piece.",
        publication_types=["Journal Article"],
        ingest_status="ingested",
    )
    fake_response = {
        "response": json.dumps({
            "is_original": False,
            "confidence": 0.85,
            "reason": "Editorial opinion, no primary data.",
        })
    }
    with patch("papers.tasks.OllamaClient") as M:
        M.return_value.generate.return_value = fake_response
        classify_original.delay(5).get(timeout=2)
    p.refresh_from_db()
    assert p.is_original is False


def test_llm_bad_json_falls_back_to_rule(db):
    p = Paper.objects.create(
        pmid=6,
        title="A study",
        abstract="Data.",
        publication_types=["Journal Article"],
        ingest_status="ingested",
    )
    with patch("papers.tasks.OllamaClient") as M:
        M.return_value.generate.return_value = {"response": "not json {{{"}
        classify_original.delay(6).get(timeout=2)
    p.refresh_from_db()
    # Fallback: default to is_original=True (conservative — keeps it in pipeline)
    assert p.is_original is True
    pc = PaperClassification.objects.get(paper=p)
    assert pc.classifier == "rule:pubtype"


def test_classify_original_advances_ingest_status_to_classified(db):
    p = Paper.objects.create(
        pmid=7,
        title="A review",
        publication_types=["Review"],
        ingest_status="ingested",
    )
    classify_original.delay(7).get(timeout=2)
    p.refresh_from_db()
    assert p.ingest_status == "classified"


def test_classify_pending_picks_up_unclassified_papers(db):
    p = Paper.objects.create(pmid=8, title="x", ingest_status="ingested")
    Paper.objects.create(pmid=9, title="y", ingest_status="pending")  # not eligible
    with patch("papers.tasks.classify_original.delay") as mock_enqueue:
        classify_pending.delay().get(timeout=2)
    enqueued = {c.args[0] for c in mock_enqueue.call_args_list}
    assert 8 in enqueued
    assert 9 not in enqueued
```

- [ ] **Step 2: Run failing tests**

```bash
poetry run pytest apps/papers/tests/test_classify_original.py -v
```

Expected: ImportError on `papers.tasks`.

- [ ] **Step 3: Implement `apps/papers/tasks.py`**

```python
"""papers.tasks — classify_original, fetch_fulltext, section_and_chunk.

Cheap-first classification per spec §4:
- Rule-based on PubMed publication types catches Reviews / Meta-Analyses
  / Systematic Reviews / Editorials (~70% per spec).
- LLM fallback (qwen3:8b) reads title+abstract and returns a structured
  JSON verdict.

The Beat schedule fires `classify_pending` every 15 minutes to sweep
any Paper with `ingest_status='ingested'`.
"""
from __future__ import annotations

import json
import logging

from celery import shared_task
from django.conf import settings

from core.ollama import OllamaClient
from corpus.models import Paper
from papers.models import PaperClassification

logger = logging.getLogger(__name__)

# PubTypes that unambiguously mean "not primary research".
NON_ORIGINAL_PUBTYPES = {
    "Review",
    "Meta-Analysis",
    "Systematic Review",
    "Editorial",
    "Comment",
    "News",
    "Practice Guideline",
    "Letter",
}

CLASSIFY_PROMPT = """You are classifying a biomedical paper as either
ORIGINAL primary research or a SECONDARY work (review, editorial,
commentary, opinion piece, guideline).

Title: {title}

Abstract: {abstract}

Reply ONLY with a JSON object of the form:
{{"is_original": true|false, "confidence": 0.0..1.0, "reason": "short reason"}}
"""

CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "is_original": {"type": "boolean"},
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["is_original", "confidence"],
}


@shared_task(name="papers.tasks.classify_pending")
def classify_pending() -> dict:
    """Beat entrypoint — enqueue classify_original for unclassified papers."""
    queued = 0
    for pmid in Paper.objects.filter(
        ingest_status="ingested", is_original__isnull=True
    ).values_list("pmid", flat=True):
        classify_original.delay(pmid)
        queued += 1
    return {"queued": queued}


@shared_task(name="papers.tasks.classify_original")
def classify_original(pmid: int) -> str:
    """Classify one paper as original vs review/secondary."""
    paper = Paper.objects.get(pmid=pmid)
    if paper.is_original is not None:
        return "already_classified"

    pubtypes = set(paper.publication_types or [])
    matched = pubtypes & NON_ORIGINAL_PUBTYPES
    if matched:
        _save_classification(
            paper,
            is_original=False,
            confidence=1.0,
            classifier="rule:pubtype",
            reason=f"publication_types contains {sorted(matched)}",
        )
        return "rule:non_original"

    # Expensive path: LLM
    prompt = CLASSIFY_PROMPT.format(
        title=paper.title[:500],
        abstract=(paper.abstract or "")[:3000],
    )
    is_original = True
    confidence = 0.5
    reason = "default"
    classifier = "rule:pubtype"
    try:
        client = OllamaClient()
        raw = client.generate(
            model="qwen3:8b",
            prompt=prompt,
            format=CLASSIFY_SCHEMA,
            options={"temperature": 0.0},
        )
        text = raw.get("response", "")
        payload = json.loads(text)
        is_original = bool(payload["is_original"])
        confidence = float(payload.get("confidence", 0.5))
        reason = str(payload.get("reason", "")).strip()[:500]
        classifier = "llm:qwen3:8b"
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
        logger.warning("LLM classify fell back to rule for pmid=%s: %s", pmid, exc)
        is_original = True  # conservative — keep in pipeline
        reason = f"llm_fallback: {exc}"

    _save_classification(
        paper,
        is_original=is_original,
        confidence=confidence,
        classifier=classifier,
        reason=reason,
    )
    return classifier


def _save_classification(
    paper: Paper,
    *,
    is_original: bool,
    confidence: float,
    classifier: str,
    reason: str,
) -> None:
    PaperClassification.objects.update_or_create(
        paper=paper,
        defaults={
            "is_original": is_original,
            "confidence": confidence,
            "classifier": classifier,
            "reason": reason,
        },
    )
    paper.is_original = is_original
    paper.classification_confidence = confidence
    paper.classification_reason = reason
    paper.ingest_status = "classified"
    paper.save(update_fields=[
        "is_original",
        "classification_confidence",
        "classification_reason",
        "ingest_status",
        "updated_at",
    ])


@shared_task(name="papers.tasks.fetch_fulltext_pending")
def fetch_fulltext_pending() -> dict:
    """Beat entrypoint — implemented in Task 27."""
    return {"queued": 0}


@shared_task(name="papers.tasks.fetch_fulltext")
def fetch_fulltext(pmid: int) -> str:
    """Implemented in Task 27."""
    raise NotImplementedError("Task 27")


@shared_task(name="papers.tasks.section_pending")
def section_pending() -> dict:
    """Beat entrypoint — implemented in Task 28."""
    return {"queued": 0}


@shared_task(name="papers.tasks.section_and_chunk")
def section_and_chunk(pmid: int) -> str:
    """Implemented in Task 28."""
    raise NotImplementedError("Task 28")
```

- [ ] **Step 4: Run tests**

```bash
poetry run pytest apps/papers/tests/test_classify_original.py -v
```

Expected:
```
8 passed
```

- [ ] **Step 5: Commit**

```bash
git add apps/papers/tasks.py apps/papers/tests/test_classify_original.py
git commit -m "feat(papers): add classify_original (rule-first + qwen3:8b LLM fallback)"
```

---

## Task 27: `papers.fetch_fulltext` task (TDD)

(per spec §4: "If pmcid: Europe PMC OAI-PMH → JATS XML to MinIO; else if open-access PDF discoverable: download → GROBID → TEI XML; else: abstract-only".)

**Files:**
- Create: `apps/papers/tests/test_fetch_fulltext.py`
- Modify: `apps/papers/tasks.py`

- [ ] **Step 1: Write failing tests in `apps/papers/tests/test_fetch_fulltext.py`**

```python
"""Tests for papers.tasks.fetch_fulltext."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from corpus.models import Paper
from papers.tasks import fetch_fulltext, fetch_fulltext_pending


@pytest.fixture(autouse=True)
def _eager(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True


def test_fetch_fulltext_pmc_path_writes_to_minio(db):
    p = Paper.objects.create(
        pmid=1, title="x", pmcid="PMC11000000",
        ingest_status="classified", is_original=True,
    )
    with patch("papers.tasks.EuropePmcClient") as EPC, \
         patch("papers.tasks.MinioClient") as MC:
        EPC.return_value.get_jats_for_pmcid.return_value = b"<article/>"
        fetch_fulltext.delay(1).get(timeout=2)
    p.refresh_from_db()
    assert p.full_text_status == "pmc_jats"
    assert p.fulltext_s3_key.startswith("papers/")
    MC.return_value.put_object.assert_called_once()


def test_fetch_fulltext_no_pmcid_marks_abstract_only(db):
    p = Paper.objects.create(
        pmid=2, title="x", pmcid="",
        ingest_status="classified", is_original=True,
    )
    with patch("papers.tasks.EuropePmcClient"), patch("papers.tasks.MinioClient"):
        fetch_fulltext.delay(2).get(timeout=2)
    p.refresh_from_db()
    assert p.full_text_status == "abstract_only"


def test_fetch_fulltext_europepmc_not_found_falls_to_abstract(db):
    p = Paper.objects.create(
        pmid=3, title="x", pmcid="PMC99999999",
        ingest_status="classified", is_original=True,
    )
    from corpus.clients.europepmc import EuropePmcNotFound
    with patch("papers.tasks.EuropePmcClient") as EPC, \
         patch("papers.tasks.MinioClient"):
        EPC.return_value.get_jats_for_pmcid.side_effect = EuropePmcNotFound("PMC99999999")
        fetch_fulltext.delay(3).get(timeout=2)
    p.refresh_from_db()
    assert p.full_text_status == "abstract_only"


def test_fetch_fulltext_advances_ingest_status_to_fetched(db):
    p = Paper.objects.create(
        pmid=4, title="x", pmcid="PMC1",
        ingest_status="classified", is_original=True,
    )
    with patch("papers.tasks.EuropePmcClient") as EPC, \
         patch("papers.tasks.MinioClient"):
        EPC.return_value.get_jats_for_pmcid.return_value = b"<article/>"
        fetch_fulltext.delay(4).get(timeout=2)
    p.refresh_from_db()
    assert p.ingest_status == "fetched"


def test_fetch_fulltext_idempotent(db):
    p = Paper.objects.create(
        pmid=5, title="x", pmcid="PMC1",
        ingest_status="fetched", full_text_status="pmc_jats",
        fulltext_s3_key="papers/0000/5.xml", is_original=True,
    )
    with patch("papers.tasks.EuropePmcClient") as EPC:
        fetch_fulltext.delay(5).get(timeout=2)
    EPC.return_value.get_jats_for_pmcid.assert_not_called()


def test_fetch_fulltext_pending_skips_non_original(db):
    Paper.objects.create(
        pmid=10, title="x", pmcid="PMC1",
        ingest_status="classified", is_original=False,  # not original — skip
    )
    Paper.objects.create(
        pmid=11, title="y", pmcid="PMC2",
        ingest_status="classified", is_original=True,
    )
    with patch("papers.tasks.fetch_fulltext.delay") as mock_enq:
        fetch_fulltext_pending.delay().get(timeout=2)
    enqueued = {c.args[0] for c in mock_enq.call_args_list}
    assert 11 in enqueued
    assert 10 not in enqueued
```

- [ ] **Step 2: Run failing tests**

```bash
poetry run pytest apps/papers/tests/test_fetch_fulltext.py -v
```

Expected: tests fail because `fetch_fulltext` raises NotImplementedError.

- [ ] **Step 3: Implement `fetch_fulltext` in `apps/papers/tasks.py`**

Add to the top of `papers/tasks.py`:

```python
from corpus.clients.europepmc import EuropePmcClient, EuropePmcNotFound
from core.minio_client import MinioClient, paper_object_key
```

Replace `fetch_fulltext_pending` and `fetch_fulltext` bodies with:

```python
@shared_task(name="papers.tasks.fetch_fulltext_pending")
def fetch_fulltext_pending() -> dict:
    """Beat entrypoint — enqueue fetch_fulltext for classified originals."""
    queued = 0
    for pmid in (
        Paper.objects
        .filter(ingest_status="classified", is_original=True, full_text_status="none")
        .values_list("pmid", flat=True)
    ):
        fetch_fulltext.delay(pmid)
        queued += 1
    return {"queued": queued}


@shared_task(name="papers.tasks.fetch_fulltext")
def fetch_fulltext(pmid: int) -> str:
    paper = Paper.objects.get(pmid=pmid)
    if paper.full_text_status in {"pmc_jats", "grobid_tei"}:
        return "already_fetched"

    if not paper.pmcid:
        paper.full_text_status = "abstract_only"
        paper.ingest_status = "fetched"
        paper.save(update_fields=["full_text_status", "ingest_status", "updated_at"])
        section_and_chunk.delay(pmid)
        return "abstract_only"

    try:
        epc = EuropePmcClient()
        xml = epc.get_jats_for_pmcid(paper.pmcid)
    except EuropePmcNotFound:
        paper.full_text_status = "abstract_only"
        paper.ingest_status = "fetched"
        paper.fulltext_fetch_error = "europepmc:idDoesNotExist"
        paper.save(update_fields=[
            "full_text_status", "ingest_status", "fulltext_fetch_error", "updated_at"
        ])
        section_and_chunk.delay(pmid)
        return "abstract_only"
    except Exception as exc:
        paper.full_text_status = "fetch_failed"
        paper.fulltext_fetch_error = str(exc)[:4000]
        paper.save(update_fields=["full_text_status", "fulltext_fetch_error", "updated_at"])
        raise

    key = paper_object_key(pmid, "xml")
    minio = MinioClient()
    minio.put_object(
        bucket=settings.MINIO_BUCKET_PAPERS,
        key=key,
        body=xml,
        content_type="application/xml",
    )
    paper.fulltext_s3_key = key
    paper.full_text_status = "pmc_jats"
    paper.fulltext_fetch_error = ""
    paper.ingest_status = "fetched"
    paper.save(update_fields=[
        "fulltext_s3_key",
        "full_text_status",
        "fulltext_fetch_error",
        "ingest_status",
        "updated_at",
    ])
    section_and_chunk.delay(pmid)
    return "pmc_jats"
```

- [ ] **Step 4: Run tests**

```bash
poetry run pytest apps/papers/tests/test_fetch_fulltext.py -v
```

Expected:
```
6 passed
```

- [ ] **Step 5: Commit**

```bash
git add apps/papers/tasks.py apps/papers/tests/test_fetch_fulltext.py
git commit -m "feat(papers): add fetch_fulltext (Europe PMC JATS to MinIO + abstract fallback)"
```

---

## Task 28: `papers.section_and_chunk` task (TDD)

(per spec §4: "Parse XML → map section types to DoCO IRIs. Keep doco:Results sections (plus doco:Conclusions tagged as aux). Split each Results section into chunks of ≤ 1800 tokens, 200-token overlap, sentence-boundary-aware. Bulk INSERT Section + Chunk rows.")

**Files:**
- Create: `apps/papers/tests/test_section_and_chunk.py`
- Modify: `apps/papers/tasks.py`

- [ ] **Step 1: Write failing tests in `apps/papers/tests/test_section_and_chunk.py`**

```python
"""Tests for papers.tasks.section_and_chunk."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from corpus.models import Paper
from papers.models import Chunk, Section
from papers.tasks import section_and_chunk, section_pending

FIXTURE = Path(__file__).parent / "fixtures" / "sample_jats.xml"


@pytest.fixture(autouse=True)
def _eager(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True


def test_section_and_chunk_parses_jats_from_minio(db):
    p = Paper.objects.create(
        pmid=1, title="x", pmcid="PMC1",
        ingest_status="fetched", full_text_status="pmc_jats",
        fulltext_s3_key="papers/0000/1.xml", is_original=True,
    )
    with patch("papers.tasks.MinioClient") as MC:
        MC.return_value.get_object.return_value = FIXTURE.read_bytes()
        section_and_chunk.delay(1).get(timeout=2)
    p.refresh_from_db()
    assert p.ingest_status == "chunked"
    sections = list(Section.objects.filter(paper=p))
    assert any(s.doco_type == "Results" for s in sections)
    assert any(s.doco_type == "Introduction" for s in sections)


def test_section_and_chunk_only_creates_chunks_for_results(db):
    p = Paper.objects.create(
        pmid=2, title="x", pmcid="PMC2",
        ingest_status="fetched", full_text_status="pmc_jats",
        fulltext_s3_key="papers/0000/2.xml", is_original=True,
    )
    with patch("papers.tasks.MinioClient") as MC:
        MC.return_value.get_object.return_value = FIXTURE.read_bytes()
        section_and_chunk.delay(2).get(timeout=2)
    chunked_section_types = {
        c.section.doco_type for c in Chunk.objects.filter(paper=p)
    }
    assert "Results" in chunked_section_types
    # Spec §4 says keep Results AND Conclusions (as aux); allow both.
    assert chunked_section_types <= {"Results", "Conclusion"}


def test_section_and_chunk_abstract_only_uses_abstract(db):
    p = Paper.objects.create(
        pmid=3,
        title="A study",
        abstract="HIF1A upregulated in disc cells under hypoxia.",
        ingest_status="fetched",
        full_text_status="abstract_only",
        is_original=True,
    )
    section_and_chunk.delay(3).get(timeout=2)
    p.refresh_from_db()
    assert p.ingest_status == "chunked"
    sections = list(Section.objects.filter(paper=p))
    assert len(sections) == 1
    assert sections[0].doco_type == "Abstract"
    assert Chunk.objects.filter(paper=p).count() >= 1


def test_section_and_chunk_idempotent(db):
    p = Paper.objects.create(
        pmid=4, title="x", abstract="data",
        ingest_status="chunked", full_text_status="abstract_only",
        is_original=True,
    )
    section_and_chunk.delay(4).get(timeout=2)
    # Should not re-process; no sections created
    assert Section.objects.filter(paper=p).count() == 0


def test_section_pending_picks_up_fetched_papers(db):
    Paper.objects.create(
        pmid=5, title="x", ingest_status="fetched",
        full_text_status="abstract_only", is_original=True,
    )
    Paper.objects.create(  # not eligible — still classified
        pmid=6, title="y", ingest_status="classified", is_original=True,
    )
    with patch("papers.tasks.section_and_chunk.delay") as mock_enq:
        section_pending.delay().get(timeout=2)
    enqueued = {c.args[0] for c in mock_enq.call_args_list}
    assert 5 in enqueued
    assert 6 not in enqueued
```

- [ ] **Step 2: Run failing tests**

```bash
poetry run pytest apps/papers/tests/test_section_and_chunk.py -v
```

Expected: tests fail because `section_and_chunk` raises NotImplementedError.

- [ ] **Step 3: Implement `section_and_chunk` in `apps/papers/tasks.py`**

Add to imports of `papers/tasks.py`:

```python
from django.db import transaction

from papers.chunking import chunk_text
from papers.doco import DOCO_IRI_PREFIX
from papers.jats import parse_jats
from papers.models import Chunk, Section
```

Replace `section_pending` and `section_and_chunk` bodies with:

```python
# Sections we slice into chunks. Results is primary; Conclusions is aux.
CHUNKABLE_DOCO_LABELS = {"Results", "Conclusion", "Abstract"}


@shared_task(name="papers.tasks.section_pending")
def section_pending() -> dict:
    queued = 0
    for pmid in (
        Paper.objects
        .filter(ingest_status="fetched", is_original=True)
        .values_list("pmid", flat=True)
    ):
        section_and_chunk.delay(pmid)
        queued += 1
    return {"queued": queued}


@shared_task(name="papers.tasks.section_and_chunk")
def section_and_chunk(pmid: int) -> str:
    paper = Paper.objects.get(pmid=pmid)
    if paper.ingest_status == "chunked":
        return "already_chunked"

    if paper.full_text_status == "abstract_only":
        return _section_abstract_only(paper)

    if paper.full_text_status == "pmc_jats" and paper.fulltext_s3_key:
        return _section_from_jats(paper)

    if paper.full_text_status == "grobid_tei" and paper.fulltext_s3_key:
        # Phase 1 punts on TEI parsing; treat like abstract until Phase 2
        # adds the TEI parser. Mark chunked with abstract for now.
        return _section_abstract_only(paper)

    # Nothing usable — mark chunked-empty so we don't loop.
    paper.ingest_status = "chunked"
    paper.save(update_fields=["ingest_status", "updated_at"])
    return "no_content"


@transaction.atomic
def _section_abstract_only(paper: Paper) -> str:
    text = paper.abstract or ""
    if not text.strip():
        paper.ingest_status = "chunked"
        paper.save(update_fields=["ingest_status", "updated_at"])
        return "empty_abstract"
    section = Section.objects.create(
        paper=paper,
        order_index=0,
        doco_type="Abstract",
        doco_iri=f"{DOCO_IRI_PREFIX}Abstract",
        heading="Abstract",
        body_text=text,
        token_count=len(text.split()),
    )
    _persist_chunks(section, text)
    paper.ingest_status = "chunked"
    paper.save(update_fields=["ingest_status", "updated_at"])
    return "chunked_abstract"


@transaction.atomic
def _section_from_jats(paper: Paper) -> str:
    minio = MinioClient()
    xml = minio.get_object(
        bucket=settings.MINIO_BUCKET_PAPERS,
        key=paper.fulltext_s3_key,
    )
    parsed = parse_jats(xml)
    if not parsed:
        return _section_abstract_only(paper)

    for ps in parsed:
        section = Section.objects.create(
            paper=paper,
            order_index=ps.order_index,
            doco_type=ps.doco_label,
            doco_iri=ps.doco_iri,
            heading=ps.heading,
            body_text=ps.body_text,
            token_count=len(ps.body_text.split()),
        )
        if ps.doco_label in CHUNKABLE_DOCO_LABELS:
            _persist_chunks(section, ps.body_text)
    paper.ingest_status = "chunked"
    paper.save(update_fields=["ingest_status", "updated_at"])
    return "chunked_jats"


def _persist_chunks(section: Section, text: str) -> int:
    records = chunk_text(text, max_tokens=1800, overlap_tokens=200)
    objs = [
        Chunk(
            section=section,
            paper_id=section.paper_id,
            chunk_index=r.chunk_index,
            text=r.text,
            token_count=r.token_count,
            char_offset_start=r.char_offset_start,
            char_offset_end=r.char_offset_end,
        )
        for r in records
    ]
    Chunk.objects.bulk_create(objs)
    return len(objs)
```

- [ ] **Step 4: Run tests**

```bash
poetry run pytest apps/papers/tests/test_section_and_chunk.py -v
```

Expected:
```
5 passed
```

- [ ] **Step 5: Commit**

```bash
git add apps/papers/tasks.py apps/papers/tests/test_section_and_chunk.py
git commit -m "feat(papers): add section_and_chunk (JATS + abstract paths via MinIO)"
```

---

## Task 29: `corpus.triage_relevance` two-pass task (TDD)

(per spec §5: cheap pass on `keywords` + PubTator entities; expensive LLM pass on qwen3:8b for surviving candidates. Result: many-to-many PaperRelevance.)

**Files:**
- Create: `apps/corpus/tests/test_triage_relevance.py`
- Modify: `apps/corpus/tasks.py`

- [ ] **Step 1: Write failing tests in `apps/corpus/tests/test_triage_relevance.py`**

```python
"""Tests for corpus.tasks.triage_relevance_cheap and _llm."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from corpus.models import Paper, PaperRelevance
from corpus.tasks import (
    triage_pending,
    triage_relevance_cheap,
    triage_relevance_llm,
)
from networks.models import Network


@pytest.fixture(autouse=True)
def _eager(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True


@pytest.fixture
def nfkb(db):
    return Network.objects.create(
        code="nfkb_axis",
        category="I",
        title="NF-κB Axis",
        keywords=["NF-kB", "RELA", "p65"],
        root_entity_aliases=["NFKB1", "RELA"],
    )


@pytest.fixture
def mech(db):
    return Network.objects.create(
        code="mechano_piezo",
        category="VIII",
        title="Piezo channels",
        keywords=["Piezo1", "Piezo2", "mechanosensitive"],
        root_entity_aliases=["PIEZO1", "PIEZO2"],
    )


def test_cheap_pass_matches_keyword_in_abstract(db, nfkb):
    p = Paper.objects.create(
        pmid=1, title="x",
        abstract="NF-kB upregulated in NP cells.",
        ingest_status="chunked", is_original=True,
    )
    triage_relevance_cheap.delay(1).get(timeout=2)
    rel = PaperRelevance.objects.filter(paper=p, network=nfkb).first()
    assert rel is not None
    assert rel.classified_by == "cheap_keyword"
    assert rel.score >= 0.5


def test_cheap_pass_matches_pubtator_root_alias(db, nfkb):
    p = Paper.objects.create(
        pmid=2, title="x", abstract="no mention",
        pubtator_entities=[{"text": "RELA", "type": "Gene"}],
        ingest_status="chunked", is_original=True,
    )
    triage_relevance_cheap.delay(2).get(timeout=2)
    rel = PaperRelevance.objects.filter(paper=p, network=nfkb).first()
    assert rel is not None
    assert rel.classified_by == "cheap_pubtator"


def test_cheap_pass_no_match_skips_llm(db, nfkb, mech):
    p = Paper.objects.create(
        pmid=3, title="x", abstract="some unrelated topic",
        pubtator_entities=[],
        ingest_status="chunked", is_original=True,
    )
    with patch("corpus.tasks.triage_relevance_llm.delay") as mock_llm:
        triage_relevance_cheap.delay(3).get(timeout=2)
    mock_llm.assert_not_called()
    assert PaperRelevance.objects.filter(paper=p).count() == 0


def test_cheap_pass_enqueues_llm_for_borderline(db, nfkb):
    # When the cheap pass matches a keyword AND we want a second check,
    # the LLM pass refines. (Implementation: any cheap match enqueues LLM
    # to refine to a confidence score.)
    p = Paper.objects.create(
        pmid=4, title="x", abstract="NF-kB and RELA are upregulated.",
        ingest_status="chunked", is_original=True,
    )
    with patch("corpus.tasks.triage_relevance_llm.delay") as mock_llm:
        triage_relevance_cheap.delay(4).get(timeout=2)
    enqueued = {(c.args[0], c.args[1]) for c in mock_llm.call_args_list}
    assert (4, nfkb.pk) in enqueued


def test_cheap_pass_iterates_all_active_networks(db, nfkb, mech):
    p = Paper.objects.create(
        pmid=5, title="x",
        abstract="Piezo1 channels respond to compression in NP cells.",
        pubtator_entities=[{"text": "PIEZO1", "type": "Gene"}],
        ingest_status="chunked", is_original=True,
    )
    triage_relevance_cheap.delay(5).get(timeout=2)
    matched_codes = {
        r.network.code for r in PaperRelevance.objects.filter(paper=p)
    }
    assert "mechano_piezo" in matched_codes
    assert "nfkb_axis" not in matched_codes  # no NF-kB keyword


def test_llm_pass_updates_relevance_score(db, nfkb):
    p = Paper.objects.create(
        pmid=6, title="x", abstract="NF-kB and RELA are upregulated.",
        ingest_status="chunked", is_original=True,
    )
    PaperRelevance.objects.create(
        paper=p, network=nfkb, score=0.5, classified_by="cheap_keyword"
    )
    fake_resp = {"response": json.dumps({
        "relevant": True, "confidence": 0.92, "reason": "primary IL-1 study"
    })}
    with patch("corpus.tasks.OllamaClient") as M:
        M.return_value.generate.return_value = fake_resp
        triage_relevance_llm.delay(6, nfkb.pk).get(timeout=2)
    rel = PaperRelevance.objects.get(paper=p, network=nfkb)
    assert rel.classified_by == "llm:qwen3:8b"
    assert rel.score == pytest.approx(0.92, abs=0.01)


def test_llm_pass_irrelevant_downgrades_score(db, nfkb):
    p = Paper.objects.create(
        pmid=7, title="x", abstract="NF-kB mention in a different tissue.",
        ingest_status="chunked", is_original=True,
    )
    PaperRelevance.objects.create(
        paper=p, network=nfkb, score=0.5, classified_by="cheap_keyword"
    )
    fake_resp = {"response": json.dumps({
        "relevant": False, "confidence": 0.85, "reason": "pancreatic cells, off-tissue"
    })}
    with patch("corpus.tasks.OllamaClient") as M:
        M.return_value.generate.return_value = fake_resp
        triage_relevance_llm.delay(7, nfkb.pk).get(timeout=2)
    rel = PaperRelevance.objects.get(paper=p, network=nfkb)
    assert rel.score < 0.5


def test_triage_pending_enqueues_chunked_papers(db, nfkb):
    Paper.objects.create(pmid=8, title="x", ingest_status="chunked", is_original=True)
    Paper.objects.create(pmid=9, title="y", ingest_status="fetched", is_original=True)
    with patch("corpus.tasks.triage_relevance_cheap.delay") as mock_enq:
        triage_pending.delay().get(timeout=2)
    enqueued = {c.args[0] for c in mock_enq.call_args_list}
    assert 8 in enqueued
    assert 9 not in enqueued
```

- [ ] **Step 2: Run failing tests**

```bash
poetry run pytest apps/corpus/tests/test_triage_relevance.py -v
```

Expected: tests fail because the triage tasks still return empty placeholders.

- [ ] **Step 3: Implement triage in `apps/corpus/tasks.py`**

Replace the three placeholder triage tasks with full implementations. Add imports at top of `corpus/tasks.py`:

```python
import json

from core.ollama import OllamaClient
from corpus.models import PaperRelevance
from networks.models import Network
```

Then:

```python
TRIAGE_PROMPT = """You are deciding whether a biomedical paper provides
primary experimental evidence relevant to a specific regulatory network
of the intervertebral disc.

Network: {network_title}
Network description: {network_description}

Paper title: {title}
Paper abstract: {abstract}

Reply ONLY with a JSON object:
{{"relevant": true|false, "confidence": 0.0..1.0, "reason": "short"}}
"""

TRIAGE_SCHEMA = {
    "type": "object",
    "properties": {
        "relevant": {"type": "boolean"},
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["relevant", "confidence"],
}


@shared_task(name="corpus.tasks.triage_pending")
def triage_pending() -> dict:
    """Beat entrypoint — sweep chunked papers without a relevance record."""
    queued = 0
    # An "untriaged" paper has zero PaperRelevance rows.
    qs = (
        Paper.objects
        .filter(ingest_status="chunked", is_original=True)
        .exclude(relevances__isnull=False)
        .values_list("pmid", flat=True)
    )
    for pmid in qs:
        triage_relevance_cheap.delay(pmid)
        queued += 1
    return {"queued": queued}


@shared_task(name="corpus.tasks.triage_relevance_cheap")
def triage_relevance_cheap(paper_id: int) -> dict:
    """Cheap pass: keyword + PubTator alias matching against every active network."""
    paper = Paper.objects.get(pmid=paper_id)
    haystack = f"{paper.title}\n{paper.abstract or ''}".lower()
    pubtator_texts = {
        (e.get("text") or "").upper() for e in (paper.pubtator_entities or [])
    }
    matched = 0
    for network in Network.objects.filter(is_active=True):
        keyword_hit = any(
            kw.lower() in haystack for kw in (network.keywords or [])
        )
        alias_hit = any(
            alias.upper() in pubtator_texts for alias in (network.root_entity_aliases or [])
        )
        if not keyword_hit and not alias_hit:
            continue
        classified_by = "cheap_keyword" if keyword_hit else "cheap_pubtator"
        PaperRelevance.objects.update_or_create(
            paper=paper,
            network=network,
            defaults={
                "score": 0.5,
                "classified_by": classified_by,
                "reason": (
                    f"keyword_hit={keyword_hit}, alias_hit={alias_hit}"
                ),
            },
        )
        triage_relevance_llm.delay(paper_id, network.pk)
        matched += 1
    return {"matched_networks": matched}


@shared_task(
    name="corpus.tasks.triage_relevance_llm",
    bind=True,
    autoretry_for=(RateLimitExceeded,),
    retry_backoff=True,
    max_retries=3,
)
def triage_relevance_llm(self, paper_id: int, network_id: int) -> dict:
    """Expensive pass: refine cheap-pass score using qwen3:8b verdict."""
    paper = Paper.objects.get(pmid=paper_id)
    network = Network.objects.get(pk=network_id)
    prompt = TRIAGE_PROMPT.format(
        network_title=network.title,
        network_description=(network.description or "")[:500],
        title=paper.title[:500],
        abstract=(paper.abstract or "")[:3000],
    )
    relevant = True
    confidence = 0.5
    reason = ""
    try:
        client = OllamaClient()
        raw = client.generate(
            model="qwen3:8b",
            prompt=prompt,
            format=TRIAGE_SCHEMA,
            options={"temperature": 0.0},
        )
        payload = json.loads(raw.get("response", ""))
        relevant = bool(payload["relevant"])
        confidence = float(payload.get("confidence", 0.5))
        reason = str(payload.get("reason", ""))[:500]
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
        logger.warning("triage LLM fallback for paper=%s network=%s: %s",
                       paper_id, network_id, exc)
        confidence = 0.4
        reason = f"llm_fallback: {exc}"

    final_score = confidence if relevant else (1.0 - confidence)
    PaperRelevance.objects.update_or_create(
        paper=paper,
        network=network,
        defaults={
            "score": final_score,
            "classified_by": "llm:qwen3:8b",
            "reason": reason,
        },
    )
    return {"score": final_score, "relevant": relevant}
```

- [ ] **Step 4: Run tests**

```bash
poetry run pytest apps/corpus/tests/test_triage_relevance.py -v
```

Expected:
```
8 passed
```

- [ ] **Step 5: Commit**

```bash
git add apps/corpus/tasks.py apps/corpus/tests/test_triage_relevance.py
git commit -m "feat(corpus): add two-pass relevance triage (cheap + qwen3 LLM refine)"
```

---

## Task 30: `/corpus/export.csv` view (TDD)

(per spec §5: "/corpus/export.csv?format=full — every paper with metadata + classifier + full-text flag; /corpus/export.csv?network=nfkb_axis — network-filtered slice".)

**Files:**
- Create: `apps/corpus/tests/test_views.py`
- Create: `apps/corpus/views.py`
- Create: `apps/corpus/urls.py`
- Modify: `interactome/urls.py`

- [ ] **Step 1: Write failing tests in `apps/corpus/tests/test_views.py`**

```python
"""Tests for corpus.views.export_csv."""
from __future__ import annotations

import csv
import io
from datetime import date

import pytest
from django.test import Client

from corpus.models import Paper, PaperRelevance
from networks.models import Network


@pytest.fixture
def client():
    return Client(HTTP_REMOTE_USER="fchemorion")


@pytest.fixture
def seed_corpus(db):
    n1 = Network.objects.create(code="nfkb_axis", category="I", title="NF-κB Axis")
    n2 = Network.objects.create(code="mechano_piezo", category="VIII", title="Piezo")
    p1 = Paper.objects.create(
        pmid=1, title="NF-kB paper", abstract="a",
        publication_date=date(2024, 5, 1),
        is_original=True, full_text_status="pmc_jats",
        ingest_status="chunked",
    )
    p2 = Paper.objects.create(
        pmid=2, title="Piezo paper", abstract="b",
        publication_date=date(2024, 4, 1),
        is_original=True, full_text_status="abstract_only",
        ingest_status="chunked",
    )
    p3 = Paper.objects.create(
        pmid=3, title="Review", abstract="c",
        is_original=False, full_text_status="none",
        ingest_status="classified",
    )
    PaperRelevance.objects.create(paper=p1, network=n1, score=0.92, classified_by="llm:qwen3:8b")
    PaperRelevance.objects.create(paper=p2, network=n2, score=0.85, classified_by="llm:qwen3:8b")
    PaperRelevance.objects.create(paper=p1, network=n2, score=0.10, classified_by="llm:qwen3:8b")
    return n1, n2, p1, p2, p3


def test_export_csv_returns_csv_content_type(db, client, seed_corpus):
    resp = client.get("/corpus/export.csv")
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("text/csv")


def test_export_csv_default_returns_all_papers(db, client, seed_corpus):
    resp = client.get("/corpus/export.csv")
    rows = list(csv.DictReader(io.StringIO(resp.content.decode())))
    pmids = {int(r["pmid"]) for r in rows}
    assert pmids == {1, 2, 3}


def test_export_csv_full_format_includes_classifier_and_fulltext(db, client, seed_corpus):
    resp = client.get("/corpus/export.csv?format=full")
    rows = list(csv.DictReader(io.StringIO(resp.content.decode())))
    headers = rows[0].keys()
    assert "is_original" in headers
    assert "full_text_status" in headers
    assert "publication_types" in headers
    assert "mesh_terms" in headers


def test_export_csv_network_filter(db, client, seed_corpus):
    resp = client.get("/corpus/export.csv?network=nfkb_axis")
    rows = list(csv.DictReader(io.StringIO(resp.content.decode())))
    pmids = {int(r["pmid"]) for r in rows}
    # Only papers with relevance > 0.5 for the requested network.
    assert pmids == {1}


def test_export_csv_unknown_network_returns_400(db, client, seed_corpus):
    resp = client.get("/corpus/export.csv?network=does_not_exist")
    assert resp.status_code == 400


def test_export_csv_threshold_query_param(db, client, seed_corpus):
    resp = client.get("/corpus/export.csv?network=mechano_piezo&threshold=0.05")
    rows = list(csv.DictReader(io.StringIO(resp.content.decode())))
    pmids = {int(r["pmid"]) for r in rows}
    assert pmids == {1, 2}  # both relevances above 0.05


def test_export_csv_filename_header(db, client, seed_corpus):
    resp = client.get("/corpus/export.csv")
    assert "attachment" in resp["Content-Disposition"]
    assert ".csv" in resp["Content-Disposition"]


def test_export_csv_network_filename_includes_code(db, client, seed_corpus):
    resp = client.get("/corpus/export.csv?network=nfkb_axis")
    assert "nfkb_axis" in resp["Content-Disposition"]
```

- [ ] **Step 2: Run failing tests**

```bash
poetry run pytest apps/corpus/tests/test_views.py -v
```

Expected:
```
... 404 at /corpus/export.csv
```

- [ ] **Step 3: Implement `apps/corpus/views.py`**

```python
"""corpus views — export.csv, stats, paper detail."""
from __future__ import annotations

import csv
import json
from typing import Iterable

from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest

from corpus.models import Paper, PaperRelevance
from networks.models import Network


def export_csv(request: HttpRequest) -> HttpResponse:
    """Stream the corpus as CSV.

    Query params:
      - ``format=full`` — emit the wide column set including is_original,
        full_text_status, publication_types, mesh_terms, doi, pmcid.
      - ``network=<code>`` — restrict to papers with PaperRelevance for
        the named network above ``threshold``.
      - ``threshold=<float>`` — default 0.5 (per spec §5).
    """
    full = request.GET.get("format") == "full"
    network_code = request.GET.get("network", "").strip()
    try:
        threshold = float(request.GET.get("threshold", "0.5"))
    except ValueError:
        return HttpResponseBadRequest("threshold must be a float")

    if network_code:
        try:
            network = Network.objects.get(code=network_code)
        except Network.DoesNotExist:
            return HttpResponseBadRequest(f"unknown network code: {network_code}")
        pmids = PaperRelevance.objects.filter(
            network=network, score__gte=threshold
        ).values_list("paper_id", flat=True)
        qs = Paper.objects.filter(pmid__in=pmids).order_by("pmid")
        filename = f"corpus_{network_code}.csv"
    else:
        qs = Paper.objects.all().order_by("pmid")
        filename = "corpus_full.csv" if full else "corpus.csv"

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)
    writer.writerow(_csv_headers(full=full))
    for paper in qs.iterator(chunk_size=500):
        writer.writerow(_csv_row(paper, full=full))
    return response


def _csv_headers(*, full: bool) -> list[str]:
    base = ["pmid", "title", "journal", "publication_date", "entrez_date"]
    if not full:
        return base
    return base + [
        "doi", "pmcid", "is_original", "classification_confidence",
        "full_text_status", "publication_types", "mesh_terms",
        "ingest_status",
    ]


def _csv_row(paper: Paper, *, full: bool) -> list:
    base = [
        paper.pmid,
        paper.title,
        paper.journal,
        paper.publication_date.isoformat() if paper.publication_date else "",
        paper.entrez_date.isoformat() if paper.entrez_date else "",
    ]
    if not full:
        return base
    return base + [
        paper.doi,
        paper.pmcid,
        "" if paper.is_original is None else str(paper.is_original),
        "" if paper.classification_confidence is None
            else f"{paper.classification_confidence:.3f}",
        paper.full_text_status,
        json.dumps(paper.publication_types or []),
        json.dumps(paper.mesh_terms or []),
        paper.ingest_status,
    ]
```

- [ ] **Step 4: Create `apps/corpus/urls.py`**

```python
"""corpus URL routes."""
from __future__ import annotations

from django.urls import path

from corpus import views

app_name = "corpus"

urlpatterns = [
    path("corpus/export.csv", views.export_csv, name="export_csv"),
]
```

- [ ] **Step 5: Wire into `interactome/urls.py`**

Replace the file contents with:

```python
"""Top-level URL conf. Each app contributes via its own ``urls.py``."""
from __future__ import annotations

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("core.urls")),
    path("", include("corpus.urls")),
    path("", include("dashboard.urls")),
]
```

- [ ] **Step 6: Run tests**

```bash
poetry run pytest apps/corpus/tests/test_views.py -v
```

Expected:
```
8 passed
```

- [ ] **Step 7: Commit**

```bash
git add apps/corpus/views.py apps/corpus/urls.py interactome/urls.py apps/corpus/tests/test_views.py
git commit -m "feat(corpus): add /corpus/export.csv view with format and network filters"
```

---

## Task 31: `/corpus/stats` and `/corpus/paper/<pmid>` views (TDD)

(per spec §5: "/corpus/stats — counts by year, journal, MeSH, full-text coverage, original-vs-review; /corpus/paper/<pmid> — single-paper view".)

**Files:**
- Create: `apps/dashboard/tests/conftest.py`
- Create: `apps/dashboard/tests/test_stats_view.py`
- Create: `apps/dashboard/tests/test_paper_detail_view.py`
- Create: `apps/dashboard/views.py`
- Create: `apps/dashboard/urls.py`
- Create: `apps/dashboard/templates/dashboard/base.html`
- Create: `apps/dashboard/templates/dashboard/stats.html`
- Create: `apps/dashboard/templates/dashboard/paper_detail.html`

- [ ] **Step 1: Create `apps/dashboard/tests/conftest.py`**

```python
"""Shared pytest fixtures for the dashboard app."""
from __future__ import annotations

from datetime import date

import pytest
from django.test import Client

from corpus.models import Paper, PaperRelevance
from networks.models import Network


@pytest.fixture
def client():
    return Client(HTTP_REMOTE_USER="fchemorion")


@pytest.fixture
def seed(db):
    n = Network.objects.create(code="nfkb_axis", category="I", title="NF-κB Axis")
    Paper.objects.create(
        pmid=1, title="2024 paper A", journal="Spine",
        publication_date=date(2024, 1, 1),
        is_original=True, full_text_status="pmc_jats",
        mesh_terms=["Intervertebral Disc", "Hypoxia"],
        ingest_status="chunked",
    )
    Paper.objects.create(
        pmid=2, title="2024 paper B", journal="JOR",
        publication_date=date(2024, 6, 1),
        is_original=True, full_text_status="abstract_only",
        mesh_terms=["Intervertebral Disc"],
        ingest_status="chunked",
    )
    Paper.objects.create(
        pmid=3, title="2023 review", journal="Spine",
        publication_date=date(2023, 1, 1),
        is_original=False, full_text_status="none",
        ingest_status="classified",
    )
    PaperRelevance.objects.create(paper_id=1, network=n, score=0.9, classified_by="llm:qwen3:8b")
    return n
```

- [ ] **Step 2: Write failing tests in `apps/dashboard/tests/test_stats_view.py`**

```python
"""Tests for /corpus/stats."""
from __future__ import annotations


def test_stats_view_returns_200(db, client, seed):
    resp = client.get("/corpus/stats")
    assert resp.status_code == 200


def test_stats_view_total_papers(db, client, seed):
    resp = client.get("/corpus/stats")
    assert b"3" in resp.content  # 3 total papers


def test_stats_view_original_vs_review_breakdown(db, client, seed):
    resp = client.get("/corpus/stats")
    body = resp.content.decode()
    assert "Original" in body or "original" in body
    assert "Review" in body or "review" in body


def test_stats_view_full_text_coverage(db, client, seed):
    resp = client.get("/corpus/stats")
    body = resp.content.decode()
    assert "pmc_jats" in body or "Full-text" in body or "full-text" in body


def test_stats_view_by_year(db, client, seed):
    resp = client.get("/corpus/stats")
    body = resp.content.decode()
    assert "2024" in body
    assert "2023" in body


def test_stats_view_by_journal(db, client, seed):
    resp = client.get("/corpus/stats")
    body = resp.content.decode()
    assert "Spine" in body
    assert "JOR" in body
```

- [ ] **Step 3: Write failing tests in `apps/dashboard/tests/test_paper_detail_view.py`**

```python
"""Tests for /corpus/paper/<pmid>."""
from __future__ import annotations


def test_paper_detail_returns_200_for_existing(db, client, seed):
    resp = client.get("/corpus/paper/1")
    assert resp.status_code == 200


def test_paper_detail_404_for_missing(db, client, seed):
    resp = client.get("/corpus/paper/99999")
    assert resp.status_code == 404


def test_paper_detail_shows_title(db, client, seed):
    resp = client.get("/corpus/paper/1")
    assert b"2024 paper A" in resp.content


def test_paper_detail_shows_relevances(db, client, seed):
    resp = client.get("/corpus/paper/1")
    body = resp.content.decode()
    assert "nfkb_axis" in body or "NF-κB" in body or "NF-kB" in body


def test_paper_detail_shows_full_text_status(db, client, seed):
    resp = client.get("/corpus/paper/1")
    body = resp.content.decode()
    assert "pmc_jats" in body or "Full-text" in body or "full-text" in body
```

- [ ] **Step 4: Run failing tests**

```bash
poetry run pytest apps/dashboard/tests/ -v
```

Expected: 404s and ImportErrors.

- [ ] **Step 5: Create `apps/dashboard/views.py`**

```python
"""Dashboard views — read-only stats and paper detail."""
from __future__ import annotations

from collections import Counter
from typing import Any

from django.db.models import Count
from django.db.models.functions import ExtractYear
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from corpus.models import Paper


def stats(request: HttpRequest) -> HttpResponse:
    total = Paper.objects.count()
    by_year = list(
        Paper.objects
        .exclude(publication_date__isnull=True)
        .annotate(year=ExtractYear("publication_date"))
        .values("year")
        .annotate(n=Count("pmid"))
        .order_by("-year")
    )
    by_journal = list(
        Paper.objects
        .exclude(journal="")
        .values("journal")
        .annotate(n=Count("pmid"))
        .order_by("-n")[:25]
    )
    fulltext_breakdown = list(
        Paper.objects.values("full_text_status").annotate(n=Count("pmid"))
    )
    original_breakdown = {
        "original": Paper.objects.filter(is_original=True).count(),
        "review_or_secondary": Paper.objects.filter(is_original=False).count(),
        "unclassified": Paper.objects.filter(is_original__isnull=True).count(),
    }
    mesh_counter: Counter[str] = Counter()
    for terms in Paper.objects.values_list("mesh_terms", flat=True):
        if terms:
            mesh_counter.update(terms)
    top_mesh = mesh_counter.most_common(25)

    context: dict[str, Any] = {
        "total": total,
        "by_year": by_year,
        "by_journal": by_journal,
        "fulltext_breakdown": fulltext_breakdown,
        "original_breakdown": original_breakdown,
        "top_mesh": top_mesh,
    }
    return render(request, "dashboard/stats.html", context)


def paper_detail(request: HttpRequest, pmid: int) -> HttpResponse:
    paper = get_object_or_404(Paper, pmid=pmid)
    relevances = list(
        paper.relevances.select_related("network").order_by("-score")
    )
    return render(
        request,
        "dashboard/paper_detail.html",
        {"paper": paper, "relevances": relevances},
    )
```

- [ ] **Step 6: Create `apps/dashboard/urls.py`**

```python
"""dashboard URL routes."""
from __future__ import annotations

from django.urls import path

from dashboard import views

app_name = "dashboard"

urlpatterns = [
    path("corpus/stats", views.stats, name="stats"),
    path("corpus/paper/<int:pmid>", views.paper_detail, name="paper_detail"),
]
```

- [ ] **Step 7: Create `apps/dashboard/templates/dashboard/base.html`**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>{% block title %}IVD Atlas{% endblock %}</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 1000px; margin: 2em auto; padding: 0 1em; }
    h1 { border-bottom: 1px solid #ccc; padding-bottom: .3em; }
    table { border-collapse: collapse; width: 100%; margin: 1em 0; }
    th, td { border-bottom: 1px solid #eee; padding: .4em .6em; text-align: left; }
    nav a { margin-right: 1em; }
  </style>
</head>
<body>
  <nav>
    <a href="/corpus/stats">Corpus stats</a>
    <a href="/corpus/export.csv">Export CSV</a>
  </nav>
  {% block content %}{% endblock %}
</body>
</html>
```

- [ ] **Step 8: Create `apps/dashboard/templates/dashboard/stats.html`**

```html
{% extends "dashboard/base.html" %}
{% block title %}Corpus stats — IVD Atlas{% endblock %}
{% block content %}
<h1>Corpus stats</h1>

<p><strong>Total papers:</strong> {{ total }}</p>

<h2>Original vs review (classification)</h2>
<table>
  <tr><th>Class</th><th>Count</th></tr>
  <tr><td>Original (primary research)</td><td>{{ original_breakdown.original }}</td></tr>
  <tr><td>Review or secondary</td><td>{{ original_breakdown.review_or_secondary }}</td></tr>
  <tr><td>Unclassified</td><td>{{ original_breakdown.unclassified }}</td></tr>
</table>

<h2>Full-text coverage</h2>
<table>
  <tr><th>Status</th><th>Count</th></tr>
  {% for row in fulltext_breakdown %}
    <tr><td>{{ row.full_text_status }}</td><td>{{ row.n }}</td></tr>
  {% endfor %}
</table>

<h2>By publication year</h2>
<table>
  <tr><th>Year</th><th>Papers</th></tr>
  {% for row in by_year %}
    <tr><td>{{ row.year }}</td><td>{{ row.n }}</td></tr>
  {% endfor %}
</table>

<h2>Top 25 journals</h2>
<table>
  <tr><th>Journal</th><th>Papers</th></tr>
  {% for row in by_journal %}
    <tr><td>{{ row.journal }}</td><td>{{ row.n }}</td></tr>
  {% endfor %}
</table>

<h2>Top 25 MeSH terms</h2>
<table>
  <tr><th>MeSH term</th><th>Papers</th></tr>
  {% for term, count in top_mesh %}
    <tr><td>{{ term }}</td><td>{{ count }}</td></tr>
  {% endfor %}
</table>
{% endblock %}
```

- [ ] **Step 9: Create `apps/dashboard/templates/dashboard/paper_detail.html`**

```html
{% extends "dashboard/base.html" %}
{% block title %}PMID {{ paper.pmid }} — IVD Atlas{% endblock %}
{% block content %}
<h1>{{ paper.title }}</h1>
<p>
  PMID <strong>{{ paper.pmid }}</strong>
  {% if paper.doi %}· DOI <code>{{ paper.doi }}</code>{% endif %}
  {% if paper.pmcid %}· PMC <code>{{ paper.pmcid }}</code>{% endif %}
</p>
<p><em>{{ paper.journal }}{% if paper.publication_date %}, {{ paper.publication_date|date:"Y-m-d" }}{% endif %}</em></p>

<h2>Status</h2>
<ul>
  <li>Ingest status: {{ paper.ingest_status }}</li>
  <li>Full-text status: {{ paper.full_text_status }}</li>
  <li>Is original:
    {% if paper.is_original is None %}unclassified
    {% else %}{{ paper.is_original|yesno:"yes,no" }}
      ({{ paper.classification_confidence|default:"" }})
    {% endif %}
  </li>
</ul>

<h2>Abstract</h2>
<p>{{ paper.abstract|default:"(none)" }}</p>

<h2>Network relevances</h2>
<table>
  <tr><th>Network</th><th>Score</th><th>Classified by</th></tr>
  {% for r in relevances %}
    <tr>
      <td>{{ r.network.code }} — {{ r.network.title }}</td>
      <td>{{ r.score|floatformat:3 }}</td>
      <td>{{ r.classified_by }}</td>
    </tr>
  {% empty %}
    <tr><td colspan="3"><em>No relevance records yet.</em></td></tr>
  {% endfor %}
</table>

<h2>MeSH terms</h2>
<ul>
  {% for term in paper.mesh_terms %}
    <li>{{ term }}</li>
  {% endfor %}
</ul>
{% endblock %}
```

- [ ] **Step 10: Run tests**

```bash
poetry run pytest apps/dashboard/tests/ -v
```

Expected:
```
11 passed
```

- [ ] **Step 11: Commit**

```bash
git add apps/dashboard/views.py apps/dashboard/urls.py apps/dashboard/templates apps/dashboard/tests
git commit -m "feat(dashboard): add /corpus/stats and /corpus/paper/<pmid> views"
```

---

## Task 32: Wire `worker_fast` into docker-compose and verify full stack

(per spec §6: "worker.fast_llm × 1, concurrency 2 — Handles: classify_original, per-network relevance triage".)

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add `worker_fast` service to `docker-compose.yml`**

After the existing `worker_io` block, insert:

```yaml
  worker_fast:
    image: interactome:dev
    restart: unless-stopped
    env_file: .env
    depends_on:
      web:
        condition: service_healthy
    command: celery -A interactome worker -Q q.fast -c 2 -n fast@%h -l info
```

- [ ] **Step 2: Verify the compose file is valid**

```bash
docker-compose config -q
```

Expected: exit code 0, no output.

- [ ] **Step 3: Bring the stack up**

```bash
docker-compose up -d --build
sleep 30
docker-compose ps
```

Expected: 9 containers `Up` / `Up (healthy)` (Phase 0 had 8; we added `worker_fast`).

- [ ] **Step 4: Apply migrations and seed reference data**

```bash
docker-compose exec web python manage.py migrate
docker-compose exec web python manage.py seed_rate_limit_buckets
docker-compose exec web python manage.py load_network_taxonomy
```

Expected output (last command):
```
Loaded 10 new networks, updated 0.
```
(Or higher if the implementer has populated more of the taxonomy.)

- [ ] **Step 5: Smoke-test the corpus pipeline end-to-end**

Trigger a tiny PubMed refresh manually:

```bash
docker-compose exec web python manage.py shell -c "
from corpus.tasks import ingest_paper
ingest_paper.delay(38000123).get(timeout=60)
print('ingested')
"
```

Expected: `ingested` printed; check the dashboard:

```bash
curl -s -H 'Remote-User: fchemorion' http://localhost:8000/corpus/stats | grep -i "total papers"
```

Expected: the stats page renders with `Total papers: 1` (or more, depending on prior runs).

- [ ] **Step 6: Smoke-test the CSV export**

```bash
curl -s -H 'Remote-User: fchemorion' \
  "http://localhost:8000/corpus/export.csv?format=full" | head -3
```

Expected: first line is the CSV header row containing `pmid,title,journal,...`.

- [ ] **Step 7: Tear down for clean state and commit**

```bash
docker-compose down
git add docker-compose.yml
git commit -m "build: add worker_fast container for cheap-LLM tasks"
```

---

## Task 33: Phase 1 close-out — full test suite, push, tag

- [ ] **Step 1: Run the entire test suite**

```bash
poetry run ruff check .
poetry run ruff format --check .
poetry run mypy apps interactome
poetry run pytest -v
```

Expected: all four commands exit 0. Phase 1 adds ~150 tests across 6 apps; total runtime should be ≤ 3 minutes.

- [ ] **Step 2: Push to origin**

```bash
git push origin main
```

- [ ] **Step 3: Verify GitHub Actions CI is green**

Open the repository's Actions tab; the latest run should be green within ~5 minutes.

- [ ] **Step 4: Tag the Phase 1 release**

```bash
git tag -a phase-1-complete -m "Phase 1 (Master IDD corpus) complete

Working subsystems:
- networks app with 10-seed taxonomy (200+ networks if implementer extended fixture)
- corpus app: Paper / PaperRelevance / IngestRun
- corpus.refresh_pubmed + ingest_paper (NCBI + PubTator)
- papers app: classify_original (rule + qwen3 LLM)
- papers.fetch_fulltext (Europe PMC + MinIO)
- papers.section_and_chunk (DoCO + tiktoken/nltk chunker)
- corpus.triage_relevance two-pass (keyword + qwen3 LLM)
- schedule app: rate limits + watermarks + janitor + Beat schedule
- /corpus/export.csv with format=full and network filters
- /corpus/stats + /corpus/paper/<pmid> dashboard views
- worker_fast container for cheap-LLM tasks
- Authelia-authenticated OllamaClient
- MinIO blob client with PMID-prefix sharding

Next: Phase 2 (Extraction pipeline) — extract.run_ppi across 7 models."
git push origin phase-1-complete
```

- [ ] **Step 5: Bootstrap the historical corpus (background long-running)**

This step kicks off the actual data ingest the deliverable is named after. Run on the cluster, not locally.

```bash
ssh cluster.simbiosys.sb.upf.edu
cd /opt/interactome
docker-compose exec web python manage.py shell -c "
from corpus.tasks import refresh_pubmed_full
refresh_pubmed_full.delay()
print('full sweep enqueued')
"
```

The full sweep runs for several hours (per spec §5 bootstrap timeline: ~3 hours for the ESearch + EFetch pass; the full corpus is network-tagged within ~1 week of cluster wall-clock).

Monitor via:
```bash
docker-compose exec web python manage.py shell -c "
from corpus.models import Paper
print('total papers:', Paper.objects.count())
print('chunked:', Paper.objects.filter(ingest_status='chunked').count())
"
```

- [ ] **Step 6: Phase 1 done. Hand off for Phase 2 plan.**

The deliverable is satisfied when:

1. `Paper.objects.count() ≥ 30000`
2. `Paper.objects.filter(is_original=True).count() ≥ 20000`
3. `Paper.objects.filter(full_text_status='pmc_jats').count() ≥ 10000`
4. `PaperRelevance.objects.values('network').distinct().count() ≥ 100`
5. `curl /corpus/export.csv?network=nfkb_axis` returns ≥ 500 rows
6. Stack survives a `docker-compose down && docker-compose up -d` with the janitor sweeping any stale `running` rows.

Once these are checked off in production, the Phase 2 (Extraction pipeline) implementation plan can be written.

---

## Phase 1 Self-Review

**Spec coverage check** (against `docs/superpowers/specs/2026-05-19-disc-interactome-app-design.md`):

- Section 1 (high-level architecture) — corpus + papers + schedule fit the Postgres-as-checkpoint, Celery-by-queue invariants. (Tasks 4, 7, 24, 26, 32)
- Section 2 (Django apps and module boundaries) — five new apps scaffolded (networks, corpus, papers, schedule, dashboard); each has a `services.py` public boundary. (Tasks 3, 11)
- Section 3 (data model) — all Phase-1-relevant tables created with status fields driving the pipeline: `Paper` (PK pmid, `ingest_status`, `full_text_status`, `is_original`, `fulltext_s3_key`), `PaperRelevance` (M:N paper/network with `score` and `classified_by`), `IngestRun`, `Watermark`, `RateLimitBucket`, `ScheduledJob`, `Network`, `NetworkQuery`, `FamilyFilter`, `Section`, `Chunk`, `PaperClassification`. Resumability pattern (`status='running'` + heartbeat + janitor) implemented end-to-end. (Tasks 4, 6, 9, 14, 19)
- Section 4 (per-paper pipeline) — first half of the pipeline (corpus.refresh → ingest_paper → classify_original → fetch_fulltext → section_and_chunk → triage_relevance) implemented. Extraction, integration, sbml.regenerate are explicitly deferred to Phases 2–4. (Tasks 24–29)
- Section 5 (master corpus subsystem) — load-bearing section. Master IDD query verbatim per spec (Task 15); E-utilities + Europe PMC OAI + PubTator3 + GROBID clients (Tasks 16, 17, 18, 23); watermarks with 7-day overlap (Task 7); rate-limit buckets per provider (Tasks 4, 8); two-pass relevance triage with confidence-as-score (Task 29); `/corpus/export.csv` with `?format=full` and `?network=<code>` filters (Task 30); `/corpus/stats` and `/corpus/paper/<pmid>` (Task 31). Citation traversal via `NcbiClient.elink_refs` is implemented in Task 16; the periodic discovery of cited PMIDs is not yet wired into a Beat task — implementer can drop this in as a future enhancement or it falls to Phase 6 ("Continuous monitoring").
- Section 6 (Celery topology) — `q.io` (carry-over from Phase 0) plus new `q.fast` queue with its dedicated `worker_fast` container; per-task routing via `CELERY_TASK_ROUTES` (Task 2); full Phase-1 Beat schedule (`janitor_reset_stale_running`, `refill_rate_limit_buckets`, `corpus.refresh_pubmed`, `corpus.refresh_pubmed_full`, `papers.classify_pending`, `papers.fetch_fulltext_pending`, `papers.section_pending`, `corpus.triage_pending`) — Task 8; `@require_token` rate-limit decorator (Task 5). Per-model extraction queues are Phase 2, deferred.
- Section 7 (SBML + verify UI) — deferred to Phases 4 and 5. Only `Network.pipeline_status` field is in place (Task 9) for later state-machine work.
- Section 8 (resumability) — every long-running task starts with a status check, sets `running` + heartbeat, and terminates in `done` or `failed` (Tasks 24, 25, 26, 27, 28, 29); janitor resets stale rows every 5 min (Task 6); idempotent task entry verified in tests for `ingest_paper`, `classify_original`, `fetch_fulltext`, `section_and_chunk`.
- Section 9 (deployment) — `worker_fast` added to docker-compose; settings extend with MinIO, Ollama, NCBI, Europe PMC, PubTator, GROBID config; `.env.example` updated with all new env vars (Task 2). Authelia integration leveraged by `OllamaClient` (Task 12).
- Section 10 (roadmap) — this plan implements the row for Phase 1.
- Appendix A (taxonomy) — fixture and loader (Task 10) with 10 seed entries spanning 4 categories; implementer must populate the remaining ~190 entries across all 17 categories.

**Placeholder scan:** No "TBD" / "TODO" / "implement later" strings in any task body. Where a later task fills in a stub (e.g. `ingest_paper` in Task 24 placeholder → Task 25 implementation), the stub raises `NotImplementedError("Task 25")` with the exact follow-up task ID, never a vague placeholder. The single "IMPLEMENTER:" comment in the taxonomy YAML is explicit instruction to populate per Appendix A, not a deferred implementation choice.

**Type / name consistency:**
- Model names match across tests, implementation, fixtures, and references: `Network`, `NetworkQuery`, `FamilyFilter`, `Paper`, `PaperRelevance`, `IngestRun`, `Section`, `Chunk`, `PaperClassification`, `Watermark`, `RateLimitBucket`, `ScheduledJob`.
- Task names use the consistent `<app>.tasks.<func>` form: `corpus.tasks.refresh_pubmed`, `corpus.tasks.ingest_paper`, `corpus.tasks.triage_pending`, `corpus.tasks.triage_relevance_cheap`, `corpus.tasks.triage_relevance_llm`, `papers.tasks.classify_pending`, `papers.tasks.classify_original`, `papers.tasks.fetch_fulltext_pending`, `papers.tasks.fetch_fulltext`, `papers.tasks.section_pending`, `papers.tasks.section_and_chunk`, `schedule.tasks.janitor_reset_stale_running`, `schedule.tasks.refill_rate_limit_buckets`. These names appear identically in `CELERY_TASK_ROUTES`, the Beat schedule dict, and the `@shared_task(name=...)` decorators.
- Status enum values match across model definition, test assertions, and task transitions: `pending → running → ingested → classified → fetched → chunked → done · failed · ingest_failed`; `full_text_status ∈ {none, abstract_only, pmc_jats, grobid_tei, fetch_failed}`; `pipeline_status ∈ {idle, refreshing, stale, version_draft, verified}`.
- `classified_by` values for `PaperRelevance` match across model choices, cheap-pass insert, and LLM-pass update: `cheap_keyword`, `cheap_pubtator`, `llm:qwen3:8b`.
- `paper_object_key(pmid, ext)` returns `papers/<4-digit-prefix>/<pmid>.<ext>` consistently in tests, the MinioClient, and the fetch_fulltext call site.
- Rate-limit `provider` strings match between fixture (`ncbi_eutils`, `europe_pmc_oai`, `pubtator3`, `grobid`, `ollama_qwen3_8b`), `@require_token(...)` decorators on each client method, and tests.

**Cross-phase implicit dependencies later phases must honour:**
- `Paper.ingest_status` adds new values in later phases (e.g. `extracted` after Phase 2). The migration strategy must be forward-only (per spec §8); existing rows with `status='chunked'` should still pass `extract.enqueue_pending_chunks`'s filter.
- `Chunk.processed_by_models` JSON list (currently empty) is mutated by Phase 2's `extract.run_ppi` to record which Ollama models have already extracted from each chunk. Phase 2 must not change the field name or shape.
- `Network.pipeline_status` already supports `version_draft` and `verified`; Phase 4 (SBML) and Phase 5 (verify UI) drive transitions through those states.
- `RateLimitBucket` schema is stable; Phase 2 must seed buckets for the remaining 6 extractor-model providers (`ollama_medgemma_27b`, `ollama_phi4_14b`, `ollama_gemma3_12b`, `ollama_deepseek_r1_32b`, `ollama_devstral_24b`, `ollama_llama3_1_8b`) by adding entries to `0001_buckets.yaml` (or a follow-up fixture).
- The `_JANITOR_REGISTRY` in `schedule.tasks` is the registration hook Phase 2's `ExtractionRun` model must call from its `AppConfig.ready()` — pattern: `register_janitor_target("extract", "ExtractionRun", "status", "heartbeat")`.
- `core.OllamaClient` is the only authorised path to the GPU box — Phase 2 must instantiate it (one per worker process) rather than re-implementing the Authelia handshake. The `format` parameter on `generate()` and `chat()` is reserved for Phase 2's PPI JSON-schema constraint.
- `PaperRelevance.score ≥ 0.5` is the default "in corpus for network X" threshold (per spec §5); Phase 3 (`graph.NetworkEdgeMembership`) should use the same threshold so triage-positive papers automatically flow into the graph.
- The Beat schedule dict in `schedule/beat_schedule.py` is the canonical source — later phases extend the dict rather than create parallel schedules.
- `corpus.IngestRun` rows are append-only audit logs; later phases should add new `source` enum values rather than reuse existing ones.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-19-phase-1-master-corpus.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — Dispatch a fresh subagent per task with review between commits. Phase 1 has more tasks than Phase 0 (33 vs 15) but each task is bite-sized (2–5 minutes), and the subagent flow lets a different subagent populate the network taxonomy YAML in parallel with the rest of the pipeline work — the two streams don't touch the same files.

**2. Inline Execution** — Execute tasks in this session using `executing-plans`, batched with checkpoints. Recommended batches:
- Batch A (Tasks 1–11): infrastructure, schedule app, networks app — landmark = `manage.py load_network_taxonomy` succeeds.
- Batch B (Tasks 12–18): clients (Ollama, MinIO, NCBI, Europe PMC, PubTator) — landmark = all client unit tests green.
- Batch C (Tasks 19–23): papers models and parsers — landmark = `parse_jats` + `chunk_text` tests green.
- Batch D (Tasks 24–29): tasks pipeline end-to-end — landmark = a single `ingest_paper.delay(38000123)` flows through to a `Paper` row with `ingest_status='chunked'`.
- Batch E (Tasks 30–33): views, stack wiring, close-out.

**Which approach?**
