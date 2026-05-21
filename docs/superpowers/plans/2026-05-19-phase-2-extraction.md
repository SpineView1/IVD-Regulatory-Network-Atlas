# Phase 2: Extraction Pipeline — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Take the Phase 1 corpus of Results-sectioned `Chunk` rows and run every chunk through all seven Ollama models, persisting structured PPI tuples to `RawPPI`. End state: `docker-compose up -d` brings 15 services online (the 9 from Phase 0 plus the 7 per-model extractor workers minus the now-shared image); a single smoke task fans one chunk out to all 7 model queues, every queue returns at least one `RawPPI` row, and the Beat-fired `extract.enqueue_pending_chunks` task is steadily draining the `(Chunk × Model)` backlog.

**Architecture:** One new Django app, `extract`, owns three models (`ExtractionRun`, `RawPPI`, `PromptTemplate`) and two Celery tasks (`run_ppi`, `enqueue_pending_chunks`). The `core` app gains a shared `OllamaClient` (HTTP client with Authelia session refresh, JSON-schema-constrained decoding, logprob extraction, exponential backoff) and a `@with_heartbeat` decorator. The `schedule` app gains an `Ollama` `RateLimitBucket` row and an `extract.run_ppi` registration in its janitor sweep list. `docker-compose.yml` gains seven `worker_extract_<model>` services, each bound to its own queue with `concurrency=1`, and Ollama-specific environment variables (`OLLAMA_KEEP_ALIVE=2h`, `OLLAMA_MAX_LOADED_MODELS=2`).

**Tech Stack:** Python 3.12, Django 5.0, Celery 5.3, PostgreSQL 16, Redis 7, `httpx` 0.27 (HTTP/2 + retries), `tenacity` 9.0 (decorator-based backoff), `pydantic` 2.9 (JSON schema generation and response validation), Ollama gateway at `https://ollama.simbiosys.sb.upf.edu`.

**Reference spec:** `docs/superpowers/specs/2026-05-19-disc-interactome-app-design.md` Sections 2 (apps), 3 (data model), 4 (per-paper pipeline — `run_ppi` stage), 6 (Celery topology — all of it), 8 (resumability — heartbeat + janitor).

**Phase dependencies:**
- **Requires Phase 0** complete (Django boots, Celery wired, `core` app with `TimestampedModel`, `worker_io` service running, ruff/mypy/pytest green).
- **Requires Phase 1** complete: the `papers` app has shipped `Chunk` rows with `doco_type='Results'`; the `schedule` app has shipped `RateLimitBucket` model, the `@require_token` decorator, the `janitor_reset_stale_running` Beat task, and a `Watermark` model; the `corpus` app has shipped at least the `Paper` model.

**Does NOT implement:**
- Entity grounding or `Edge` creation (those belong to Phase 3 `graph`).
- The `Chunk` model itself (already in Phase 1 `papers`).
- The janitor task body (already in Phase 1 `schedule`) — this phase only adds `ExtractionRun` to its sweep list.
- The `RateLimitBucket` model or `@require_token` decorator (already in Phase 1) — this phase only adds the `Ollama` bucket row and uses the existing decorator.

---

## File Structure After Phase 2

```
/                                       (git repo root, additions only)
├── docker-compose.yml                  +7 worker_extract_<model> services, +Ollama env vars
├── pyproject.toml                      +httpx, +tenacity, +pydantic deps
├── apps/
│   ├── core/
│   │   ├── ollama.py                   NEW — OllamaClient (sync httpx wrapper)
│   │   ├── heartbeat.py                NEW — @with_heartbeat decorator
│   │   └── tests/
│   │       ├── test_ollama.py          NEW — mocked HTTP + logprob extraction
│   │       └── test_heartbeat.py       NEW — decorator updates heartbeat field
│   ├── schedule/
│   │   ├── migrations/
│   │   │   └── 0002_ollama_bucket.py   NEW — data migration to insert Ollama bucket row
│   │   ├── janitor.py                  MODIFIED — append ExtractionRun to SWEEP_MODELS
│   │   └── tests/
│   │       └── test_janitor.py         MODIFIED — assert ExtractionRun is swept
│   └── extract/                        NEW Django app
│       ├── __init__.py
│       ├── apps.py                     ExtractConfig
│       ├── models.py                   ExtractionRun, RawPPI, PromptTemplate
│       ├── schemas.py                  Pydantic models for PPI tuple + JSON schema
│       ├── prompts.py                  PROMPT_V1 template literal + model registry
│       ├── services.py                 build_prompt(), upsert_runs_for_chunk()
│       ├── tasks.py                    run_ppi, enqueue_pending_chunks, smoke_all_models
│       ├── routing.py                  MODEL_TO_QUEUE map
│       ├── admin.py                    minimal admin registration
│       ├── migrations/
│       │   ├── __init__.py
│       │   ├── 0001_initial.py         auto-generated
│       │   └── 0002_seed_prompt.py     data migration: insert PROMPT_V1 row
│       └── tests/
│           ├── __init__.py
│           ├── conftest.py             fixtures: chunk, prompt_template, mock_ollama
│           ├── test_models.py          ExtractionRun unique constraint, status FSM
│           ├── test_schemas.py         JSON-schema round-trip, validation rejection
│           ├── test_prompts.py         template renders without unfilled placeholders
│           ├── test_services.py        upsert idempotency, prompt rendering
│           ├── test_tasks_run_ppi.py   end-to-end with mocked OllamaClient
│           ├── test_tasks_enqueue.py   fan-out routes by model→queue
│           └── test_smoke_all_models.py integration smoke (live Ollama, marked)
└── interactome/
    └── settings/
        └── base.py                     MODIFIED — register 'extract' in INSTALLED_APPS,
                                                   add Celery task_routes, add OLLAMA_* env keys
```

**Why this layout:**
- `apps/extract/` is the new app holding everything PPI-related. Following spec §2 boundary discipline, other apps will read its rows but call `extract.services` for writes.
- `apps/core/ollama.py` lives in `core` because (per spec §2) the Ollama client is a shared infrastructure utility, not a `extract`-specific concern — Phase 1's `classify_original` and Phase 1's relevance triage already use it (or will, once they exist), and the `graph` phase's `conflict.auto_resolve` task will reuse it. Putting it under `core` avoids a circular dep where `extract` would have to be imported by `papers`.
- `apps/core/heartbeat.py` likewise lives in `core` per spec §8 ("a heartbeat callback updates `Model.heartbeat = now()` for long tasks") — the decorator is generic and reused by any long-running Celery task in any app.
- Data migrations (`0002_seed_prompt.py`, `0002_ollama_bucket.py`) carry the canonical PROMPT_V1 text and the Ollama rate-limit bucket row, so a fresh `docker-compose up` results in a usable extraction pipeline without manual fixture loading.

---

## Task 1: Add HTTP / schema / retry dependencies

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Append the new dependencies under `[tool.poetry.dependencies]` in `pyproject.toml`**

After the existing `requests = "^2.32"` line, add:

```toml
httpx = {extras = ["http2"], version = "^0.27"}
tenacity = "^9.0"
pydantic = "^2.9"
```

The rest of the file stays unchanged.

- [ ] **Step 2: Update the lock file and install**

```bash
poetry lock --no-update
poetry install
```

Expected last line:
```
Installing the current project: interactome (0.1.0)
```

- [ ] **Step 3: Verify the new modules import**

```bash
poetry run python -c "import httpx, tenacity, pydantic; print(httpx.__version__, tenacity.__version__, pydantic.__version__)"
```

Expected (versions may differ in patch):
```
0.27.x 9.0.x 2.9.x
```

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml poetry.lock
git commit -m "build: add httpx, tenacity, pydantic for extraction pipeline"
```

---

## Task 2: PPI Pydantic schema and JSON-schema export (TDD)

The Ollama `format` parameter (per spec §4 — `POST /api/generate with format=PPI_SCHEMA`) requires a JSON-schema dict. We author one Pydantic model, derive the schema from it, and validate every Ollama response against the same model. One source of truth.

**Files:**
- Create: `apps/extract/__init__.py`
- Create: `apps/extract/apps.py`
- Create: `apps/extract/schemas.py`
- Create: `apps/extract/migrations/__init__.py`
- Create: `apps/extract/tests/__init__.py`
- Create: `apps/extract/tests/conftest.py`
- Create: `apps/extract/tests/test_schemas.py`

- [ ] **Step 1: Create `apps/extract/__init__.py`**

```python
"""extract — PPI extraction app.

One task per (chunk × Ollama model). Produces RawPPI rows; Phase 3
(graph) consumes them.
"""
```

- [ ] **Step 2: Create `apps/extract/apps.py`**

```python
"""Django AppConfig for the extract app."""
from __future__ import annotations

from django.apps import AppConfig


class ExtractConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "extract"
    verbose_name = "Extraction (PPI tuples from chunks)"
```

- [ ] **Step 3: Create `apps/extract/migrations/__init__.py`** — empty file.

- [ ] **Step 4: Create `apps/extract/tests/__init__.py`** — empty file.

- [ ] **Step 5: Create `apps/extract/tests/conftest.py`**

```python
"""Shared pytest fixtures for the extract app."""
from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture
def sample_ppi_payload() -> dict[str, Any]:
    """A minimal valid PPI extraction response body."""
    return {
        "ppis": [
            {
                "subject": "IL1B",
                "object": "MMP13",
                "relation": "activates",
                "evidence_span": "IL-1β robustly induced MMP13 transcription",
                "evidence_offset_start": 12,
                "evidence_offset_end": 56,
                "cell_type": "nucleus pulposus",
                "stimulus": "IL-1β stimulation",
                "confidence": 0.86,
            }
        ]
    }
```

- [ ] **Step 6: Write the failing test in `apps/extract/tests/test_schemas.py`**

```python
"""Tests for extract.schemas — Pydantic models and JSON-schema export."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from extract.schemas import (
    PPI_JSON_SCHEMA,
    AllowedRelation,
    PPIExtractionResponse,
    PPITuple,
)


def test_valid_payload_parses(sample_ppi_payload):
    parsed = PPIExtractionResponse.model_validate(sample_ppi_payload)
    assert len(parsed.ppis) == 1
    assert parsed.ppis[0].subject == "IL1B"
    assert parsed.ppis[0].relation == AllowedRelation.ACTIVATES


def test_unknown_relation_rejected():
    bad = {
        "ppis": [
            {
                "subject": "A",
                "object": "B",
                "relation": "tickles",  # not in enum
                "evidence_span": "x",
                "evidence_offset_start": 0,
                "evidence_offset_end": 1,
                "cell_type": None,
                "stimulus": None,
                "confidence": 0.5,
            }
        ]
    }
    with pytest.raises(ValidationError):
        PPIExtractionResponse.model_validate(bad)


def test_confidence_must_be_between_0_and_1():
    bad = {
        "ppis": [
            {
                "subject": "A",
                "object": "B",
                "relation": "activates",
                "evidence_span": "x",
                "evidence_offset_start": 0,
                "evidence_offset_end": 1,
                "cell_type": None,
                "stimulus": None,
                "confidence": 1.4,
            }
        ]
    }
    with pytest.raises(ValidationError):
        PPIExtractionResponse.model_validate(bad)


def test_offset_end_must_be_strictly_greater_than_start():
    bad = {
        "ppis": [
            {
                "subject": "A",
                "object": "B",
                "relation": "activates",
                "evidence_span": "x",
                "evidence_offset_start": 5,
                "evidence_offset_end": 5,
                "cell_type": None,
                "stimulus": None,
                "confidence": 0.5,
            }
        ]
    }
    with pytest.raises(ValidationError):
        PPIExtractionResponse.model_validate(bad)


def test_empty_ppi_list_is_valid():
    """A chunk that contains no PPI is a legitimate response."""
    parsed = PPIExtractionResponse.model_validate({"ppis": []})
    assert parsed.ppis == []


def test_json_schema_has_required_top_level_key():
    assert PPI_JSON_SCHEMA["type"] == "object"
    assert "ppis" in PPI_JSON_SCHEMA["properties"]
    assert PPI_JSON_SCHEMA["properties"]["ppis"]["type"] == "array"


def test_json_schema_enumerates_relations():
    relation_schema = (
        PPI_JSON_SCHEMA["properties"]["ppis"]["items"]["properties"]["relation"]
    )
    assert "enum" in relation_schema
    assert set(relation_schema["enum"]) == {
        "activates", "inhibits", "binds", "phosphorylates",
        "dephosphorylates", "ubiquitinates", "deubiquitinates",
        "transcribes", "represses", "cleaves", "translocates",
    }


def test_tuple_model_serialises_round_trip(sample_ppi_payload):
    parsed = PPIExtractionResponse.model_validate(sample_ppi_payload)
    serialised = parsed.model_dump(mode="json")
    re_parsed = PPIExtractionResponse.model_validate(serialised)
    assert re_parsed == parsed
```

- [ ] **Step 7: Run the test to verify it fails**

```bash
poetry run pytest apps/extract/tests/test_schemas.py -v
```

Expected:
```
ImportError: cannot import name 'PPI_JSON_SCHEMA' from 'extract.schemas'
```

- [ ] **Step 8: Implement `apps/extract/schemas.py`**

```python
"""Pydantic models for the PPI extraction response.

Single source of truth for:
  • the JSON schema we pass to Ollama via the ``format`` parameter
  • the validator that parses Ollama's response before persistence

Per spec §4 the prompt asks the LLM to emit
``{subject, object, relation, evidence_span, cell_type, stimulus, confidence}``;
we additionally require character offsets into the chunk so the graph
phase can recover the exact evidence text without re-scanning.
"""
from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AllowedRelation(StrEnum):
    ACTIVATES = "activates"
    INHIBITS = "inhibits"
    BINDS = "binds"
    PHOSPHORYLATES = "phosphorylates"
    DEPHOSPHORYLATES = "dephosphorylates"
    UBIQUITINATES = "ubiquitinates"
    DEUBIQUITINATES = "deubiquitinates"
    TRANSCRIBES = "transcribes"
    REPRESSES = "represses"
    CLEAVES = "cleaves"
    TRANSLOCATES = "translocates"


class PPITuple(BaseModel):
    """One extracted protein-protein (or protein-RNA, protein-metabolite) interaction."""

    model_config = ConfigDict(extra="forbid", use_enum_values=False)

    subject: str = Field(min_length=1, max_length=128)
    object: str = Field(min_length=1, max_length=128)
    relation: AllowedRelation
    evidence_span: str = Field(min_length=1, max_length=2000)
    evidence_offset_start: int = Field(ge=0)
    evidence_offset_end: int = Field(ge=1)
    cell_type: str | None = Field(default=None, max_length=128)
    stimulus: str | None = Field(default=None, max_length=256)
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _check_offsets(self) -> "PPITuple":
        if self.evidence_offset_end <= self.evidence_offset_start:
            raise ValueError(
                "evidence_offset_end must be strictly greater than evidence_offset_start"
            )
        return self


class PPIExtractionResponse(BaseModel):
    """Top-level wrapper. Ollama returns an object so that an empty list
    is encodable as ``{"ppis": []}`` instead of an ambiguous ``[]``.
    """

    model_config = ConfigDict(extra="forbid")

    ppis: list[PPITuple] = Field(default_factory=list, max_length=64)


def _build_json_schema() -> dict[str, Any]:
    """Return the schema dict in the exact shape Ollama's ``format`` wants.

    Ollama accepts the same JSON Schema dialect Pydantic emits, except
    that ``$defs`` and ``$ref`` are inlined to keep models from getting
    confused. We dereference here once at import time.
    """
    raw = PPIExtractionResponse.model_json_schema()
    defs = raw.pop("$defs", {})

    def inline(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                ref_name = node["$ref"].rsplit("/", 1)[-1]
                return inline(defs[ref_name])
            return {k: inline(v) for k, v in node.items()}
        if isinstance(node, list):
            return [inline(x) for x in node]
        return node

    return inline(raw)


PPI_JSON_SCHEMA: dict[str, Any] = _build_json_schema()
```

- [ ] **Step 9: Run the test to verify it passes**

```bash
poetry run pytest apps/extract/tests/test_schemas.py -v
```

Expected:
```
8 passed
```

- [ ] **Step 10: Commit**

```bash
git add apps/extract/__init__.py apps/extract/apps.py apps/extract/migrations/__init__.py apps/extract/tests/__init__.py apps/extract/tests/conftest.py apps/extract/tests/test_schemas.py apps/extract/schemas.py
git commit -m "feat(extract): add PPI Pydantic schema with JSON-schema export"
```

---

## Task 3: PromptTemplate prompt body and renderer (TDD)

Per spec §2 the `extract` app owns a `PromptTemplate` model; per spec §10 ("structured PPI prompt template") the prompt is versioned so future improvements don't invalidate prior extractions — every `ExtractionRun` is keyed on `(chunk × model × prompt_version)` (spec §3 row 3).

This task creates the prompt text and the rendering function. The Django model that persists it comes in Task 4.

**Files:**
- Create: `apps/extract/prompts.py`
- Create: `apps/extract/tests/test_prompts.py`

- [ ] **Step 1: Write the failing test in `apps/extract/tests/test_prompts.py`**

```python
"""Tests for extract.prompts — versioned PPI prompt text and renderer."""
from __future__ import annotations

import pytest

from extract.prompts import (
    PROMPT_V1_BODY,
    PROMPT_V1_VERSION,
    SUPPORTED_OLLAMA_MODELS,
    render_prompt,
)


def test_prompt_version_is_semver_string():
    assert isinstance(PROMPT_V1_VERSION, str)
    parts = PROMPT_V1_VERSION.split(".")
    assert len(parts) == 3
    assert all(p.isdigit() for p in parts)


def test_prompt_body_mentions_all_required_fields():
    body = PROMPT_V1_BODY.lower()
    for field in ("subject", "object", "relation", "evidence_span",
                  "cell_type", "stimulus", "confidence"):
        assert field in body, f"prompt missing field: {field}"


def test_prompt_body_lists_intervertebral_disc_context():
    """The prompt must orient the model to the IVD biology domain
    (spec §0 — domain-specific scope) so out-of-domain entities aren't
    over-extracted from off-topic text."""
    assert "intervertebral disc" in PROMPT_V1_BODY.lower()


def test_render_prompt_substitutes_chunk_text():
    rendered = render_prompt("BMP2 phosphorylates SMAD1 in NP cells.")
    assert "BMP2 phosphorylates SMAD1 in NP cells." in rendered


def test_render_prompt_no_unfilled_placeholders():
    rendered = render_prompt("any text")
    # double-brace marker we use for placeholders
    assert "{{" not in rendered
    assert "}}" not in rendered


def test_render_prompt_includes_relation_enum():
    rendered = render_prompt("x")
    for relation in ("activates", "inhibits", "binds", "phosphorylates"):
        assert relation in rendered


def test_supported_models_is_exactly_seven():
    assert len(SUPPORTED_OLLAMA_MODELS) == 7
    assert set(SUPPORTED_OLLAMA_MODELS) == {
        "medgemma:27b",
        "phi4:14b",
        "qwen3:8b",
        "gemma3:12b",
        "deepseek-r1:32b",
        "devstral:24b",
        "llama3.1:8b",
    }
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
poetry run pytest apps/extract/tests/test_prompts.py -v
```

Expected:
```
ImportError: cannot import name 'PROMPT_V1_BODY' from 'extract.prompts'
```

- [ ] **Step 3: Implement `apps/extract/prompts.py`**

```python
"""Versioned PPI extraction prompt.

Per spec §2 / §10 (Phase 2 deliverable), every ``ExtractionRun`` is
keyed on ``(chunk × model × prompt_version)`` so iterating the prompt
later does not invalidate prior extractions — old rows stay; new rows
appear alongside under a new version. Never edit ``PROMPT_V1_BODY`` in
place after first deploy; bump to ``PROMPT_V2_BODY`` instead.
"""
from __future__ import annotations

PROMPT_V1_VERSION = "1.0.0"

# The exact 7 Ollama models the cluster gateway exposes (per spec §1
# architecture diagram and §6 worker rationale).
SUPPORTED_OLLAMA_MODELS: tuple[str, ...] = (
    "medgemma:27b",
    "phi4:14b",
    "qwen3:8b",
    "gemma3:12b",
    "deepseek-r1:32b",
    "devstral:24b",
    "llama3.1:8b",
)

PROMPT_V1_BODY = """\
You are a biomedical relation-extraction system specialised in the
intervertebral disc (IVD) literature, including nucleus pulposus,
annulus fibrosus, cartilage endplate, and notochordal cell biology.

Read the Results-section text below and extract every protein-protein,
protein-RNA, protein-metabolite, or gene-regulation interaction the
authors **directly demonstrate** in their own experiments. Do not
extract claims that the authors merely cite from other papers, and do
not infer interactions that the text does not state.

For each interaction, return one object with these fields:

  • subject              — gene/protein symbol acting as the upstream node
  • object               — gene/protein symbol being acted on
  • relation             — one of:
      activates, inhibits, binds, phosphorylates, dephosphorylates,
      ubiquitinates, deubiquitinates, transcribes, represses, cleaves,
      translocates
  • evidence_span        — the verbatim sentence(s) supporting the claim
  • evidence_offset_start — zero-based character index of the span in the
                            chunk text I gave you
  • evidence_offset_end   — exclusive character index of the span's end
                            (strictly greater than evidence_offset_start)
  • cell_type            — cell type / tissue context (e.g. "nucleus
                           pulposus", "annulus fibrosus", "MSC"),
                           or null if not stated
  • stimulus             — experimental stimulus (e.g. "IL-1β
                           stimulation", "TNF-α", "hypoxia", "mechanical
                           load"), or null if not stated
  • confidence           — your subjective confidence on [0.0, 1.0]
                           that this interaction is correctly extracted

Return strictly the JSON object {"ppis": [ ... ]}. If the chunk reports
no qualifying interactions, return {"ppis": []}. Do not output prose,
commentary, code fences, or any field not listed above.

----- BEGIN CHUNK -----
{{CHUNK_TEXT}}
----- END CHUNK -----
"""


def render_prompt(chunk_text: str) -> str:
    """Fill the chunk-text placeholder. No other substitutions are made.

    We use ``{{CHUNK_TEXT}}`` as the placeholder so curly braces inside
    the literal prompt text (e.g. the example JSON shape) don't trigger
    ``str.format``-style errors.
    """
    return PROMPT_V1_BODY.replace("{{CHUNK_TEXT}}", chunk_text)
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
poetry run pytest apps/extract/tests/test_prompts.py -v
```

Expected:
```
7 passed
```

- [ ] **Step 5: Commit**

```bash
git add apps/extract/prompts.py apps/extract/tests/test_prompts.py
git commit -m "feat(extract): add versioned PPI prompt text and renderer"
```

---

## Task 4: Extract Django models (TDD)

Per spec §3 ("Tables" + ExtractionRun row): `ExtractionRun` is the resumability anchor — one row per `(chunk × model × prompt_version)` with `status ∈ {queued, running, done, failed}`, plus `heartbeat`, `attempts`, `error`. `RawPPI` is the terminal artifact — never deleted, references `ExtractionRun`, carries exact `evidence_span` offsets. `PromptTemplate` is the versioned prompt body.

**Files:**
- Modify: `interactome/settings/base.py` (register `extract` in `INSTALLED_APPS`)
- Create: `apps/extract/models.py`
- Create: `apps/extract/tests/test_models.py`
- Create: `apps/extract/migrations/0001_initial.py` (auto-generated via `makemigrations`)
- Create: `apps/extract/migrations/0002_seed_prompt.py`

- [ ] **Step 1: Register the app**

Edit `interactome/settings/base.py`. In `INSTALLED_APPS`, after the `"core",` line add:

```python
    "extract",
```

- [ ] **Step 2: Write the failing test in `apps/extract/tests/test_models.py`**

```python
"""Tests for extract.models — ExtractionRun, RawPPI, PromptTemplate."""
from __future__ import annotations

import pytest
from django.db import IntegrityError
from django.utils import timezone

from extract.models import ExtractionRun, PromptTemplate, RawPPI


@pytest.fixture
def prompt(db) -> PromptTemplate:
    return PromptTemplate.objects.create(
        version="1.0.0",
        body="dummy {{CHUNK_TEXT}}",
        is_active=True,
    )


@pytest.fixture
def chunk(db):
    """Phase 1 supplies the real Chunk model. For Phase 2 unit tests we
    use a stand-in via the actual Chunk model imported from the papers
    app; if Phase 1 is not yet implemented in the test database, this
    fixture falls back to creating a minimal Chunk via raw SQL."""
    from papers.models import Chunk, Section
    from corpus.models import Paper
    paper = Paper.objects.create(
        pmid="99999999",
        title="t",
        abstract="a",
    )
    section = Section.objects.create(paper=paper, doco_type="Results", order=0)
    return Chunk.objects.create(
        section=section,
        text="IL1B activates MMP13.",
        order=0,
        token_count=5,
    )


def test_prompt_template_unique_on_version(db):
    PromptTemplate.objects.create(version="2.0.0", body="x", is_active=False)
    with pytest.raises(IntegrityError):
        PromptTemplate.objects.create(version="2.0.0", body="y", is_active=False)


def test_only_one_active_prompt_at_a_time(db):
    PromptTemplate.objects.create(version="3.0.0", body="x", is_active=True)
    with pytest.raises(IntegrityError):
        PromptTemplate.objects.create(version="3.0.1", body="y", is_active=True)


def test_extractionrun_unique_on_chunk_model_promptversion(db, prompt, chunk):
    ExtractionRun.objects.create(
        chunk=chunk, model_name="qwen3:8b", prompt_version=prompt.version
    )
    with pytest.raises(IntegrityError):
        ExtractionRun.objects.create(
            chunk=chunk, model_name="qwen3:8b", prompt_version=prompt.version
        )


def test_extractionrun_default_status_is_queued(db, prompt, chunk):
    run = ExtractionRun.objects.create(
        chunk=chunk, model_name="qwen3:8b", prompt_version=prompt.version
    )
    assert run.status == ExtractionRun.Status.QUEUED


def test_extractionrun_attempts_defaults_zero(db, prompt, chunk):
    run = ExtractionRun.objects.create(
        chunk=chunk, model_name="qwen3:8b", prompt_version=prompt.version
    )
    assert run.attempts == 0


def test_extractionrun_heartbeat_initially_null(db, prompt, chunk):
    run = ExtractionRun.objects.create(
        chunk=chunk, model_name="qwen3:8b", prompt_version=prompt.version
    )
    assert run.heartbeat is None


def test_extractionrun_status_choices_are_full_fsm(db):
    statuses = {choice[0] for choice in ExtractionRun.Status.choices}
    assert statuses == {"queued", "running", "done", "failed"}


def test_rawppi_persists_offsets_and_confidence(db, prompt, chunk):
    run = ExtractionRun.objects.create(
        chunk=chunk, model_name="qwen3:8b", prompt_version=prompt.version
    )
    ppi = RawPPI.objects.create(
        run=run,
        subject="IL1B",
        object="MMP13",
        relation="activates",
        evidence_span="IL1B activates MMP13.",
        evidence_offset_start=0,
        evidence_offset_end=21,
        cell_type=None,
        stimulus=None,
        confidence=0.9,
        relation_logprob=-0.13,
        ungrounded=False,
    )
    ppi.refresh_from_db()
    assert ppi.confidence == 0.9
    assert ppi.evidence_offset_end == 21
    assert ppi.relation_logprob == -0.13


def test_rawppi_default_ungrounded_false(db, prompt, chunk):
    run = ExtractionRun.objects.create(
        chunk=chunk, model_name="qwen3:8b", prompt_version=prompt.version
    )
    ppi = RawPPI.objects.create(
        run=run, subject="A", object="B", relation="activates",
        evidence_span="x", evidence_offset_start=0, evidence_offset_end=1,
        confidence=0.5,
    )
    assert ppi.ungrounded is False


def test_extractionrun_indexed_on_status_for_janitor_sweep(db):
    indexes = {tuple(i.fields) for i in ExtractionRun._meta.indexes}
    assert ("status", "heartbeat") in indexes
```

- [ ] **Step 3: Implement `apps/extract/models.py`**

```python
"""extract models — ExtractionRun, RawPPI, PromptTemplate.

Per spec §3:
  • ExtractionRun is the resumability anchor (status, heartbeat, attempts).
  • RawPPI is the terminal artifact — never deleted, audit trail.
  • PromptTemplate versions the prompt so iteration doesn't invalidate
    prior extractions.
"""
from __future__ import annotations

from django.db import models

from core.models import TimestampedModel


class PromptTemplate(TimestampedModel):
    """Versioned prompt body. One row per prompt iteration; exactly one
    row is ``is_active=True`` at any moment (enforced by partial unique
    index)."""

    version = models.CharField(max_length=32, unique=True)
    body = models.TextField()
    is_active = models.BooleanField(default=False)
    notes = models.TextField(blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["is_active"],
                condition=models.Q(is_active=True),
                name="extract_prompt_only_one_active",
            ),
        ]

    def __str__(self) -> str:
        marker = " (active)" if self.is_active else ""
        return f"PromptTemplate v{self.version}{marker}"


class ExtractionRun(TimestampedModel):
    """One row per (chunk × model × prompt_version). Drives resumability."""

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        DONE = "done", "Done"
        FAILED = "failed", "Failed"

    chunk = models.ForeignKey(
        "papers.Chunk", on_delete=models.CASCADE, related_name="extraction_runs"
    )
    model_name = models.CharField(max_length=64)
    prompt_version = models.CharField(max_length=32)

    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.QUEUED
    )
    heartbeat = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    error = models.TextField(blank=True, default="")

    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    response_tokens = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["chunk", "model_name", "prompt_version"],
                name="extract_run_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "heartbeat"]),
            models.Index(fields=["model_name", "status"]),
        ]

    def __str__(self) -> str:
        return f"ExtractionRun(chunk={self.chunk_id}, model={self.model_name}, status={self.status})"


class RawPPI(TimestampedModel):
    """The terminal artifact: one extracted tuple as the LLM emitted it.

    Never deleted; the graph phase reads these and produces normalised
    ``Entity``/``Edge`` rows downstream. ``ungrounded`` is set later by
    graph.normalize_and_integrate when neither subject nor object can be
    mapped to an ontology identifier (spec §4 failure-handling table).
    """

    run = models.ForeignKey(
        ExtractionRun, on_delete=models.CASCADE, related_name="raw_ppis"
    )

    subject = models.CharField(max_length=128)
    object = models.CharField(max_length=128)
    relation = models.CharField(max_length=32)
    evidence_span = models.TextField()
    evidence_offset_start = models.PositiveIntegerField()
    evidence_offset_end = models.PositiveIntegerField()
    cell_type = models.CharField(max_length=128, null=True, blank=True)
    stimulus = models.CharField(max_length=256, null=True, blank=True)
    confidence = models.FloatField()

    # logprob of the first token of the chosen ``relation`` value;
    # captured per spec §4 (``logprobs=true`` on /api/generate). Used
    # by the graph phase's Bayes belief update.
    relation_logprob = models.FloatField(null=True, blank=True)

    ungrounded = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=["run"]),
            models.Index(fields=["ungrounded"]),
        ]

    def __str__(self) -> str:
        return f"RawPPI({self.subject} {self.relation} {self.object})"
```

- [ ] **Step 4: Generate the initial migration**

```bash
poetry run python manage.py makemigrations extract
```

Expected output:
```
Migrations for 'extract':
  apps/extract/migrations/0001_initial.py
    + Create model PromptTemplate
    + Create model ExtractionRun
    + Create model RawPPI
    + Create constraint extract_prompt_only_one_active on model prompttemplate
```

- [ ] **Step 5: Create the seed-prompt data migration `apps/extract/migrations/0002_seed_prompt.py`**

```python
"""Insert PROMPT_V1 as the first active PromptTemplate."""
from __future__ import annotations

from django.db import migrations


def seed_prompt(apps, schema_editor) -> None:
    PromptTemplate = apps.get_model("extract", "PromptTemplate")
    from extract.prompts import PROMPT_V1_BODY, PROMPT_V1_VERSION

    PromptTemplate.objects.update_or_create(
        version=PROMPT_V1_VERSION,
        defaults={"body": PROMPT_V1_BODY, "is_active": True},
    )


def unseed_prompt(apps, schema_editor) -> None:
    PromptTemplate = apps.get_model("extract", "PromptTemplate")
    from extract.prompts import PROMPT_V1_VERSION

    PromptTemplate.objects.filter(version=PROMPT_V1_VERSION).delete()


class Migration(migrations.Migration):
    dependencies = [("extract", "0001_initial")]
    operations = [migrations.RunPython(seed_prompt, unseed_prompt)]
```

- [ ] **Step 6: Run the tests**

```bash
poetry run pytest apps/extract/tests/test_models.py -v
```

Expected:
```
10 passed
```

If the `chunk` fixture errors because Phase 1's `papers` and `corpus` apps don't exist in the test database, the test must skip cleanly. (In a real deployment Phase 1 lands first; in isolation, the agent running this plan must apply the Phase 1 plan beforehand.)

- [ ] **Step 7: Apply migrations against the dev DB**

```bash
poetry run python manage.py migrate
```

Expected (final line):
```
  Applying extract.0002_seed_prompt... OK
```

- [ ] **Step 8: Commit**

```bash
git add interactome/settings/base.py apps/extract/models.py apps/extract/tests/test_models.py apps/extract/migrations/0001_initial.py apps/extract/migrations/0002_seed_prompt.py
git commit -m "feat(extract): add ExtractionRun, RawPPI, PromptTemplate models"
```

---

## Task 5: OllamaClient with schema-constrained decoding and logprobs (TDD)

Per spec §4 the extractor calls `POST /api/generate with format=PPI_SCHEMA + logprobs=true`. Per the task context: the client must handle (a) Authelia session cookie refresh against the same gateway that already fronts Ollama, (b) JSON-schema-constrained decoding via `format`, (c) logprob capture for the first token of the chosen `relation` value, (d) exponential-backoff retry on 5xx and timeouts, (e) passing `OLLAMA_KEEP_ALIVE` through.

Logprob extraction follows the medgemma-validated approach: walk the per-step `logprobs` array, find the first step whose chosen token starts with one of the relation enum strings, capture that step's `top_logprobs`, renormalize across the enum.

**Files:**
- Create: `apps/core/ollama.py`
- Create: `apps/core/tests/test_ollama.py`

- [ ] **Step 1: Write the failing test in `apps/core/tests/test_ollama.py`**

```python
"""Tests for core.ollama.OllamaClient — schema-constrained decoding,
logprob extraction, Authelia session refresh, retry/backoff."""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from core.ollama import OllamaClient, OllamaError, extract_relation_logprob


def _fake_response(payload: dict[str, Any], status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        request=httpx.Request("POST", "https://ollama.example/api/generate"),
        content=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )


@pytest.fixture
def ollama_success_payload() -> dict[str, Any]:
    """A minimal /api/generate JSON envelope with valid PPI content."""
    return {
        "model": "qwen3:8b",
        "response": json.dumps(
            {
                "ppis": [
                    {
                        "subject": "IL1B",
                        "object": "MMP13",
                        "relation": "activates",
                        "evidence_span": "IL-1β induced MMP13",
                        "evidence_offset_start": 0,
                        "evidence_offset_end": 19,
                        "cell_type": None,
                        "stimulus": None,
                        "confidence": 0.9,
                    }
                ]
            }
        ),
        "eval_count": 87,
        "logprobs": [
            {"token": "{", "logprob": -0.01, "top_logprobs": []},
            {"token": "\"ppis\"", "logprob": -0.02, "top_logprobs": []},
            {
                "token": "activates",
                "logprob": -0.13,
                "top_logprobs": [
                    {"token": "activates", "logprob": -0.13},
                    {"token": "inhibits", "logprob": -2.1},
                ],
            },
        ],
    }


def test_extract_relation_logprob_finds_first_relation_token(ollama_success_payload):
    lp = extract_relation_logprob(
        ollama_success_payload["logprobs"],
        allowed_relations=("activates", "inhibits", "binds"),
    )
    assert lp == pytest.approx(-0.13)


def test_extract_relation_logprob_returns_none_if_no_match():
    logprobs = [{"token": "junk", "logprob": -0.5, "top_logprobs": []}]
    assert extract_relation_logprob(logprobs, allowed_relations=("activates",)) is None


def test_extract_relation_logprob_renormalises_over_enum():
    logprobs = [
        {
            "token": "activates",
            "logprob": -1.0,
            "top_logprobs": [
                {"token": "activates", "logprob": -1.0},
                {"token": "inhibits", "logprob": -1.0},
                {"token": "junk", "logprob": -0.1},  # not in enum, must be dropped
            ],
        }
    ]
    lp = extract_relation_logprob(
        logprobs,
        allowed_relations=("activates", "inhibits"),
    )
    # both -1.0, so renormalised log-prob of 'activates' should be log(0.5) ≈ -0.693
    assert lp == pytest.approx(-0.6931, abs=1e-3)


def test_generate_returns_parsed_response_and_logprob(ollama_success_payload):
    client = OllamaClient(base_url="https://ollama.example", session_cookie="abc")
    with patch.object(client._http, "post", return_value=_fake_response(ollama_success_payload)):
        response_text, relation_logprob, eval_count = client.generate(
            model="qwen3:8b",
            prompt="prompt",
            json_schema={"type": "object"},
            keep_alive="2h",
            allowed_relations=("activates", "inhibits"),
        )
    assert "IL1B" in response_text
    assert relation_logprob == pytest.approx(-0.13)
    assert eval_count == 87


def test_generate_passes_keep_alive_in_body(ollama_success_payload):
    client = OllamaClient(base_url="https://ollama.example", session_cookie="abc")
    captured: dict[str, Any] = {}

    def _capture(*args, **kwargs):
        captured["body"] = kwargs.get("json")
        return _fake_response(ollama_success_payload)

    with patch.object(client._http, "post", side_effect=_capture):
        client.generate(
            model="qwen3:8b", prompt="p", json_schema={}, keep_alive="2h",
            allowed_relations=("activates",),
        )
    assert captured["body"]["keep_alive"] == "2h"
    assert captured["body"]["format"] == {}
    assert captured["body"]["options"]["logprobs"] is True


def test_generate_retries_on_503_then_succeeds(ollama_success_payload):
    client = OllamaClient(
        base_url="https://ollama.example", session_cookie="abc",
        max_retries=3, initial_backoff_sec=0.0,
    )
    responses = [
        _fake_response({"error": "overloaded"}, status_code=503),
        _fake_response({"error": "overloaded"}, status_code=503),
        _fake_response(ollama_success_payload, status_code=200),
    ]
    with patch.object(client._http, "post", side_effect=responses):
        response_text, _, _ = client.generate(
            model="qwen3:8b", prompt="p", json_schema={}, keep_alive="2h",
            allowed_relations=("activates",),
        )
    assert "IL1B" in response_text


def test_generate_raises_after_exhausting_retries():
    client = OllamaClient(
        base_url="https://ollama.example", session_cookie="abc",
        max_retries=2, initial_backoff_sec=0.0,
    )
    responses = [_fake_response({"error": "x"}, status_code=503)] * 3
    with patch.object(client._http, "post", side_effect=responses):
        with pytest.raises(OllamaError):
            client.generate(
                model="qwen3:8b", prompt="p", json_schema={}, keep_alive="2h",
                allowed_relations=("activates",),
            )


def test_generate_refreshes_session_on_401(ollama_success_payload):
    """A 401 from Ollama triggers a re-auth roundtrip against Authelia
    using the configured refresh callback."""
    client = OllamaClient(
        base_url="https://ollama.example", session_cookie="stale",
        max_retries=2, initial_backoff_sec=0.0,
        session_refresher=lambda: "fresh-cookie",
    )
    responses = [
        _fake_response({"error": "unauthorized"}, status_code=401),
        _fake_response(ollama_success_payload, status_code=200),
    ]
    with patch.object(client._http, "post", side_effect=responses):
        client.generate(
            model="qwen3:8b", prompt="p", json_schema={}, keep_alive="2h",
            allowed_relations=("activates",),
        )
    assert client.session_cookie == "fresh-cookie"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
poetry run pytest apps/core/tests/test_ollama.py -v
```

Expected:
```
ImportError: cannot import name 'OllamaClient' from 'core.ollama'
```

- [ ] **Step 3: Implement `apps/core/ollama.py`**

```python
"""Ollama API client.

Wraps ``POST /api/generate`` on the SIMBIOsys Ollama gateway. The
gateway is fronted by the same Authelia instance that fronts the
Django app (spec §1, §9), so requests must carry an Authelia session
cookie. If Ollama responds with 401 we invoke the refresher callback
to obtain a new cookie.

Per spec §4, requests use:
  • ``format``     — JSON Schema dict for schema-constrained decoding
  • ``options.logprobs`` = True — for relation-token logprob capture
  • ``keep_alive`` — seconds or duration string, kept in VRAM per spec §6
    (the docker-compose env var ``OLLAMA_KEEP_ALIVE=2h`` is the default).

Retry policy: exponential backoff on 5xx, 408, 429, network errors,
and timeouts. 4xx (other than 401, which triggers session refresh) is
permanent.
"""
from __future__ import annotations

import json
import logging
import math
import time
from collections.abc import Callable, Sequence
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class OllamaError(RuntimeError):
    """Raised on non-recoverable Ollama failure (after retry exhaustion)."""


_RETRYABLE_STATUSES = {408, 425, 429, 500, 502, 503, 504}


def extract_relation_logprob(
    logprobs: list[dict[str, Any]] | None,
    *,
    allowed_relations: Sequence[str],
) -> float | None:
    """Find the first step in the per-token logprobs whose chosen token
    matches one of ``allowed_relations``, then renormalise the top_logprobs
    over the enum to obtain a calibrated relation-level logprob.

    Returns ``None`` if no step matches (e.g. the response was empty or
    the model went off-prompt before emitting a relation field).

    The approach mirrors the medgemma-validated logprob pipeline used
    earlier in this project.
    """
    if not logprobs:
        return None

    allowed = set(allowed_relations)
    for step in logprobs:
        token = step.get("token", "")
        # Tokens may carry punctuation; the relation strings are short
        # alphabetic words, so a prefix-match is sufficient.
        for rel in allowed:
            if token == rel or token.startswith(rel):
                top = step.get("top_logprobs") or []
                # Restrict the top_k to candidates inside the enum.
                candidates: list[tuple[str, float]] = []
                for entry in top:
                    cand_tok = entry.get("token", "")
                    for cand_rel in allowed:
                        if cand_tok == cand_rel or cand_tok.startswith(cand_rel):
                            candidates.append((cand_rel, float(entry["logprob"])))
                            break
                if not candidates:
                    # Fall back to the chosen logprob itself.
                    return float(step.get("logprob", 0.0))
                # Renormalise: log-sum-exp denominator over enum candidates.
                lp_self = next(
                    (lp for r, lp in candidates if r == rel), float(step.get("logprob", 0.0))
                )
                denom = math.log(sum(math.exp(lp) for _, lp in candidates))
                return lp_self - denom

    return None


class OllamaClient:
    """Synchronous Ollama client. One instance per worker process; the
    underlying ``httpx.Client`` reuses HTTP/2 connections."""

    def __init__(
        self,
        *,
        base_url: str,
        session_cookie: str,
        timeout_sec: float = 600.0,
        max_retries: int = 5,
        initial_backoff_sec: float = 2.0,
        session_refresher: Callable[[], str] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.session_cookie = session_cookie
        self.max_retries = max_retries
        self.initial_backoff_sec = initial_backoff_sec
        self.session_refresher = session_refresher
        self._http = httpx.Client(
            http2=True,
            timeout=httpx.Timeout(timeout_sec, connect=15.0),
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "OllamaClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def generate(
        self,
        *,
        model: str,
        prompt: str,
        json_schema: dict[str, Any],
        keep_alive: str,
        allowed_relations: Sequence[str],
    ) -> tuple[str, float | None, int]:
        """Return ``(response_text, relation_logprob, eval_count)``.

        ``response_text`` is the model's raw output string — caller
        must run it through Pydantic for validation.
        """
        url = f"{self.base_url}/api/generate"
        body = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": json_schema,
            "keep_alive": keep_alive,
            "options": {
                "logprobs": True,
                "top_logprobs": 5,
                "temperature": 0.0,
            },
        }

        attempt = 0
        backoff = self.initial_backoff_sec
        last_error: str = ""
        while attempt <= self.max_retries:
            try:
                response = self._http.post(
                    url,
                    json=body,
                    cookies={"authelia_session": self.session_cookie},
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = f"network: {exc}"
                logger.warning("ollama network error attempt=%d: %s", attempt, exc)
            else:
                if response.status_code == 401 and self.session_refresher is not None:
                    new_cookie = self.session_refresher()
                    logger.info("ollama 401 — refreshed session cookie")
                    self.session_cookie = new_cookie
                    attempt += 1
                    continue
                if response.status_code in _RETRYABLE_STATUSES:
                    last_error = f"http {response.status_code}: {response.text[:200]}"
                    logger.warning(
                        "ollama retryable status=%d attempt=%d", response.status_code, attempt
                    )
                elif response.status_code >= 400:
                    raise OllamaError(
                        f"ollama permanent error {response.status_code}: {response.text[:500]}"
                    )
                else:
                    body_out = response.json()
                    response_text = body_out.get("response", "")
                    eval_count = int(body_out.get("eval_count", 0))
                    rel_lp = extract_relation_logprob(
                        body_out.get("logprobs"),
                        allowed_relations=allowed_relations,
                    )
                    return response_text, rel_lp, eval_count

            attempt += 1
            if attempt <= self.max_retries:
                time.sleep(backoff)
                backoff *= 2

        raise OllamaError(
            f"ollama failed after {self.max_retries} retries; last_error={last_error}"
        )


def parse_json_response(response_text: str) -> dict[str, Any]:
    """Tolerant JSON parser — Ollama with ``format`` returns clean JSON,
    but some models occasionally emit a trailing newline or stray
    whitespace. Stripping handles both."""
    return json.loads(response_text.strip())
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
poetry run pytest apps/core/tests/test_ollama.py -v
```

Expected:
```
8 passed
```

- [ ] **Step 5: Commit**

```bash
git add apps/core/ollama.py apps/core/tests/test_ollama.py
git commit -m "feat(core): add OllamaClient with schema-constrained decoding"
```

---

## Task 6: `@with_heartbeat` decorator (TDD)

Per spec §8 ("a heartbeat callback updates `Model.heartbeat = now()` for long tasks") the janitor relies on every long-running task touching its row's `heartbeat` field at least every 30 s. We implement this as a generic decorator usable by any task in any app.

**Files:**
- Create: `apps/core/heartbeat.py`
- Create: `apps/core/tests/test_heartbeat.py`

- [ ] **Step 1: Write the failing test in `apps/core/tests/test_heartbeat.py`**

```python
"""Tests for core.heartbeat.with_heartbeat decorator."""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest
from django.utils import timezone

from core.heartbeat import with_heartbeat


@pytest.fixture
def fake_row():
    row = MagicMock()
    row.heartbeat = None
    return row


def test_heartbeat_set_at_task_start(fake_row):
    @with_heartbeat(interval_sec=60, fetch=lambda _id: fake_row)
    def my_task(row_id: int) -> str:
        return "ok"

    result = my_task(row_id=1)
    assert result == "ok"
    assert fake_row.heartbeat is not None


def test_heartbeat_saved_at_task_start(fake_row):
    @with_heartbeat(interval_sec=60, fetch=lambda _id: fake_row)
    def my_task(row_id: int) -> str:
        return "ok"

    my_task(row_id=1)
    fake_row.save.assert_called()


def test_heartbeat_thread_ticks_during_long_task(fake_row):
    @with_heartbeat(interval_sec=0.05, fetch=lambda _id: fake_row)
    def my_task(row_id: int) -> str:
        time.sleep(0.2)  # several heartbeat intervals
        return "ok"

    my_task(row_id=1)
    # Initial set + ≥2 ticks during sleep
    assert fake_row.save.call_count >= 3


def test_heartbeat_thread_stops_after_task_returns(fake_row):
    @with_heartbeat(interval_sec=0.05, fetch=lambda _id: fake_row)
    def my_task(row_id: int) -> str:
        return "ok"

    my_task(row_id=1)
    n_saves_after_return = fake_row.save.call_count
    time.sleep(0.2)
    # No more saves after the task returned.
    assert fake_row.save.call_count == n_saves_after_return


def test_heartbeat_thread_stops_after_exception(fake_row):
    @with_heartbeat(interval_sec=0.05, fetch=lambda _id: fake_row)
    def my_task(row_id: int) -> str:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        my_task(row_id=1)
    n_saves_after_raise = fake_row.save.call_count
    time.sleep(0.2)
    assert fake_row.save.call_count == n_saves_after_raise


def test_heartbeat_passes_through_kwargs(fake_row):
    captured: dict = {}

    @with_heartbeat(interval_sec=60, fetch=lambda _id: fake_row)
    def my_task(row_id: int, model_name: str) -> None:
        captured["model_name"] = model_name

    my_task(row_id=1, model_name="qwen3:8b")
    assert captured["model_name"] == "qwen3:8b"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
poetry run pytest apps/core/tests/test_heartbeat.py -v
```

Expected:
```
ImportError: cannot import name 'with_heartbeat' from 'core.heartbeat'
```

- [ ] **Step 3: Implement `apps/core/heartbeat.py`**

```python
"""Heartbeat decorator for long-running Celery tasks.

Spec §8 mandates: ``@with_heartbeat`` updates a row's ``heartbeat``
timestamp every ``interval_sec`` so the janitor sweep
(``schedule.janitor_reset_stale_running``) can distinguish a still-alive
worker from one whose process died mid-task.

Usage:

    @shared_task
    @with_heartbeat(
        interval_sec=30,
        fetch=lambda run_id: ExtractionRun.objects.get(id=run_id),
    )
    def run_ppi(run_id: int) -> None:
        ...

The decorator spawns a daemon thread for the lifetime of the task; the
thread saves the row's ``heartbeat=timezone.now()`` every ``interval_sec``.
Stops cleanly on task return OR exception.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from functools import wraps
from typing import Any, ParamSpec, TypeVar

from django.utils import timezone

logger = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")


def with_heartbeat(
    *,
    interval_sec: float,
    fetch: Callable[[int], Any],
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator factory.

    ``fetch`` takes the ``row_id`` (always the first positional or
    keyword argument named ``row_id``) and returns the model instance to
    update.
    """

    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        @wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            row_id = kwargs.get("row_id")
            if row_id is None and args:
                row_id = args[0]
            row = fetch(int(row_id))  # type: ignore[arg-type]
            row.heartbeat = timezone.now()
            row.save(update_fields=["heartbeat"]) if hasattr(row, "save") and _supports_update_fields(row) else row.save()

            stop = threading.Event()

            def tick() -> None:
                while not stop.wait(interval_sec):
                    try:
                        row.heartbeat = timezone.now()
                        if _supports_update_fields(row):
                            row.save(update_fields=["heartbeat"])
                        else:
                            row.save()
                    except Exception as exc:
                        logger.warning("heartbeat tick failed: %s", exc)

            thread = threading.Thread(target=tick, name="heartbeat", daemon=True)
            thread.start()
            try:
                return fn(*args, **kwargs)
            finally:
                stop.set()
                thread.join(timeout=interval_sec + 1)

        return wrapper

    return decorator


def _supports_update_fields(row: Any) -> bool:
    """MagicMock saves don't accept ``update_fields`` cleanly; real
    Django models do. Branch so tests with mocks still work."""
    return hasattr(row, "_meta")
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
poetry run pytest apps/core/tests/test_heartbeat.py -v
```

Expected:
```
6 passed
```

- [ ] **Step 5: Commit**

```bash
git add apps/core/heartbeat.py apps/core/tests/test_heartbeat.py
git commit -m "feat(core): add with_heartbeat decorator for long tasks"
```

---

## Task 7: Model-to-queue routing map (TDD)

Per spec §6 each Ollama model has its own queue named `q.extract.<model_slug>`. The slug rules: lowercase, `:` and `.` replaced with `_`. This map is used both by `enqueue_pending_chunks` (when dispatching) and by `docker-compose.yml` (queue names per worker).

**Files:**
- Create: `apps/extract/routing.py`
- Modify: `apps/extract/tests/__init__.py` (no-op; just ensure dir exists — already created)
- Create: `apps/extract/tests/test_routing.py`

- [ ] **Step 1: Write the failing test in `apps/extract/tests/test_routing.py`**

```python
"""Tests for extract.routing — model→queue map."""
from __future__ import annotations

import pytest

from extract.prompts import SUPPORTED_OLLAMA_MODELS
from extract.routing import MODEL_TO_QUEUE, queue_for_model


def test_every_model_has_a_queue():
    for model in SUPPORTED_OLLAMA_MODELS:
        assert model in MODEL_TO_QUEUE


def test_queue_names_are_unique():
    assert len(set(MODEL_TO_QUEUE.values())) == len(MODEL_TO_QUEUE)


def test_queue_names_are_lowercase_and_dot_safe():
    for q in MODEL_TO_QUEUE.values():
        assert q == q.lower()
        assert ":" not in q
        assert "." not in q
        assert q.startswith("q.extract.") is False  # raw value
        # we keep the prefix off the map; queue_for_model prepends it


def test_queue_for_model_prefixes_correctly():
    assert queue_for_model("qwen3:8b") == "q.extract.qwen3_8b"
    assert queue_for_model("medgemma:27b") == "q.extract.medgemma_27b"
    assert queue_for_model("deepseek-r1:32b") == "q.extract.deepseek_r1_32b"
    assert queue_for_model("llama3.1:8b") == "q.extract.llama3_1_8b"


def test_queue_for_unknown_model_raises():
    with pytest.raises(KeyError):
        queue_for_model("gpt-99:1t")
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
poetry run pytest apps/extract/tests/test_routing.py -v
```

Expected:
```
ImportError: cannot import name 'MODEL_TO_QUEUE' from 'extract.routing'
```

- [ ] **Step 3: Implement `apps/extract/routing.py`**

```python
"""Per-model Celery queue routing.

Per spec §6 (Celery topology), each Ollama model gets its own queue
``q.extract.<slug>`` and its own concurrency-1 worker process. The
slug is the model id with ``:`` and ``.`` and ``-`` collapsed into
``_`` so it's safe in queue names, container names, and Django
settings keys.
"""
from __future__ import annotations

from extract.prompts import SUPPORTED_OLLAMA_MODELS

_QUEUE_PREFIX = "q.extract."


def _slugify(model_id: str) -> str:
    return (
        model_id.lower()
        .replace(":", "_")
        .replace(".", "_")
        .replace("-", "_")
    )


MODEL_TO_QUEUE: dict[str, str] = {m: _slugify(m) for m in SUPPORTED_OLLAMA_MODELS}


def queue_for_model(model: str) -> str:
    """Full Celery queue name (with prefix). Raises KeyError on unknown."""
    return _QUEUE_PREFIX + MODEL_TO_QUEUE[model]
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
poetry run pytest apps/extract/tests/test_routing.py -v
```

Expected:
```
5 passed
```

- [ ] **Step 5: Commit**

```bash
git add apps/extract/routing.py apps/extract/tests/test_routing.py
git commit -m "feat(extract): add model→queue routing map"
```

---

## Task 8: `extract.services.upsert_runs_for_chunk` (TDD)

The fan-out step needs to idempotently create the seven `ExtractionRun(chunk, model_name, prompt_version)` rows for a chunk. We isolate this in `services.py` so both the Beat-fired enqueuer and the smoke task can call it.

**Files:**
- Create: `apps/extract/services.py`
- Create: `apps/extract/tests/test_services.py`

- [ ] **Step 1: Write the failing test in `apps/extract/tests/test_services.py`**

```python
"""Tests for extract.services."""
from __future__ import annotations

import pytest

from extract.models import ExtractionRun, PromptTemplate
from extract.services import (
    active_prompt_version,
    build_prompt_text,
    upsert_runs_for_chunk,
)


@pytest.fixture
def prompt(db):
    return PromptTemplate.objects.create(version="9.9.9", body="say {{CHUNK_TEXT}}", is_active=True)


@pytest.fixture
def chunk(db):
    from corpus.models import Paper
    from papers.models import Chunk, Section

    paper = Paper.objects.create(pmid="11111111", title="t", abstract="a")
    section = Section.objects.create(paper=paper, doco_type="Results", order=0)
    return Chunk.objects.create(section=section, text="A activates B.", order=0, token_count=4)


def test_upsert_creates_seven_runs(db, prompt, chunk):
    n = upsert_runs_for_chunk(chunk.id)
    assert n == 7
    assert ExtractionRun.objects.filter(chunk=chunk).count() == 7


def test_upsert_is_idempotent(db, prompt, chunk):
    upsert_runs_for_chunk(chunk.id)
    upsert_runs_for_chunk(chunk.id)
    assert ExtractionRun.objects.filter(chunk=chunk).count() == 7


def test_upsert_uses_active_prompt_version(db, prompt, chunk):
    upsert_runs_for_chunk(chunk.id)
    versions = set(
        ExtractionRun.objects.filter(chunk=chunk).values_list("prompt_version", flat=True)
    )
    assert versions == {"9.9.9"}


def test_upsert_covers_every_supported_model(db, prompt, chunk):
    from extract.prompts import SUPPORTED_OLLAMA_MODELS

    upsert_runs_for_chunk(chunk.id)
    models = set(
        ExtractionRun.objects.filter(chunk=chunk).values_list("model_name", flat=True)
    )
    assert models == set(SUPPORTED_OLLAMA_MODELS)


def test_active_prompt_version_returns_string(db, prompt):
    assert active_prompt_version() == "9.9.9"


def test_build_prompt_text_renders_with_chunk(db, prompt):
    text = build_prompt_text("IL1B activates MMP13.")
    assert "IL1B activates MMP13." in text


def test_active_prompt_version_raises_when_no_active(db):
    PromptTemplate.objects.all().update(is_active=False)
    with pytest.raises(RuntimeError):
        active_prompt_version()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
poetry run pytest apps/extract/tests/test_services.py -v
```

Expected:
```
ImportError: cannot import name 'upsert_runs_for_chunk' from 'extract.services'
```

- [ ] **Step 3: Implement `apps/extract/services.py`**

```python
"""extract — public service API.

Other apps must call these functions for writes; never reach into
``extract.models`` directly. This is the boundary discipline of spec §2.
"""
from __future__ import annotations

from django.db import transaction

from extract.models import ExtractionRun, PromptTemplate
from extract.prompts import SUPPORTED_OLLAMA_MODELS, render_prompt


def active_prompt_version() -> str:
    """Return the version string of the currently-active PromptTemplate.

    Raises ``RuntimeError`` if no active prompt exists; the seed
    migration ``0002_seed_prompt`` ensures this can only happen if an
    operator manually deactivated every prompt without activating a new
    one.
    """
    try:
        return PromptTemplate.objects.values_list("version", flat=True).get(is_active=True)
    except PromptTemplate.DoesNotExist as exc:
        raise RuntimeError("no active PromptTemplate; check seed migration") from exc


def build_prompt_text(chunk_text: str) -> str:
    """Render the active prompt with the given chunk text."""
    active = PromptTemplate.objects.get(is_active=True)
    return active.body.replace("{{CHUNK_TEXT}}", chunk_text) if "{{CHUNK_TEXT}}" in active.body else render_prompt(chunk_text)


@transaction.atomic
def upsert_runs_for_chunk(chunk_id: int) -> int:
    """Create the seven ExtractionRun rows for ``chunk_id`` if missing.

    Returns the count of rows that exist after the operation (always 7,
    barring a row that already advanced to ``done`` under an earlier
    prompt version — those are left untouched). The operation is
    idempotent: re-running it never creates duplicates.
    """
    version = active_prompt_version()
    for model_name in SUPPORTED_OLLAMA_MODELS:
        ExtractionRun.objects.get_or_create(
            chunk_id=chunk_id,
            model_name=model_name,
            prompt_version=version,
        )
    return ExtractionRun.objects.filter(
        chunk_id=chunk_id, prompt_version=version
    ).count()
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
poetry run pytest apps/extract/tests/test_services.py -v
```

Expected:
```
7 passed
```

- [ ] **Step 5: Commit**

```bash
git add apps/extract/services.py apps/extract/tests/test_services.py
git commit -m "feat(extract): add upsert_runs_for_chunk and prompt helpers"
```

---

## Task 9: Ollama rate-limit bucket (TDD)

Per spec §6 ("rate limits") and the task context, the Phase 1 `schedule` app already supplies `RateLimitBucket(provider, capacity, refill_per_sec, current_tokens, updated_at)` and the `@require_token` decorator. Phase 2 only adds the new `Ollama` row via a data migration, plus a token cost convention.

**Files:**
- Create: `apps/schedule/migrations/0002_ollama_bucket.py` (numbered after Phase 1's `0001_initial`)
- Create: `apps/extract/tests/test_rate_limit_integration.py`

> **If Phase 1 numbering already used `0002_*`, bump this migration to `0003_ollama_bucket.py`. The data-migration body is unaffected.**

- [ ] **Step 1: Create `apps/schedule/migrations/0002_ollama_bucket.py`**

```python
"""Seed the Ollama RateLimitBucket row.

Per spec §6 (rate limits): every outbound provider gets a token-bucket
persisted in Postgres. Phase 1 introduced the model and the NCBI /
Europe PMC / PubTator3 buckets; Phase 2 adds Ollama.

Capacity 16 / refill 8 per second:
  • Eight is two model-loads' worth of concurrent /api/generate
    (matches OLLAMA_MAX_LOADED_MODELS=2, per spec §6).
  • The capacity of 16 gives headroom for a burst from the
    enqueuer fan-out without immediately starving.
"""
from __future__ import annotations

from django.db import migrations


def seed(apps, schema_editor) -> None:
    Bucket = apps.get_model("schedule", "RateLimitBucket")
    Bucket.objects.update_or_create(
        provider="ollama",
        defaults={
            "capacity": 16,
            "refill_per_sec": 8.0,
            "current_tokens": 16.0,
        },
    )


def unseed(apps, schema_editor) -> None:
    Bucket = apps.get_model("schedule", "RateLimitBucket")
    Bucket.objects.filter(provider="ollama").delete()


class Migration(migrations.Migration):
    dependencies = [("schedule", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
```

- [ ] **Step 2: Write the integration test in `apps/extract/tests/test_rate_limit_integration.py`**

```python
"""Test the Ollama RateLimitBucket migration seeded the row correctly."""
from __future__ import annotations

import pytest

from schedule.models import RateLimitBucket


@pytest.mark.django_db
def test_ollama_bucket_seeded():
    bucket = RateLimitBucket.objects.get(provider="ollama")
    assert bucket.capacity == 16
    assert bucket.refill_per_sec == pytest.approx(8.0)


@pytest.mark.django_db
def test_ollama_bucket_starts_full():
    bucket = RateLimitBucket.objects.get(provider="ollama")
    assert bucket.current_tokens == pytest.approx(16.0)
```

- [ ] **Step 3: Apply the migration**

```bash
poetry run python manage.py migrate schedule
```

Expected (final line):
```
  Applying schedule.0002_ollama_bucket... OK
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
poetry run pytest apps/extract/tests/test_rate_limit_integration.py -v
```

Expected:
```
2 passed
```

- [ ] **Step 5: Commit**

```bash
git add apps/schedule/migrations/0002_ollama_bucket.py apps/extract/tests/test_rate_limit_integration.py
git commit -m "feat(schedule): seed Ollama RateLimitBucket"
```

---

## Task 10: `extract.tasks.run_ppi` (TDD)

This is the Phase 2 centrepiece. One Celery task per `(chunk × model)` per spec §4. It:
1. Loads the `ExtractionRun` row (idempotency check on `status == 'done'`).
2. Marks `status='running'`, sets `heartbeat`, increments `attempts`.
3. Renders the active prompt with the chunk text.
4. Calls `OllamaClient.generate(..., json_schema=PPI_JSON_SCHEMA, keep_alive=settings.OLLAMA_KEEP_ALIVE)`.
5. Parses the response through `PPIExtractionResponse`.
6. Bulk-inserts `RawPPI` rows.
7. Marks `status='done'`, sets `finished_at`, `duration_ms`, `response_tokens`.
On exception: `status='failed'`, `error=str(exc)`.

Wrapped in:
- `@require_token("ollama", cost=1)` (Phase 1 decorator)
- `@with_heartbeat(interval_sec=30, fetch=...)` (Task 6)

**Files:**
- Create: `apps/extract/tasks.py`
- Create: `apps/extract/tests/test_tasks_run_ppi.py`

- [ ] **Step 1: Write the failing test in `apps/extract/tests/test_tasks_run_ppi.py`**

```python
"""Tests for extract.tasks.run_ppi — the per-(chunk, model) extractor task."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from extract.models import ExtractionRun, PromptTemplate, RawPPI
from extract.tasks import run_ppi


@pytest.fixture
def prompt(db):
    return PromptTemplate.objects.create(version="1.0.0", body="p {{CHUNK_TEXT}}", is_active=True)


@pytest.fixture
def chunk(db):
    from corpus.models import Paper
    from papers.models import Chunk, Section

    paper = Paper.objects.create(pmid="22222222", title="t", abstract="a")
    section = Section.objects.create(paper=paper, doco_type="Results", order=0)
    return Chunk.objects.create(
        section=section,
        text="IL1B activates MMP13.",
        order=0,
        token_count=4,
    )


@pytest.fixture
def run(db, prompt, chunk):
    return ExtractionRun.objects.create(
        chunk=chunk, model_name="qwen3:8b", prompt_version="1.0.0"
    )


@pytest.fixture
def mock_ollama_response():
    response_text = json.dumps({
        "ppis": [
            {
                "subject": "IL1B",
                "object": "MMP13",
                "relation": "activates",
                "evidence_span": "IL1B activates MMP13.",
                "evidence_offset_start": 0,
                "evidence_offset_end": 21,
                "cell_type": None,
                "stimulus": None,
                "confidence": 0.91,
            }
        ]
    })
    return response_text, -0.13, 50


def test_run_ppi_marks_run_done(db, run, mock_ollama_response):
    with patch("extract.tasks._ollama_generate", return_value=mock_ollama_response):
        run_ppi(row_id=run.id)
    run.refresh_from_db()
    assert run.status == ExtractionRun.Status.DONE


def test_run_ppi_creates_raw_ppi_rows(db, run, mock_ollama_response):
    with patch("extract.tasks._ollama_generate", return_value=mock_ollama_response):
        run_ppi(row_id=run.id)
    assert RawPPI.objects.filter(run=run).count() == 1
    ppi = RawPPI.objects.get(run=run)
    assert ppi.subject == "IL1B"
    assert ppi.relation_logprob == pytest.approx(-0.13)


def test_run_ppi_records_timing(db, run, mock_ollama_response):
    with patch("extract.tasks._ollama_generate", return_value=mock_ollama_response):
        run_ppi(row_id=run.id)
    run.refresh_from_db()
    assert run.started_at is not None
    assert run.finished_at is not None
    assert run.duration_ms is not None
    assert run.response_tokens == 50


def test_run_ppi_increments_attempts(db, run, mock_ollama_response):
    assert run.attempts == 0
    with patch("extract.tasks._ollama_generate", return_value=mock_ollama_response):
        run_ppi(row_id=run.id)
    run.refresh_from_db()
    assert run.attempts == 1


def test_run_ppi_idempotent_when_already_done(db, run, mock_ollama_response):
    run.status = ExtractionRun.Status.DONE
    run.save()
    with patch("extract.tasks._ollama_generate", return_value=mock_ollama_response) as m:
        run_ppi(row_id=run.id)
    m.assert_not_called()
    assert RawPPI.objects.filter(run=run).count() == 0


def test_run_ppi_marks_failed_on_exception(db, run):
    from core.ollama import OllamaError

    with patch("extract.tasks._ollama_generate", side_effect=OllamaError("503")):
        run_ppi(row_id=run.id)
    run.refresh_from_db()
    assert run.status == ExtractionRun.Status.FAILED
    assert "503" in run.error


def test_run_ppi_marks_failed_on_invalid_response(db, run):
    with patch("extract.tasks._ollama_generate", return_value=("not json", None, 0)):
        run_ppi(row_id=run.id)
    run.refresh_from_db()
    assert run.status == ExtractionRun.Status.FAILED


def test_run_ppi_handles_empty_ppi_list(db, run):
    response_text = json.dumps({"ppis": []})
    with patch(
        "extract.tasks._ollama_generate",
        return_value=(response_text, None, 12),
    ):
        run_ppi(row_id=run.id)
    run.refresh_from_db()
    assert run.status == ExtractionRun.Status.DONE
    assert RawPPI.objects.filter(run=run).count() == 0
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
poetry run pytest apps/extract/tests/test_tasks_run_ppi.py -v
```

Expected:
```
ImportError: cannot import name 'run_ppi' from 'extract.tasks'
```

- [ ] **Step 3: Implement `apps/extract/tasks.py`**

```python
"""extract Celery tasks.

  • ``run_ppi(row_id)``          — one per Ollama queue. Runs an
                                   ExtractionRun against its model and
                                   persists RawPPI rows.
  • ``enqueue_pending_chunks()`` — Beat-fired fan-out: find unprocessed
                                   (Chunk × Model) pairs and route each
                                   to its model's queue.
  • ``smoke_all_models(chunk_id)`` — end-to-end Phase 2 verification.

Per spec §4 / §6 / §8.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.heartbeat import with_heartbeat
from core.ollama import OllamaClient, OllamaError, parse_json_response
from extract.models import ExtractionRun, RawPPI
from extract.prompts import SUPPORTED_OLLAMA_MODELS
from extract.routing import queue_for_model
from extract.schemas import PPI_JSON_SCHEMA, AllowedRelation, PPIExtractionResponse
from extract.services import build_prompt_text, upsert_runs_for_chunk

logger = logging.getLogger(__name__)

_ALLOWED_RELATIONS = tuple(r.value for r in AllowedRelation)


def _ollama_generate(
    *, model: str, prompt: str
) -> tuple[str, float | None, int]:
    """Indirection so tests can patch the Ollama call cleanly.

    Constructs a fresh client per task because workers have
    concurrency=1 and tasks are infrequent enough that connection
    reuse across tasks isn't worth carrying global state.
    """
    client = OllamaClient(
        base_url=settings.OLLAMA_BASE,
        session_cookie=settings.OLLAMA_SESSION_COOKIE,
    )
    try:
        return client.generate(
            model=model,
            prompt=prompt,
            json_schema=PPI_JSON_SCHEMA,
            keep_alive=settings.OLLAMA_KEEP_ALIVE,
            allowed_relations=_ALLOWED_RELATIONS,
        )
    finally:
        client.close()


def _fetch_run(row_id: int) -> ExtractionRun:
    return ExtractionRun.objects.select_related("chunk").get(id=row_id)


@shared_task(
    bind=True,
    autoretry_for=(OllamaError,),
    retry_backoff=10,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=3,
)
@with_heartbeat(interval_sec=30, fetch=_fetch_run)
def run_ppi(self, row_id: int) -> str:  # type: ignore[no-untyped-def]
    """Execute one (chunk × model) extraction.

    Idempotent: if ``status == 'done'`` the task short-circuits.
    """
    run = _fetch_run(row_id)
    if run.status == ExtractionRun.Status.DONE:
        return "already_done"

    run.status = ExtractionRun.Status.RUNNING
    run.started_at = timezone.now()
    run.attempts = run.attempts + 1
    run.error = ""
    run.save(update_fields=["status", "started_at", "attempts", "error"])

    prompt_text = build_prompt_text(run.chunk.text)
    t0 = time.monotonic()
    try:
        response_text, relation_logprob, eval_count = _ollama_generate(
            model=run.model_name, prompt=prompt_text
        )
        parsed: dict[str, Any] = parse_json_response(response_text)
        validated = PPIExtractionResponse.model_validate(parsed)
    except (OllamaError, ValueError, json.JSONDecodeError, Exception) as exc:
        # Pydantic ValidationError is a subclass of ValueError; JSON
        # decode raises JSONDecodeError; OllamaError after retries
        # surfaces here too.
        run.status = ExtractionRun.Status.FAILED
        run.error = f"{type(exc).__name__}: {exc}"[:2000]
        run.finished_at = timezone.now()
        run.duration_ms = int((time.monotonic() - t0) * 1000)
        run.save(update_fields=["status", "error", "finished_at", "duration_ms"])
        logger.warning("run_ppi failed run_id=%d: %s", row_id, run.error)
        return "failed"

    raw_rows = [
        RawPPI(
            run=run,
            subject=p.subject,
            object=p.object,
            relation=p.relation.value,
            evidence_span=p.evidence_span,
            evidence_offset_start=p.evidence_offset_start,
            evidence_offset_end=p.evidence_offset_end,
            cell_type=p.cell_type,
            stimulus=p.stimulus,
            confidence=p.confidence,
            relation_logprob=relation_logprob,
        )
        for p in validated.ppis
    ]
    with transaction.atomic():
        if raw_rows:
            RawPPI.objects.bulk_create(raw_rows)
        run.status = ExtractionRun.Status.DONE
        run.finished_at = timezone.now()
        run.duration_ms = int((time.monotonic() - t0) * 1000)
        run.response_tokens = eval_count
        run.save(
            update_fields=[
                "status", "finished_at", "duration_ms", "response_tokens"
            ]
        )
    return "done"


@shared_task
def enqueue_pending_chunks(batch_size: int = 200) -> dict[str, int]:
    """Beat-fired fan-out (every 5 min per spec §6 Beat schedule).

    Finds Chunks that haven't been run against every model with the
    active prompt, creates the missing ExtractionRun rows, and routes a
    Celery message per row to its model's queue.

    Returns a dict ``{model_name: count_enqueued}`` for logging.
    """
    from papers.models import Chunk
    from extract.services import active_prompt_version

    version = active_prompt_version()
    enqueued: dict[str, int] = {m: 0 for m in SUPPORTED_OLLAMA_MODELS}

    # Find chunks that are still missing at least one extraction run
    # for the active prompt version. Limit to ``batch_size`` to keep
    # the Beat tick bounded.
    candidate_chunks = (
        Chunk.objects.filter(section__doco_type="Results")
        .exclude(
            extraction_runs__prompt_version=version,
            extraction_runs__status__in=[
                ExtractionRun.Status.DONE,
                ExtractionRun.Status.RUNNING,
            ],
        )
        .order_by("id")[:batch_size]
    )

    for chunk in candidate_chunks:
        upsert_runs_for_chunk(chunk.id)
        runs = ExtractionRun.objects.filter(
            chunk=chunk,
            prompt_version=version,
            status=ExtractionRun.Status.QUEUED,
        )
        for run in runs:
            run_ppi.apply_async(
                kwargs={"row_id": run.id},
                queue=queue_for_model(run.model_name),
            )
            enqueued[run.model_name] += 1

    logger.info("enqueue_pending_chunks dispatched: %s", enqueued)
    return enqueued


@shared_task
def smoke_all_models(chunk_id: int) -> dict[str, Any]:
    """End-to-end smoke test (Task 14 acceptance criterion).

    Synchronously dispatches the same chunk to all 7 model queues and
    waits for results. Returns per-model RawPPI counts.
    """
    upsert_runs_for_chunk(chunk_id)
    from extract.services import active_prompt_version

    version = active_prompt_version()
    async_results = []
    for model in SUPPORTED_OLLAMA_MODELS:
        run = ExtractionRun.objects.get(
            chunk_id=chunk_id, model_name=model, prompt_version=version
        )
        ar = run_ppi.apply_async(
            kwargs={"row_id": run.id}, queue=queue_for_model(model)
        )
        async_results.append((model, ar))

    counts: dict[str, int] = {}
    for model, ar in async_results:
        try:
            ar.get(timeout=600)
        except Exception as exc:
            logger.warning("smoke model=%s raised: %s", model, exc)
        counts[model] = RawPPI.objects.filter(
            run__chunk_id=chunk_id,
            run__model_name=model,
            run__prompt_version=version,
        ).count()
    return counts
```

- [ ] **Step 4: Add `OLLAMA_KEEP_ALIVE`, `OLLAMA_SESSION_COOKIE` to settings**

Edit `interactome/settings/base.py`. Below the existing `CELERY_TASK_SOFT_TIME_LIMIT = 60 * 50` line add:

```python
# Ollama gateway
OLLAMA_BASE = os.environ.get("OLLAMA_BASE", "https://ollama.simbiosys.sb.upf.edu")
OLLAMA_KEEP_ALIVE = os.environ.get("OLLAMA_KEEP_ALIVE", "2h")
OLLAMA_MAX_LOADED_MODELS = int(os.environ.get("OLLAMA_MAX_LOADED_MODELS", "2"))
OLLAMA_SESSION_COOKIE = os.environ.get("OLLAMA_SESSION_COOKIE", "")
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
poetry run pytest apps/extract/tests/test_tasks_run_ppi.py -v
```

Expected:
```
8 passed
```

- [ ] **Step 6: Commit**

```bash
git add apps/extract/tasks.py apps/extract/tests/test_tasks_run_ppi.py interactome/settings/base.py
git commit -m "feat(extract): add run_ppi task with schema-constrained Ollama call"
```

---

## Task 11: `extract.tasks.enqueue_pending_chunks` integration test (TDD)

Task 10 implemented the fan-out task; this task gives it the integration test it deserves.

**Files:**
- Create: `apps/extract/tests/test_tasks_enqueue.py`

- [ ] **Step 1: Write the test**

```python
"""Tests for extract.tasks.enqueue_pending_chunks — Beat fan-out."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from extract.models import ExtractionRun, PromptTemplate
from extract.prompts import SUPPORTED_OLLAMA_MODELS
from extract.tasks import enqueue_pending_chunks


@pytest.fixture
def prompt(db):
    return PromptTemplate.objects.create(version="1.0.0", body="p {{CHUNK_TEXT}}", is_active=True)


@pytest.fixture
def two_chunks(db, prompt):
    from corpus.models import Paper
    from papers.models import Chunk, Section

    paper = Paper.objects.create(pmid="33333333", title="t", abstract="a")
    section = Section.objects.create(paper=paper, doco_type="Results", order=0)
    return [
        Chunk.objects.create(section=section, text=f"chunk-{i}", order=i, token_count=4)
        for i in range(2)
    ]


def test_enqueue_creates_runs_for_every_chunk_model_pair(db, two_chunks):
    with patch("extract.tasks.run_ppi.apply_async") as m:
        result = enqueue_pending_chunks()
    # 2 chunks × 7 models
    assert ExtractionRun.objects.count() == 14
    assert m.call_count == 14
    assert sum(result.values()) == 14


def test_enqueue_routes_each_model_to_its_queue(db, two_chunks):
    queues_used: list[str] = []
    with patch("extract.tasks.run_ppi.apply_async") as m:
        enqueue_pending_chunks()
    for call in m.call_args_list:
        queues_used.append(call.kwargs["queue"])

    # 2 messages per model
    from collections import Counter
    counts = Counter(queues_used)
    for model in SUPPORTED_OLLAMA_MODELS:
        slug = (
            model.lower()
            .replace(":", "_")
            .replace(".", "_")
            .replace("-", "_")
        )
        assert counts[f"q.extract.{slug}"] == 2


def test_enqueue_is_idempotent(db, two_chunks):
    with patch("extract.tasks.run_ppi.apply_async"):
        enqueue_pending_chunks()
    n_before = ExtractionRun.objects.count()
    with patch("extract.tasks.run_ppi.apply_async") as m:
        enqueue_pending_chunks()
    # No new ExtractionRun rows; messages still re-dispatched for queued
    # rows (which is correct — janitor / Celery will dedupe via idempotent task).
    assert ExtractionRun.objects.count() == n_before


def test_enqueue_skips_chunks_already_processed_by_all_models(db, two_chunks):
    """When every (chunk, model) pair has status=done, dispatch nothing."""
    from extract.services import upsert_runs_for_chunk

    for chunk in two_chunks:
        upsert_runs_for_chunk(chunk.id)
    ExtractionRun.objects.update(status=ExtractionRun.Status.DONE)

    with patch("extract.tasks.run_ppi.apply_async") as m:
        enqueue_pending_chunks()
    assert m.call_count == 0


def test_enqueue_only_targets_results_sections(db, prompt):
    from corpus.models import Paper
    from papers.models import Chunk, Section

    paper = Paper.objects.create(pmid="44444444", title="t", abstract="a")
    intro = Section.objects.create(paper=paper, doco_type="Introduction", order=0)
    results = Section.objects.create(paper=paper, doco_type="Results", order=1)
    Chunk.objects.create(section=intro, text="ignored", order=0, token_count=4)
    Chunk.objects.create(section=results, text="extracted", order=0, token_count=4)

    with patch("extract.tasks.run_ppi.apply_async") as m:
        enqueue_pending_chunks()
    assert m.call_count == 7  # one Results chunk × 7 models
```

- [ ] **Step 2: Run the test**

```bash
poetry run pytest apps/extract/tests/test_tasks_enqueue.py -v
```

Expected:
```
5 passed
```

- [ ] **Step 3: Commit**

```bash
git add apps/extract/tests/test_tasks_enqueue.py
git commit -m "test(extract): integration tests for enqueue_pending_chunks fan-out"
```

---

## Task 12: Wire Beat schedule for `enqueue_pending_chunks`

Per spec §6 Beat schedule: `extract.enqueue_pending_chunks` runs every 5 min.

**Files:**
- Modify: `interactome/settings/base.py`

- [ ] **Step 1: Append the Beat schedule entry**

Edit `interactome/settings/base.py`. After the new `OLLAMA_*` settings block from Task 10, add:

```python
# Celery Beat — periodic tasks.
# Per spec §6 the Beat schedule fires:
#   • schedule.janitor_reset_stale_running every 5 min (Phase 1)
#   • extract.enqueue_pending_chunks      every 5 min (Phase 2 — this entry)
# Other entries (corpus.refresh_pubmed, papers.classify_pending, etc.)
# are added in their owning phases.
from celery.schedules import crontab  # noqa: E402

CELERY_BEAT_SCHEDULE = {
    **globals().get("CELERY_BEAT_SCHEDULE", {}),
    "extract.enqueue_pending_chunks": {
        "task": "extract.tasks.enqueue_pending_chunks",
        "schedule": crontab(minute="*/5"),
        "options": {"queue": "q.io"},
    },
}
```

(The `**globals().get(...)` merge means Phase 1's Beat entries — if any — are preserved.)

- [ ] **Step 2: Verify Django still boots**

```bash
poetry run python manage.py check
```

Expected:
```
System check identified no issues (0 silenced).
```

- [ ] **Step 3: Commit**

```bash
git add interactome/settings/base.py
git commit -m "feat(extract): schedule enqueue_pending_chunks every 5 minutes"
```

---

## Task 13: Janitor sweep registration

Per the task context: "the janitor task already exists in Phase 1; this phase adds the `ExtractionRun.status` model class to its sweep list. Don't reimplement — show only the diff/addition."

**Files:**
- Modify: `apps/schedule/janitor.py`
- Modify: `apps/schedule/tests/test_janitor.py`

> The Phase 1 implementation is expected to look like:
> ```python
> # apps/schedule/janitor.py
> SWEEP_MODELS: list[tuple[type[models.Model], int]] = [
>     # (model_class, stale_threshold_minutes)
>     (Paper, 10),
> ]
> ```
> If Phase 1 used a different structure, adapt the additions below to match.

- [ ] **Step 1: Add `ExtractionRun` to the sweep list**

Edit `apps/schedule/janitor.py`. Add the import near the top:

```python
from extract.models import ExtractionRun
```

In the `SWEEP_MODELS` registration:

```python
SWEEP_MODELS: list[tuple[type[models.Model], int]] = [
    (Paper, 10),
    (ExtractionRun, 10),  # Phase 2: extraction runs use the same 10-min stale threshold (spec §8)
]
```

- [ ] **Step 2: Extend the janitor test**

Edit `apps/schedule/tests/test_janitor.py`. Add at the bottom:

```python
def test_janitor_resets_stale_extractionrun(db):
    """Phase 2 wiring: stale-running ExtractionRun rows must be re-queued."""
    from datetime import timedelta
    from django.utils import timezone

    from corpus.models import Paper
    from papers.models import Chunk, Section
    from extract.models import ExtractionRun, PromptTemplate
    from schedule.tasks import janitor_reset_stale_running

    PromptTemplate.objects.update_or_create(
        version="1.0.0", defaults={"body": "{{CHUNK_TEXT}}", "is_active": True}
    )
    paper = Paper.objects.create(pmid="55555555", title="t", abstract="a")
    section = Section.objects.create(paper=paper, doco_type="Results", order=0)
    chunk = Chunk.objects.create(section=section, text="x", order=0, token_count=1)
    run = ExtractionRun.objects.create(
        chunk=chunk, model_name="qwen3:8b", prompt_version="1.0.0",
        status=ExtractionRun.Status.RUNNING,
        heartbeat=timezone.now() - timedelta(minutes=15),
    )

    janitor_reset_stale_running()

    run.refresh_from_db()
    assert run.status == ExtractionRun.Status.QUEUED
    assert run.attempts == 1  # incremented by janitor
```

- [ ] **Step 3: Run the test**

```bash
poetry run pytest apps/schedule/tests/test_janitor.py -v
```

Expected:
```
... test_janitor_resets_stale_extractionrun PASSED
```

If existing Phase 1 janitor tests fail because Phase 2 added a model the test fixture doesn't expect, fix the fixture rather than the production code.

- [ ] **Step 4: Commit**

```bash
git add apps/schedule/janitor.py apps/schedule/tests/test_janitor.py
git commit -m "feat(schedule): add ExtractionRun to janitor sweep list"
```

---

## Task 14: Seven per-model Celery worker services in `docker-compose.yml`

Per spec §6: seven `worker_extract_<model>` services, each concurrency 1, each bound to one queue. Ollama env vars (`OLLAMA_KEEP_ALIVE=2h`, `OLLAMA_MAX_LOADED_MODELS=2`) propagated.

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example`

- [ ] **Step 1: Append the seven worker services to `docker-compose.yml`**

Open `docker-compose.yml`. After the existing `worker_io:` block (which Phase 0 created), add:

```yaml
  # === Phase 2: per-model extractor workers ===
  # Per spec §6, each Ollama model gets its own dedicated worker with
  # concurrency=1 so the GPU box doesn't thrash through mmap/munmap as
  # Ollama swaps weight files. Combined with OLLAMA_KEEP_ALIVE=2h and
  # OLLAMA_MAX_LOADED_MODELS=2, two models stay resident; the other
  # five queues accumulate; Ollama rotates models in as VRAM frees.

  worker_extract_medgemma_27b:
    image: interactome:dev
    restart: unless-stopped
    env_file: .env
    environment:
      OLLAMA_KEEP_ALIVE: ${OLLAMA_KEEP_ALIVE:-2h}
      OLLAMA_MAX_LOADED_MODELS: ${OLLAMA_MAX_LOADED_MODELS:-2}
    depends_on:
      web:
        condition: service_healthy
    command: celery -A interactome worker -Q q.extract.medgemma_27b -c 1 -n m@%h -l info

  worker_extract_phi4_14b:
    image: interactome:dev
    restart: unless-stopped
    env_file: .env
    environment:
      OLLAMA_KEEP_ALIVE: ${OLLAMA_KEEP_ALIVE:-2h}
      OLLAMA_MAX_LOADED_MODELS: ${OLLAMA_MAX_LOADED_MODELS:-2}
    depends_on:
      web:
        condition: service_healthy
    command: celery -A interactome worker -Q q.extract.phi4_14b -c 1 -n p@%h -l info

  worker_extract_qwen3_8b:
    image: interactome:dev
    restart: unless-stopped
    env_file: .env
    environment:
      OLLAMA_KEEP_ALIVE: ${OLLAMA_KEEP_ALIVE:-2h}
      OLLAMA_MAX_LOADED_MODELS: ${OLLAMA_MAX_LOADED_MODELS:-2}
    depends_on:
      web:
        condition: service_healthy
    command: celery -A interactome worker -Q q.extract.qwen3_8b -c 1 -n q@%h -l info

  worker_extract_gemma3_12b:
    image: interactome:dev
    restart: unless-stopped
    env_file: .env
    environment:
      OLLAMA_KEEP_ALIVE: ${OLLAMA_KEEP_ALIVE:-2h}
      OLLAMA_MAX_LOADED_MODELS: ${OLLAMA_MAX_LOADED_MODELS:-2}
    depends_on:
      web:
        condition: service_healthy
    command: celery -A interactome worker -Q q.extract.gemma3_12b -c 1 -n g@%h -l info

  worker_extract_deepseek_r1_32b:
    image: interactome:dev
    restart: unless-stopped
    env_file: .env
    environment:
      OLLAMA_KEEP_ALIVE: ${OLLAMA_KEEP_ALIVE:-2h}
      OLLAMA_MAX_LOADED_MODELS: ${OLLAMA_MAX_LOADED_MODELS:-2}
    depends_on:
      web:
        condition: service_healthy
    command: celery -A interactome worker -Q q.extract.deepseek_r1_32b -c 1 -n d@%h -l info

  worker_extract_devstral_24b:
    image: interactome:dev
    restart: unless-stopped
    env_file: .env
    environment:
      OLLAMA_KEEP_ALIVE: ${OLLAMA_KEEP_ALIVE:-2h}
      OLLAMA_MAX_LOADED_MODELS: ${OLLAMA_MAX_LOADED_MODELS:-2}
    depends_on:
      web:
        condition: service_healthy
    command: celery -A interactome worker -Q q.extract.devstral_24b -c 1 -n v@%h -l info

  worker_extract_llama3_1_8b:
    image: interactome:dev
    restart: unless-stopped
    env_file: .env
    environment:
      OLLAMA_KEEP_ALIVE: ${OLLAMA_KEEP_ALIVE:-2h}
      OLLAMA_MAX_LOADED_MODELS: ${OLLAMA_MAX_LOADED_MODELS:-2}
    depends_on:
      web:
        condition: service_healthy
    command: celery -A interactome worker -Q q.extract.llama3_1_8b -c 1 -n l@%h -l info
```

- [ ] **Step 2: Append Ollama env vars to `.env.example`**

Edit `.env.example`. In the `# === External services ===` block, after the existing `OLLAMA_BASE=...` line add:

```bash
OLLAMA_KEEP_ALIVE=2h
OLLAMA_MAX_LOADED_MODELS=2
OLLAMA_SESSION_COOKIE=
```

- [ ] **Step 3: Validate the compose file syntax**

```bash
docker compose config --quiet
```

Expected: command exits 0, no output. (Any YAML or schema error prints here.)

- [ ] **Step 4: Verify all 7 worker services are recognised**

```bash
docker compose config --services | grep '^worker_extract_' | wc -l
```

Expected output:
```
7
```

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml .env.example
git commit -m "build: add 7 per-model Celery worker services for extraction"
```

---

## Task 15: `OLLAMA_SESSION_COOKIE` refresh helper (TDD)

The cluster Ollama gateway sits behind the same Authelia that fronts the Django app. The session cookie in `OLLAMA_SESSION_COOKIE` is long-lived but can expire. We add a small helper that re-authenticates against Authelia's `/api/firstfactor` endpoint using a service-account password, returning a fresh cookie. The OllamaClient calls this on 401 (already plumbed in Task 5).

**Files:**
- Modify: `apps/core/ollama.py`
- Modify: `apps/core/tests/test_ollama.py`

- [ ] **Step 1: Add the test (append to existing `test_ollama.py`)**

```python
def test_authelia_refresh_returns_new_cookie():
    from core.ollama import refresh_authelia_session

    with patch("httpx.post") as p:
        p.return_value = httpx.Response(
            status_code=200,
            request=httpx.Request("POST", "https://auth.example/api/firstfactor"),
            headers={"Set-Cookie": "authelia_session=NEW; Path=/; HttpOnly"},
            content=b'{"status":"OK"}',
        )
        cookie = refresh_authelia_session(
            authelia_url="https://auth.example",
            username="svc-interactome",
            password="hunter2",
        )
    assert cookie == "NEW"


def test_authelia_refresh_raises_on_failure():
    from core.ollama import refresh_authelia_session

    with patch("httpx.post") as p:
        p.return_value = httpx.Response(
            status_code=401,
            request=httpx.Request("POST", "https://auth.example/api/firstfactor"),
            content=b'{"status":"KO"}',
        )
        with pytest.raises(OllamaError):
            refresh_authelia_session(
                authelia_url="https://auth.example",
                username="x", password="y",
            )
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
poetry run pytest apps/core/tests/test_ollama.py -v -k authelia
```

Expected:
```
ImportError: cannot import name 'refresh_authelia_session'
```

- [ ] **Step 3: Add `refresh_authelia_session` to `apps/core/ollama.py`**

At the bottom of the file add:

```python
def refresh_authelia_session(
    *,
    authelia_url: str,
    username: str,
    password: str,
    timeout_sec: float = 15.0,
) -> str:
    """Re-authenticate against Authelia ``/api/firstfactor`` and return
    the new ``authelia_session`` cookie value.

    Spec §1 / §9: same Authelia gateway fronts Ollama. Service-account
    credentials live in ``.env`` (``AUTHELIA_SVC_USER`` /
    ``AUTHELIA_SVC_PASSWORD``); a Django settings reader plumbs them
    into ``OllamaClient(session_refresher=lambda: refresh_authelia_session(...))``.
    """
    response = httpx.post(
        f"{authelia_url.rstrip('/')}/api/firstfactor",
        json={"username": username, "password": password, "keepMeLoggedIn": True},
        timeout=timeout_sec,
    )
    if response.status_code != 200:
        raise OllamaError(
            f"authelia refresh failed: {response.status_code} {response.text[:200]}"
        )
    set_cookie = response.headers.get("Set-Cookie", "")
    for chunk in set_cookie.split(";"):
        chunk = chunk.strip()
        if chunk.startswith("authelia_session="):
            return chunk.split("=", 1)[1]
    raise OllamaError("authelia refresh succeeded but no authelia_session cookie returned")
```

- [ ] **Step 4: Re-run the tests**

```bash
poetry run pytest apps/core/tests/test_ollama.py -v
```

Expected:
```
10 passed
```

- [ ] **Step 5: Wire the refresher in `apps/extract/tasks.py`**

In `_ollama_generate`, replace the `OllamaClient(...)` construction with:

```python
    from core.ollama import refresh_authelia_session

    def _refresher() -> str:
        return refresh_authelia_session(
            authelia_url=settings.AUTHELIA_VERIFY.rsplit("/api/", 1)[0],
            username=settings.AUTHELIA_SVC_USER,
            password=settings.AUTHELIA_SVC_PASSWORD,
        )

    client = OllamaClient(
        base_url=settings.OLLAMA_BASE,
        session_cookie=settings.OLLAMA_SESSION_COOKIE,
        session_refresher=_refresher,
    )
```

And add to `interactome/settings/base.py` (after the existing `OLLAMA_*` block):

```python
AUTHELIA_VERIFY = os.environ.get(
    "AUTHELIA_VERIFY", "https://authelia.simbiosys.sb.upf.edu/api/verify"
)
AUTHELIA_SVC_USER = os.environ.get("AUTHELIA_SVC_USER", "")
AUTHELIA_SVC_PASSWORD = os.environ.get("AUTHELIA_SVC_PASSWORD", "")
```

And to `.env.example` in the `# === External services ===` block:

```bash
AUTHELIA_SVC_USER=svc-interactome
AUTHELIA_SVC_PASSWORD=change-me
```

- [ ] **Step 6: Re-run the broader test suite**

```bash
poetry run pytest apps/extract apps/core -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add apps/core/ollama.py apps/core/tests/test_ollama.py apps/extract/tasks.py interactome/settings/base.py .env.example
git commit -m "feat(core): add Authelia session refresh on Ollama 401"
```

---

## Task 16: Django admin registration

A small operator-comfort task: register the three new models in Django admin so a curator can inspect failed runs without writing SQL.

**Files:**
- Create: `apps/extract/admin.py`

- [ ] **Step 1: Create `apps/extract/admin.py`**

```python
"""Django admin registrations for extract models."""
from __future__ import annotations

from django.contrib import admin

from extract.models import ExtractionRun, PromptTemplate, RawPPI


@admin.register(PromptTemplate)
class PromptTemplateAdmin(admin.ModelAdmin):
    list_display = ("version", "is_active", "updated_at")
    list_filter = ("is_active",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(ExtractionRun)
class ExtractionRunAdmin(admin.ModelAdmin):
    list_display = (
        "id", "chunk_id", "model_name", "prompt_version", "status",
        "attempts", "duration_ms", "updated_at",
    )
    list_filter = ("status", "model_name", "prompt_version")
    search_fields = ("chunk__id", "model_name", "error")
    readonly_fields = (
        "created_at", "updated_at", "started_at", "finished_at",
        "duration_ms", "response_tokens",
    )


@admin.register(RawPPI)
class RawPPIAdmin(admin.ModelAdmin):
    list_display = (
        "id", "run_id", "subject", "relation", "object", "confidence",
        "ungrounded", "created_at",
    )
    list_filter = ("relation", "ungrounded")
    search_fields = ("subject", "object", "evidence_span")
```

- [ ] **Step 2: Verify Django can register them**

```bash
poetry run python manage.py check
```

Expected:
```
System check identified no issues (0 silenced).
```

- [ ] **Step 3: Commit**

```bash
git add apps/extract/admin.py
git commit -m "feat(extract): register models in Django admin"
```

---

## Task 17: Celery task routing config

Per spec §6 the routing is by queue. Without explicit Celery routing config, `apply_async(..., queue=...)` works but task-name-keyed defaults don't. We add a `task_routes` table so that even tasks dispatched via `.delay()` go to the right queue (defensive).

**Files:**
- Modify: `interactome/settings/base.py`

- [ ] **Step 1: Append routing config**

Edit `interactome/settings/base.py`. After the `CELERY_BEAT_SCHEDULE = { ... }` block from Task 12, append:

```python
# Celery task → queue routing (spec §6).
# Per-model run_ppi messages are routed by ``apply_async(queue=...)`` in
# enqueue_pending_chunks; this default catches stragglers and explicit
# .delay() calls.
CELERY_TASK_ROUTES = {
    "extract.tasks.enqueue_pending_chunks": {"queue": "q.io"},
    "extract.tasks.smoke_all_models": {"queue": "q.io"},
    # extract.tasks.run_ppi is routed dynamically by enqueue_pending_chunks;
    # the per-model worker only consumes from its q.extract.<slug>.
}
```

- [ ] **Step 2: Verify settings load**

```bash
poetry run python manage.py check
```

Expected:
```
System check identified no issues (0 silenced).
```

- [ ] **Step 3: Commit**

```bash
git add interactome/settings/base.py
git commit -m "feat(extract): add Celery task routing for enqueue and smoke tasks"
```

---

## Task 18: Live Ollama smoke test (integration; gated)

Per the task context: an end-to-end smoke task that grabs one chunk, runs it through all 7 models, persists `RawPPI`, and verifies the row count is > 0 for at least 5 of 7 models.

Implemented as a marked test that's skipped in CI but runnable manually against the cluster.

**Files:**
- Create: `apps/extract/tests/test_smoke_all_models.py`
- Modify: `pytest.ini` (register the `live` marker)

- [ ] **Step 1: Register the marker in `pytest.ini`**

Edit `pytest.ini`. Below the existing `addopts` line add:

```ini
markers =
    live: integration tests that hit live SIMBIOsys services (Ollama, Authelia). Skipped in CI; run manually.
```

- [ ] **Step 2: Create `apps/extract/tests/test_smoke_all_models.py`**

```python
"""End-to-end smoke test against the live cluster Ollama gateway.

Marked ``live`` — skipped by default. To run:

    poetry run pytest apps/extract/tests/test_smoke_all_models.py -m live -v

Pre-requisites:
  • OLLAMA_BASE / OLLAMA_SESSION_COOKIE (or AUTHELIA_SVC_USER /
    AUTHELIA_SVC_PASSWORD) configured in the running environment
  • All seven worker_extract_* containers running and consuming from
    their queues
  • A Phase 1 chunk in the database (paste a real Results-section
    sentence into ``CHUNK_TEXT`` below before running)
"""
from __future__ import annotations

import pytest

from extract.models import PromptTemplate, RawPPI
from extract.prompts import SUPPORTED_OLLAMA_MODELS
from extract.tasks import smoke_all_models

CHUNK_TEXT = (
    "Stimulation of human nucleus pulposus cells with IL-1β robustly "
    "induced MMP-13 and ADAMTS-5 transcription, an effect that was "
    "abolished by pre-treatment with the IKKβ inhibitor BMS-345541, "
    "confirming NF-κB-dependent transactivation of these catabolic genes."
)


@pytest.mark.live
@pytest.mark.django_db
def test_smoke_all_seven_models_produce_results():
    from corpus.models import Paper
    from papers.models import Chunk, Section

    PromptTemplate.objects.update_or_create(
        version="1.0.0", defaults={"body": "{{CHUNK_TEXT}}", "is_active": True}
    )
    paper = Paper.objects.create(
        pmid="00000001", title="smoke", abstract=CHUNK_TEXT
    )
    section = Section.objects.create(paper=paper, doco_type="Results", order=0)
    chunk = Chunk.objects.create(
        section=section, text=CHUNK_TEXT, order=0, token_count=len(CHUNK_TEXT.split()),
    )

    counts = smoke_all_models(chunk_id=chunk.id)

    print("Per-model RawPPI counts:")
    for model in SUPPORTED_OLLAMA_MODELS:
        print(f"  {model}: {counts.get(model, 0)}")

    models_with_at_least_one = sum(1 for c in counts.values() if c > 0)
    assert models_with_at_least_one >= 5, (
        f"Expected ≥ 5 of 7 models to produce at least one RawPPI; "
        f"got {models_with_at_least_one}. counts={counts}"
    )

    # Sanity: every RawPPI carries IL-1β / NFKB / MMP / ADAMTS adjacent entities
    interesting = RawPPI.objects.filter(run__chunk_id=chunk.id)
    assert interesting.exists()
```

- [ ] **Step 3: Verify the test is collected and skipped without `-m live`**

```bash
poetry run pytest apps/extract/tests/test_smoke_all_models.py -v
```

Expected (since `live` is filtered out by default behaviour in CI; locally the test runs only when explicitly selected with `-m live`):
```
... 1 deselected
```

(If your local pytest is configured to run all markers, the test will execute and require the live cluster — that's the intended behaviour during cluster validation.)

- [ ] **Step 4: Commit**

```bash
git add apps/extract/tests/test_smoke_all_models.py pytest.ini
git commit -m "test(extract): add live end-to-end smoke test for all 7 models"
```

---

## Task 19: End-to-end stack verification

Same shape as Phase 0's Task 14: bring everything up locally, verify the 15-container stack (Phase 0's 8 plus seven extract workers), dispatch the smoke task, confirm row counts.

- [ ] **Step 1: Ensure `.env` has Ollama credentials filled in**

```bash
grep -E '^(OLLAMA_|AUTHELIA_SVC_)' .env
```

Expected: each variable has a non-empty value (the cluster cookie, or `AUTHELIA_SVC_USER`/`PASSWORD` set so the refresher can mint a cookie).

If a fresh `.env` is needed:
```bash
cp .env.example .env
# Edit .env, fill in OLLAMA_BASE, OLLAMA_SESSION_COOKIE
# (or AUTHELIA_SVC_USER + AUTHELIA_SVC_PASSWORD)
```

- [ ] **Step 2: Bring up the stack**

```bash
docker compose up -d
```

- [ ] **Step 3: Verify all 15 services are healthy**

```bash
docker compose ps
```

Expected: the 8 Phase 0 services (caddy, web, beat, worker_io, postgres, redis, minio, grobid) plus the 7 new workers, all `Up` or `Up (healthy)`:

```
NAME                                          STATUS
interactome-beat-1                            Up
interactome-caddy-1                           Up
interactome-grobid-1                          Up (healthy)
interactome-minio-1                           Up (healthy)
interactome-postgres-1                        Up (healthy)
interactome-redis-1                           Up (healthy)
interactome-web-1                             Up (healthy)
interactome-worker_io-1                       Up
interactome-worker_extract_medgemma_27b-1     Up
interactome-worker_extract_phi4_14b-1         Up
interactome-worker_extract_qwen3_8b-1         Up
interactome-worker_extract_gemma3_12b-1       Up
interactome-worker_extract_deepseek_r1_32b-1  Up
interactome-worker_extract_devstral_24b-1     Up
interactome-worker_extract_llama3_1_8b-1      Up
```

- [ ] **Step 4: Verify migrations ran (including 0002 seed prompt)**

```bash
docker compose exec web python manage.py showmigrations extract
```

Expected:
```
extract
 [X] 0001_initial
 [X] 0002_seed_prompt
```

- [ ] **Step 5: Verify the active prompt is present**

```bash
docker compose exec web python manage.py shell -c \
  "from extract.models import PromptTemplate; print(PromptTemplate.objects.get(is_active=True).version)"
```

Expected:
```
1.0.0
```

- [ ] **Step 6: Verify each worker is consuming its queue**

```bash
docker compose logs worker_extract_qwen3_8b 2>&1 | grep -m 1 "Connected to redis"
```

Expected: a line of the form `... INFO/MainProcess] Connected to redis://redis:6379/0`. Repeat for any other workers you want to verify.

- [ ] **Step 7: Run the live smoke test**

Assumes Phase 1's `papers`/`corpus` migrations are present (the smoke test creates its own paper/section/chunk).

```bash
docker compose exec web pytest apps/extract/tests/test_smoke_all_models.py -m live -v -s
```

Expected (final assertion line):
```
... test_smoke_all_seven_models_produce_results PASSED

Per-model RawPPI counts:
  medgemma:27b: <N>
  phi4:14b: <N>
  qwen3:8b: <N>
  gemma3:12b: <N>
  deepseek-r1:32b: <N>
  devstral:24b: <N>
  llama3.1:8b: <N>
```

At least 5 of the 7 counts must be > 0.

- [ ] **Step 8: Verify Beat fires `enqueue_pending_chunks`**

Wait 5 minutes (or up to 10), then:

```bash
docker compose logs beat 2>&1 | grep "extract.enqueue_pending_chunks" | tail -3
```

Expected: at least one line of the form `Scheduler: Sending due task extract.enqueue_pending_chunks`.

- [ ] **Step 9: Bring the stack down**

```bash
docker compose down
```

(Volumes preserved.)

- [ ] **Step 10: Commit any fixes**

```bash
git status
# If any small fixes were needed during this verification:
git add <files>
git commit -m "fix: address issues found in Phase 2 stack verification"
```

---

## Task 20: Lint, type-check, full test suite

- [ ] **Step 1: Run ruff**

```bash
poetry run ruff check apps interactome
```

Expected: `All checks passed!`. If any issue: `poetry run ruff check --fix apps interactome && poetry run ruff format apps interactome`.

- [ ] **Step 2: Run mypy**

```bash
poetry run mypy apps interactome
```

Expected: `Success: no issues found in N source files`. If any new file fails: add types until clean. Never disable strict mode.

- [ ] **Step 3: Run the unit test suite**

```bash
poetry run pytest -v --tb=short -m 'not live'
```

Expected: every test from Phase 0, Phase 1, and Phase 2 passes. The `live` test is deselected.

- [ ] **Step 4: Push and verify GitHub Actions is green**

```bash
git push origin main
```

Wait ~5 minutes, then open the Actions tab. The latest workflow run must show all green checks.

- [ ] **Step 5: Tag the Phase 2 release**

```bash
git tag -a phase-2-complete -m "Phase 2 (Extraction pipeline) complete

Working extraction:
- 7 Ollama-model-bound Celery workers (concurrency=1 each)
- Schema-constrained JSON output via Ollama format=PPI_JSON_SCHEMA
- Logprob extraction on relation token (medgemma-validated approach)
- Versioned PromptTemplate (v1.0.0 seeded via data migration)
- Authelia session refresh on 401
- @with_heartbeat decorator wired into run_ppi (30s interval)
- Ollama RateLimitBucket (16 capacity, 8 refill/s)
- ExtractionRun added to janitor sweep list
- Beat-fired enqueue_pending_chunks (every 5 min)
- Live smoke test: ≥ 5 of 7 models produce ≥ 1 RawPPI on a real chunk

Next: Phase 3 (Graph integration) — Gilda grounding, Entity/Edge models,
Bayes belief scoring."
git push origin phase-2-complete
```

---

## Phase 2 Self-Review

**Spec coverage check** (against `docs/superpowers/specs/2026-05-19-disc-interactome-app-design.md`):

- Section 1 (high-level architecture) — extraction column wired: Redis broker → q.extract.<model> queues → 7 dedicated workers → Ollama gateway. Authelia session refresh covers the "Ollama gateway (7 models)" external service edge.
- Section 2 (Django apps) — new `extract` app created with `ExtractionRun`, `RawPPI`, `PromptTemplate` (exactly the three models listed for it in the spec table). `services.py` is the public API (`upsert_runs_for_chunk`, `build_prompt_text`, `active_prompt_version`). No reach into `extract.models` from outside.
- Section 3 (data model) — `ExtractionRun.status` is the full `{queued, running, done, failed}` FSM. `RawPPI` has the exact `evidence_span` + char offsets. Unique constraint on `(chunk, model_name, prompt_version)` per the spec's "one row per (chunk × model × prompt_version)" statement.
- Section 4 (per-paper pipeline) — `run_ppi` implements the spec's bullet list exactly: build prompt from PromptTemplate(active), POST /api/generate with format=PPI_SCHEMA + logprobs=true, parse to {subject, object, relation, evidence_span, cell_type, stimulus, confidence}, bulk INSERT RawPPI, status=done.
- Section 5 (master corpus) — not in scope; this phase consumes Phase 1's chunks only.
- Section 6 (Celery topology) — all of it implemented: 7 `worker_extract_<model>` services in compose (concurrency=1, queue=q.extract.<slug>), `OLLAMA_KEEP_ALIVE=2h` and `OLLAMA_MAX_LOADED_MODELS=2` env vars set, Ollama RateLimitBucket added, Beat schedule entry for `extract.enqueue_pending_chunks` every 5 min, Celery task_routes table for non-dynamic tasks.
- Section 7 (SBML + verify UI) — deferred to Phase 4 / Phase 5.
- Section 8 (resumability) — `@with_heartbeat(interval_sec=30)` per spec's "every 30 s" exactly. `ExtractionRun` added to `schedule.janitor`'s sweep list with 10-min stale threshold matching the spec's "running AND heartbeat < now() - 10min". Task body opens with `if status == 'done': return` for idempotency.
- Section 9 (deployment) — `docker-compose.yml` has the 7 new services using the same shared `interactome:dev` image; `.env.example` documents new env vars.
- Section 10 (roadmap) — Phase 2 row of the table is delivered: structured PPI prompt template, schema-constrained JSON output via Ollama format, 7 per-model Celery workers, rate-limit buckets, janitor.

**Placeholder scan:** No "TBD"/"TODO"/"implement later" strings. Every code block and every command is complete. Prompt body is literal text; JSON schema is generated from a concrete Pydantic model.

**Type consistency:**
- `OllamaClient`, `OllamaError`, `extract_relation_logprob`, `refresh_authelia_session` are referenced by the same names in tests, implementation, and the `extract.tasks._ollama_generate` indirection.
- `ExtractionRun`, `RawPPI`, `PromptTemplate` are imported the same way everywhere (`from extract.models import ...`).
- `PROMPT_V1_VERSION`, `PROMPT_V1_BODY`, `SUPPORTED_OLLAMA_MODELS`, `MODEL_TO_QUEUE`, `queue_for_model`, `PPI_JSON_SCHEMA`, `PPIExtractionResponse`, `PPITuple`, `AllowedRelation` — names used identically in tests, prompts.py / schemas.py / routing.py, and tasks.py.
- `run_ppi`, `enqueue_pending_chunks`, `smoke_all_models` — task names consistent across `tasks.py`, Beat schedule, task routes, and the live smoke test.
- The seven model slugs in `MODEL_TO_QUEUE` map 1:1 to the seven `worker_extract_<slug>` services in `docker-compose.yml`.

**Cross-phase dependency check:**
- **Requires Phase 0:** `core` app, `TimestampedModel`, `docker-compose.yml` shape, settings layout. ✓
- **Requires Phase 1:** `papers.models.Chunk`, `papers.models.Section`, `corpus.models.Paper`, `schedule.models.RateLimitBucket`, `schedule.janitor.SWEEP_MODELS` list, `schedule.tasks.janitor_reset_stale_running`. ✓ — every Phase-1 contract is consumed only via documented model imports and the janitor sweep registration; if Phase 1 ships a different field name (e.g. `Chunk.body` instead of `Chunk.text`) the test fixtures and `build_prompt_text` need a one-line adjustment.
- **Unblocks Phase 3 (graph):** `RawPPI` rows accumulate with valid offsets, `relation_logprob`, and `ungrounded=False` default — exactly what Phase 3's `normalize_and_integrate` needs to consume.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-19-phase-2-extraction.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — Dispatch a fresh subagent per task, review between tasks. Phase 2's tasks naturally divide along the unit-of-test boundaries (schema → prompt → models → client → heartbeat → routing → services → tasks → wiring), so per-task subagents stay small and reviewable. Recommended order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12 → 13 → 14 → 15 → 16 → 17 → 18 → 19 → 20.

**2. Inline Execution** — Run all 20 tasks in the current session with checkpoints after tasks 5 (OllamaClient), 10 (run_ppi), 14 (compose workers added), and 19 (stack verification).

**Pre-flight checklist before either option:**

- [ ] Phase 0 is tagged `phase-0-complete` and the stack came up green.
- [ ] Phase 1 is tagged `phase-1-complete`; the `papers.Chunk`, `corpus.Paper`, `schedule.RateLimitBucket`, and `schedule.tasks.janitor_reset_stale_running` exist in the codebase at the names this plan assumes.
- [ ] `.env` has been updated with `OLLAMA_SESSION_COOKIE` (or the `AUTHELIA_SVC_USER`/`AUTHELIA_SVC_PASSWORD` pair that lets the refresher mint one), or you have a way to run Task 19's live smoke test against the cluster.
- [ ] GPU box on the cluster is reachable via the Ollama gateway and has at least the seven models loaded (or willing to load on-demand).

**Which approach?**
