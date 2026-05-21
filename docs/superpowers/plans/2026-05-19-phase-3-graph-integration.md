# Phase 3: Graph Integration — Implementation Plan

> **⚠ CROSS-PLAN CONTRACT OVERRIDE:** Before implementing, read
> `2026-05-19-cross-plan-reconciliation.md`. It is authoritative where this
> plan's cross-phase references disagree. For this phase specifically: use
> `RawPPI.subject`/`object` (not `subject_text`/`object_text`),
> `RawPPI.evidence_offset_start/end`, `RawPPI.relation_logprob`, `RawPPI.run`,
> `ExtractionRun.model_name` (not `extractor_model`), and
> `Paper.publication_date` (not `pub_date`). `Network.root_entities` now exists
> (added by reconciliation §8). `Edge` now persists `n_supporting_papers` and
> `n_models_agreeing`; set them in `normalize_and_integrate`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the stream of `RawPPI` rows produced by Phase 2 into a normalized, deduplicated, belief-scored regulatory graph that biologists can browse network-by-network. End state: every grounded `RawPPI` becomes an `Edge` carrying provenance back to its source chunks; conflicts (intra-paper, inter-paper, inter-model) raise `Conflict` rows; affected networks demote from `verified` → `stale`; the NF-κB axis renders in a Cytoscape.js dev view at `/graph/dev/networks/<code>/`.

**Architecture:** Two cooperating apps. The `core` app gains the **ontology layer** (`OntologyEntity` + `Identifier`) — these are concept-level rows shared by every consumer of normalized entities. The new `graph` app owns the **graph layer** (`Entity`, `Edge`, `EdgeEvidence`, `Conflict`, `NetworkEdgeMembership`) and the `normalize_and_integrate` Celery task that batch-processes `RawPPI` rows through Gilda grounding, edge upsert, belief recomputation, conflict detection, and network membership reassignment. The Bayes belief function is a pure-Python helper in `graph/services.py` that callers can unit-test in isolation. A new `graph.integrate_pending` Beat task runs every 10 min to debounce integration (spec §4 — "Integration is debounced … batch size 10–50"). A minimal Django+Cytoscape.js dev UI gives reviewers something to look at before Phase 5's full verification stack ships.

**Tech Stack:** Python 3.12, Django 5.0, Celery 5.3, PostgreSQL 16, **Gilda 1.4+** (new dependency), pytest 8 + pytest-django 4.8, ruff 0.6, mypy 1.10, Cytoscape.js 3.30 served from CDN.

**Reference spec:** `docs/superpowers/specs/2026-05-19-disc-interactome-app-design.md` Sections 3 (graph layer), 4 (`normalize_and_integrate`), 6 (Beat schedule), 7 (network status state machine), 10 (Phase 3 deliverable).

**Cross-phase dependencies (must already be in place):**
- Phase 0: `core` app, `TimestampedModel`, settings, Celery wiring, Authelia middleware.
- Phase 1: `networks.Network` model with `root_entities` JSONB array and `pipeline_status` field; `corpus.Paper`; `papers.Section` and `papers.Chunk`.
- Phase 2: `extract.ExtractionRun`, `extract.RawPPI` (with `subject_text`, `object_text`, `relation`, `cell_type`, `stimulus`, `confidence`, `evidence_span_start`, `evidence_span_end`, `extractor_model`, FK to `Chunk` and `ExtractionRun`).

This plan does NOT modify those models. If a referenced field name in Phase 1/2 differs at execution time, adjust the references but keep the semantics.

---

## File Structure After Phase 3

```
/                                       (git repo root, unchanged outside the listed paths)
├── pyproject.toml                      ADD: gilda dependency
├── apps/
│   ├── core/
│   │   ├── models.py                   ADD: OntologyEntity, Identifier
│   │   ├── services.py                 ADD: grounding helpers, identifier upsert
│   │   ├── migrations/
│   │   │   └── 0002_ontology_entity_identifier.py   (auto-generated)
│   │   └── tests/
│   │       ├── test_ontology_models.py    NEW
│   │       └── test_grounding_service.py  NEW
│   └── graph/                           NEW APP
│       ├── __init__.py
│       ├── apps.py                      GraphConfig
│       ├── models.py                    Entity, Edge, EdgeEvidence, Conflict, NetworkEdgeMembership
│       ├── services.py                  bayes_belief, normalize_and_integrate core, conflict detection
│       ├── tasks.py                     Celery tasks
│       ├── urls.py                      /graph/dev/networks/<code>/ route
│       ├── views.py                     dev UI view + edge JSON endpoint
│       ├── admin.py                     Django admin registrations
│       ├── templates/
│       │   └── graph/
│       │       └── dev_network.html     Cytoscape.js page
│       ├── migrations/
│       │   ├── __init__.py
│       │   └── 0001_initial.py          (auto-generated)
│       └── tests/
│           ├── __init__.py
│           ├── conftest.py              fixtures (paper/chunk/raw_ppi factories)
│           ├── test_models.py           model constraints
│           ├── test_bayes_belief.py     pure function unit tests
│           ├── test_normalize_and_integrate.py   end-to-end integration flow
│           ├── test_conflict_detection.py        intra/inter-paper/inter-model
│           ├── test_network_membership.py        membership + stale demotion
│           ├── test_tasks.py            integrate_pending Beat task
│           └── test_views.py            dev UI renders, JSON endpoint shape
└── interactome/
    └── settings/
        └── base.py                      ADD: "graph" to INSTALLED_APPS, Beat schedule entry
```

**Why this layout:**
- Ontology rows live in `core` because they are concept-level and used by every downstream consumer (the spec's diagram in Section 3 places them above the graph layer). The `graph` app then composes them into `Entity` nodes.
- The Bayes belief function is a free function (`bayes_belief(...)`) in `graph/services.py`, not a method on `Edge`. Pure functions are easier to test and reason about; the model just stores the result.
- The dev UI lives under `/graph/dev/` and is excluded from any future biologist-facing routes — Phase 5 will own the real verification UI.

---

## Task 1: Add Gilda dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add `gilda` to `[tool.poetry.dependencies]`**

In the dependencies block, after the existing `requests = "^2.32"` line, insert:

```toml
gilda = "^1.4"
```

Gilda pulls in `pandas`, `scikit-learn`, and a few hundred MB of grounding resources at first use. Document the disk impact in `.env.example` as a comment if not already noted (no env var change needed; Gilda caches under `~/.data/gilda/`).

- [ ] **Step 2: Lock and install**

```bash
poetry lock --no-update
poetry install
```

Expected: `poetry.lock` updated; `Installing the current project: interactome (0.1.0)` at the tail.

- [ ] **Step 3: Smoke-test that Gilda imports and resolves a known symbol**

```bash
poetry run python -c "import gilda; r = gilda.ground('IL1B'); print(r[0].term.db, r[0].term.id, r[0].score)"
```

Expected: a line resembling `HGNC 5992 0.7777` (exact score may vary by Gilda version; the important part is that `db='HGNC'` and `id='5992'`).

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml poetry.lock
git commit -m "build: add gilda dependency for entity grounding"
```

---

## Task 2: `OntologyEntity` and `Identifier` models in `core` (TDD)

The spec (Section 3 — layer diagram and the "Tiered identifier strictness" decision) requires every promoted `Entity` to resolve to at least one ontology `Identifier`. These rows are conceptual and shared across the system, so they live in `core`, not `graph`.

**Files:**
- Create: `apps/core/tests/test_ontology_models.py`
- Modify: `apps/core/models.py`
- Generate: `apps/core/migrations/0002_ontology_entity_identifier.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for core.OntologyEntity and core.Identifier."""
from __future__ import annotations

import pytest
from django.db import IntegrityError

from core.models import Identifier, OntologyEntity


def test_ontology_entity_requires_preferred_label(db):
    with pytest.raises(IntegrityError):
        OntologyEntity.objects.create(entity_type="protein", preferred_label="")


def test_ontology_entity_records_type_and_label(db):
    e = OntologyEntity.objects.create(entity_type="protein", preferred_label="IL1B")
    assert e.entity_type == "protein"
    assert e.preferred_label == "IL1B"
    assert e.created_at is not None


def test_identifier_unique_per_scheme_and_value(db):
    e = OntologyEntity.objects.create(entity_type="protein", preferred_label="IL1B")
    Identifier.objects.create(entity=e, scheme="HGNC", value="5992")
    with pytest.raises(IntegrityError):
        Identifier.objects.create(entity=e, scheme="HGNC", value="5992")


def test_identifier_is_iri_for_known_schemes(db):
    e = OntologyEntity.objects.create(entity_type="protein", preferred_label="IL1B")
    i = Identifier.objects.create(entity=e, scheme="HGNC", value="5992")
    assert i.as_iri() == "https://identifiers.org/hgnc:5992"


def test_identifier_is_iri_for_uniprot(db):
    e = OntologyEntity.objects.create(entity_type="protein", preferred_label="IL1B")
    i = Identifier.objects.create(entity=e, scheme="UNIPROT", value="P01584")
    assert i.as_iri() == "https://identifiers.org/uniprot:P01584"


def test_identifier_is_iri_for_chebi(db):
    e = OntologyEntity.objects.create(entity_type="metabolite", preferred_label="NAD+")
    i = Identifier.objects.create(entity=e, scheme="CHEBI", value="13389")
    assert i.as_iri() == "https://identifiers.org/chebi:CHEBI:13389"


def test_identifier_is_iri_for_mirbase(db):
    e = OntologyEntity.objects.create(entity_type="mirna", preferred_label="miR-21")
    i = Identifier.objects.create(entity=e, scheme="MIRBASE", value="MIMAT0000076")
    assert i.as_iri() == "https://identifiers.org/mirbase:MIMAT0000076"


def test_ontology_entity_reverse_relation_named_identifiers(db):
    e = OntologyEntity.objects.create(entity_type="protein", preferred_label="IL1B")
    Identifier.objects.create(entity=e, scheme="HGNC", value="5992")
    Identifier.objects.create(entity=e, scheme="UNIPROT", value="P01584")
    assert e.identifiers.count() == 2
```

- [ ] **Step 2: Run to confirm failure**

```bash
poetry run pytest apps/core/tests/test_ontology_models.py -v
```

Expected: `ImportError: cannot import name 'OntologyEntity' from 'core.models'`.

- [ ] **Step 3: Implement the models**

Append to `apps/core/models.py`:

```python
from django.db.models import CheckConstraint, Q, UniqueConstraint


class OntologyEntity(TimestampedModel):
    """A canonical biological concept (gene, protein, miRNA, metabolite, complex).

    The graph layer's ``Entity`` rows point here; provenance and tools that
    care about the underlying ontology dereference via the ``identifiers``
    reverse relation.
    """

    ENTITY_TYPES = [
        ("gene", "Gene"),
        ("protein", "Protein"),
        ("mirna", "microRNA"),
        ("lncrna", "lncRNA"),
        ("metabolite", "Metabolite"),
        ("complex", "Complex"),
        ("cell_type", "Cell type"),
        ("phenotype", "Phenotype"),
        ("other", "Other"),
    ]

    entity_type = models.CharField(max_length=32, choices=ENTITY_TYPES, db_index=True)
    preferred_label = models.CharField(max_length=255, db_index=True)
    description = models.TextField(blank=True, default="")
    # Cellular compartment for SBML-qual compartment assignment (Phase 4).
    compartment = models.CharField(max_length=32, blank=True, default="cytoplasm")
    # Primary identifiers.org URI (derived from the preferred Identifier).
    # Consumed by Phase 4 SBML MIRIAM annotation. See reconciliation doc §5/§8.
    canonical_uri = models.URLField(blank=True, default="")

    class Meta:
        constraints = [
            CheckConstraint(
                check=~Q(preferred_label=""),
                name="ontologyentity_label_nonempty",
            ),
        ]
        indexes = [
            models.Index(fields=["entity_type", "preferred_label"]),
        ]

    def __str__(self) -> str:
        return f"{self.preferred_label} ({self.entity_type})"


class Identifier(TimestampedModel):
    """One external identifier for an ``OntologyEntity``.

    A single concept can have many identifiers (UNIPROT + HGNC + ENSEMBL +
    NCBI Gene + ...). The ``(scheme, value)`` pair is unique within an
    entity but may collide across entities (rare, but Gilda can sometimes
    propose the same UNIPROT ID for two related concepts; we keep them
    distinct rows for traceability).
    """

    SCHEMES = [
        ("HGNC", "HGNC"),
        ("UNIPROT", "UniProt"),
        ("ENSEMBL", "Ensembl"),
        ("NCBI_GENE", "NCBI Gene"),
        ("CHEBI", "ChEBI"),
        ("MIRBASE", "miRBase"),
        ("MESH", "MeSH"),
        ("GO", "Gene Ontology"),
        ("CL", "Cell Ontology"),
        ("DOID", "Disease Ontology"),
        ("REACTOME", "Reactome"),
        ("OTHER", "Other"),
    ]

    entity = models.ForeignKey(
        OntologyEntity,
        related_name="identifiers",
        on_delete=models.CASCADE,
    )
    scheme = models.CharField(max_length=32, choices=SCHEMES, db_index=True)
    value = models.CharField(max_length=128, db_index=True)
    is_primary = models.BooleanField(default=False)

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["entity", "scheme", "value"],
                name="identifier_unique_per_entity_scheme_value",
            ),
        ]
        indexes = [
            models.Index(fields=["scheme", "value"]),
        ]

    def as_iri(self) -> str:
        """Return the canonical identifiers.org IRI for this identifier."""
        prefix = self.scheme.lower()
        # ChEBI's identifiers.org pattern keeps the CHEBI: prefix in the value.
        if self.scheme == "CHEBI" and not self.value.upper().startswith("CHEBI:"):
            value = f"CHEBI:{self.value}"
        else:
            value = self.value
        return f"https://identifiers.org/{prefix}:{value}"

    def __str__(self) -> str:
        return f"{self.scheme}:{self.value}"
```

- [ ] **Step 4: Generate the migration**

```bash
poetry run python manage.py makemigrations core --name ontology_entity_identifier
```

Expected: `Migrations for 'core': 0002_ontology_entity_identifier.py` listing `OntologyEntity` and `Identifier`.

- [ ] **Step 5: Apply the migration**

```bash
poetry run python manage.py migrate core
```

- [ ] **Step 6: Run the tests; confirm green**

```bash
poetry run pytest apps/core/tests/test_ontology_models.py -v
```

Expected: `8 passed`.

- [ ] **Step 7: Commit**

```bash
git add apps/core/models.py apps/core/migrations/0002_*.py apps/core/tests/test_ontology_models.py
git commit -m "feat(core): add OntologyEntity and Identifier for tiered grounding"
```

---

## Task 3: Gilda-backed grounding service in `core` (TDD)

A single front door — `core.services.ground_mention(text, entity_type_hint=None)` — that calls Gilda, returns the best match above a configurable threshold, and upserts an `OntologyEntity` + `Identifier`. The function returns `None` when Gilda has no match above threshold; callers (specifically `graph.normalize_and_integrate`) interpret `None` as "flag the `RawPPI` as ungrounded".

**Files:**
- Create: `apps/core/services.py`
- Create: `apps/core/tests/test_grounding_service.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for core.services.ground_mention."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.models import Identifier, OntologyEntity
from core.services import GROUND_SCORE_THRESHOLD, ground_mention


@pytest.fixture
def fake_gilda_match():
    """Build a stand-in for a single gilda.grounder.ScoredMatch."""
    def _make(db: str, id_: str, name: str, score: float):
        m = MagicMock()
        m.term.db = db
        m.term.id = id_
        m.term.entry_name = name
        m.score = score
        return m
    return _make


@patch("core.services.gilda")
def test_ground_mention_returns_entity_on_high_score(mock_gilda, db, fake_gilda_match):
    mock_gilda.ground.return_value = [fake_gilda_match("HGNC", "5992", "IL1B", 0.95)]
    entity = ground_mention("IL-1β")
    assert entity is not None
    assert entity.preferred_label == "IL1B"
    assert entity.entity_type == "protein"
    assert entity.identifiers.filter(scheme="HGNC", value="5992").exists()


@patch("core.services.gilda")
def test_ground_mention_returns_none_below_threshold(mock_gilda, db, fake_gilda_match):
    mock_gilda.ground.return_value = [
        fake_gilda_match("HGNC", "5992", "IL1B", GROUND_SCORE_THRESHOLD - 0.01),
    ]
    assert ground_mention("ambiguous-thing") is None


@patch("core.services.gilda")
def test_ground_mention_returns_none_on_empty_match_list(mock_gilda, db):
    mock_gilda.ground.return_value = []
    assert ground_mention("unknownium") is None


@patch("core.services.gilda")
def test_ground_mention_is_idempotent(mock_gilda, db, fake_gilda_match):
    mock_gilda.ground.return_value = [fake_gilda_match("HGNC", "5992", "IL1B", 0.95)]
    e1 = ground_mention("IL1B")
    e2 = ground_mention("IL-1B")
    assert e1.pk == e2.pk
    assert OntologyEntity.objects.count() == 1
    assert Identifier.objects.filter(scheme="HGNC", value="5992").count() == 1


@patch("core.services.gilda")
def test_ground_mention_uses_entity_type_hint_when_provided(mock_gilda, db, fake_gilda_match):
    mock_gilda.ground.return_value = [fake_gilda_match("MIRBASE", "MIMAT0000076", "miR-21", 0.92)]
    entity = ground_mention("miR-21", entity_type_hint="mirna")
    assert entity.entity_type == "mirna"


@patch("core.services.gilda")
def test_ground_mention_blank_input_returns_none(mock_gilda, db):
    assert ground_mention("") is None
    assert ground_mention("   ") is None
    mock_gilda.ground.assert_not_called()


@patch("core.services.gilda")
def test_ground_mention_chooses_top_score(mock_gilda, db, fake_gilda_match):
    mock_gilda.ground.return_value = [
        fake_gilda_match("HGNC", "5992", "IL1B", 0.95),
        fake_gilda_match("HGNC", "5993", "IL1A", 0.85),
    ]
    entity = ground_mention("IL-1")
    assert entity.identifiers.filter(value="5992").exists()
    assert not entity.identifiers.filter(value="5993").exists()
```

- [ ] **Step 2: Run, confirm failure**

```bash
poetry run pytest apps/core/tests/test_grounding_service.py -v
```

Expected: `ImportError: cannot import name 'ground_mention' from 'core.services'`.

- [ ] **Step 3: Implement `core/services.py`**

```python
"""core.services — public API of the core app.

Today this is just the grounding helper. Other shared utilities (timezone
helpers, structured-log shims) live alongside as they accrete.
"""
from __future__ import annotations

import logging
from typing import Optional

import gilda
from django.db import transaction

from core.models import Identifier, OntologyEntity

logger = logging.getLogger(__name__)

# Gilda's score is roughly the dot-product of TF-IDF vectors. Empirically:
#   > 0.7  → high-confidence match
#   0.5-0.7 → ambiguous; could be wrong family member
#   < 0.5  → noise
# Spec §3 demands tiered strictness; we keep the bar high (0.70) to favour
# precision over recall — the ungrounded RawPPI is still archived, just
# never promoted to an Edge.
GROUND_SCORE_THRESHOLD: float = 0.70


# Gilda's db codes map onto our Identifier.SCHEMES. Anything not listed
# here falls through to OTHER.
_GILDA_DB_TO_SCHEME: dict[str, str] = {
    "HGNC": "HGNC",
    "UP": "UNIPROT",
    "UNIPROT": "UNIPROT",
    "ENSEMBL": "ENSEMBL",
    "EGID": "NCBI_GENE",
    "NCBIGENE": "NCBI_GENE",
    "CHEBI": "CHEBI",
    "MIRBASE": "MIRBASE",
    "MESH": "MESH",
    "GO": "GO",
    "CL": "CL",
    "DOID": "DOID",
    "REACTOME": "REACTOME",
}


# Heuristic mapping from a Gilda match's db code to our entity_type. The
# caller's ``entity_type_hint`` always wins.
_GILDA_DB_TO_ENTITY_TYPE: dict[str, str] = {
    "HGNC": "protein",
    "UP": "protein",
    "UNIPROT": "protein",
    "ENSEMBL": "gene",
    "EGID": "gene",
    "NCBIGENE": "gene",
    "CHEBI": "metabolite",
    "MIRBASE": "mirna",
    "GO": "phenotype",
    "CL": "cell_type",
    "DOID": "phenotype",
}


def ground_mention(
    text: str,
    *,
    entity_type_hint: Optional[str] = None,
) -> Optional[OntologyEntity]:
    """Ground a free-text mention to an OntologyEntity via Gilda.

    Returns the (created or pre-existing) OntologyEntity on success, or
    ``None`` if Gilda has no match above ``GROUND_SCORE_THRESHOLD``.
    Idempotent: re-grounding the same text never creates duplicates.

    Caller contract: ``ground_mention`` never raises for "no match"; the
    integration task interprets ``None`` as "leave the RawPPI ungrounded".
    """
    if not text or not text.strip():
        return None

    try:
        matches = gilda.ground(text.strip())
    except Exception as exc:  # gilda's resource load can fail on cold worker
        logger.warning("gilda.ground failed for %r: %s", text, exc)
        return None

    if not matches:
        return None

    top = matches[0]
    if top.score < GROUND_SCORE_THRESHOLD:
        return None

    scheme = _GILDA_DB_TO_SCHEME.get(top.term.db.upper(), "OTHER")
    entity_type = entity_type_hint or _GILDA_DB_TO_ENTITY_TYPE.get(
        top.term.db.upper(), "other"
    )

    with transaction.atomic():
        # Look up by the primary identifier we're about to create — that is
        # the unique handle, not preferred_label (which can collide across
        # gene/protein synonyms).
        ident = Identifier.objects.filter(
            scheme=scheme, value=top.term.id
        ).select_related("entity").first()
        if ident is not None:
            return ident.entity

        entity = OntologyEntity.objects.create(
            entity_type=entity_type,
            preferred_label=top.term.entry_name,
        )
        Identifier.objects.create(
            entity=entity,
            scheme=scheme,
            value=top.term.id,
            is_primary=True,
        )
        return entity
```

- [ ] **Step 4: Run; confirm green**

```bash
poetry run pytest apps/core/tests/test_grounding_service.py -v
```

Expected: `7 passed`.

- [ ] **Step 5: Commit**

```bash
git add apps/core/services.py apps/core/tests/test_grounding_service.py
git commit -m "feat(core): add Gilda-backed ground_mention service"
```

---

## Task 4: Scaffold the `graph` app

**Files:**
- Create: `apps/graph/__init__.py`
- Create: `apps/graph/apps.py`
- Create: `apps/graph/models.py` (placeholder)
- Create: `apps/graph/services.py` (placeholder)
- Create: `apps/graph/tasks.py` (placeholder)
- Create: `apps/graph/views.py` (placeholder)
- Create: `apps/graph/urls.py`
- Create: `apps/graph/admin.py`
- Create: `apps/graph/migrations/__init__.py`
- Create: `apps/graph/tests/__init__.py`
- Modify: `interactome/settings/base.py` (register the app)
- Modify: `interactome/urls.py` (include `graph.urls`)

- [ ] **Step 1: Create `apps/graph/__init__.py`**

```python
"""graph — normalized entity/edge graph and aggregation pipeline.

Depends on:
  - core (OntologyEntity, Identifier, ground_mention)
  - networks (Network, root_entities)
  - extract (RawPPI, ExtractionRun)
  - papers (Chunk, Section)
  - corpus (Paper)

Spec §3 (data model), §4 (normalize_and_integrate), §7 (network state machine).
"""
```

- [ ] **Step 2: Create `apps/graph/apps.py`**

```python
"""AppConfig for the graph app."""
from __future__ import annotations

from django.apps import AppConfig


class GraphConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "graph"
    verbose_name = "Graph (entities, edges, conflicts)"
```

- [ ] **Step 3: Create placeholder modules**

`apps/graph/models.py`:
```python
"""Graph models — Entity, Edge, EdgeEvidence, Conflict, NetworkEdgeMembership."""
```

`apps/graph/services.py`:
```python
"""graph.services — public API: bayes_belief, normalize_and_integrate, conflict detection."""
```

`apps/graph/tasks.py`:
```python
"""graph Celery tasks."""
```

`apps/graph/views.py`:
```python
"""graph dev UI views."""
```

`apps/graph/admin.py`:
```python
"""Django admin registrations for graph models."""
```

`apps/graph/urls.py`:
```python
"""graph URL routes."""
from __future__ import annotations

from django.urls import path

app_name = "graph"
urlpatterns: list = []
```

`apps/graph/migrations/__init__.py` (empty file).
`apps/graph/tests/__init__.py` (empty file).

- [ ] **Step 4: Register the app in `interactome/settings/base.py`**

Find `INSTALLED_APPS` and add `"graph"` after `"core"`:

```python
INSTALLED_APPS = [
    # ... existing Django + third-party apps ...
    "core",
    "networks",
    "corpus",
    "papers",
    "extract",
    "graph",
    "schedule",
]
```

(Match the exact ordering of apps already registered by earlier phases; the only change is that `"graph"` appears in the local-apps block.)

- [ ] **Step 5: Wire the URL conf in `interactome/urls.py`**

Add to the existing `urlpatterns` list (just before any trailing `]`):

```python
    path("graph/", include("graph.urls")),
```

- [ ] **Step 6: Verify Django boots**

```bash
poetry run python manage.py check
```

Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 7: Commit**

```bash
git add apps/graph/ interactome/settings/base.py interactome/urls.py
git commit -m "feat(graph): scaffold graph app"
```

---

## Task 5: `Entity` model (TDD)

Per spec §3: `Entity` is "a normalized node in the graph" with a FK to `OntologyEntity`. Cell-type and stimulus context can vary — keep them as optional discriminators so the same protein in NP vs AF cells is one `Entity` row (decision: do *not* split entities by cell-type, since SBML-qual species map 1:1 to ontology entities).

**Files:**
- Create: `apps/graph/tests/conftest.py`
- Create: `apps/graph/tests/test_models.py`
- Modify: `apps/graph/models.py`

- [ ] **Step 1: Create `apps/graph/tests/conftest.py`**

```python
"""Shared fixtures for graph tests.

Provides minimal stand-ins for Phase 1/2 models so the graph tests can
exercise normalize_and_integrate without depending on the full corpus
pipeline.
"""
from __future__ import annotations

from datetime import date

import pytest

from core.models import Identifier, OntologyEntity


@pytest.fixture
def il1b_ontology_entity(db):
    e = OntologyEntity.objects.create(entity_type="protein", preferred_label="IL1B")
    Identifier.objects.create(entity=e, scheme="HGNC", value="5992", is_primary=True)
    return e


@pytest.fixture
def nfkb1_ontology_entity(db):
    e = OntologyEntity.objects.create(entity_type="protein", preferred_label="NFKB1")
    Identifier.objects.create(entity=e, scheme="HGNC", value="7794", is_primary=True)
    return e


@pytest.fixture
def sirt1_ontology_entity(db):
    e = OntologyEntity.objects.create(entity_type="protein", preferred_label="SIRT1")
    Identifier.objects.create(entity=e, scheme="HGNC", value="14929", is_primary=True)
    return e


@pytest.fixture
def paper_factory(db):
    """Build minimal Paper rows. Phase 1 owns the real model — this just
    sidesteps the dependency for graph-only tests."""
    from corpus.models import Paper  # noqa: WPS433 -- intentional local import

    def _make(*, pmid: str, year: int = 2024, title: str = "Test paper"):
        return Paper.objects.create(
            pmid=pmid,
            doi=f"10.0/{pmid}",
            title=title,
            abstract="",
            pub_date=date(year, 1, 1),
            is_original=True,
        )
    return _make


@pytest.fixture
def chunk_factory(db, paper_factory):
    from papers.models import Chunk, Section

    def _make(*, paper=None, text: str = "IL1B activates NFKB1.", index: int = 0):
        paper = paper or paper_factory(pmid=f"pmid-{id(text)}")
        section, _ = Section.objects.get_or_create(
            paper=paper, doco_type="Results", order=0,
            defaults={"raw_xml": ""},
        )
        return Chunk.objects.create(
            section=section, text=text, char_start=0, char_end=len(text), index=index,
        )
    return _make


@pytest.fixture
def raw_ppi_factory(db, chunk_factory):
    from extract.models import ExtractionRun, RawPPI

    def _make(
        *,
        subject_text: str,
        object_text: str,
        relation: str = "activates",
        chunk=None,
        extractor_model: str = "qwen3_8b",
        confidence: float = 0.9,
    ):
        chunk = chunk or chunk_factory()
        run, _ = ExtractionRun.objects.get_or_create(
            chunk=chunk,
            extractor_model=extractor_model,
            prompt_version="v1",
            defaults={"status": "done"},
        )
        return RawPPI.objects.create(
            extraction_run=run,
            subject_text=subject_text,
            object_text=object_text,
            relation=relation,
            evidence_span_start=0,
            evidence_span_end=len(chunk.text),
            confidence=confidence,
            ungrounded=False,
        )
    return _make
```

(If a Phase 1/2 model has different fields, adjust the fixture accordingly — but keep the public signature stable so later tests don't break.)

- [ ] **Step 2: Write the failing test in `apps/graph/tests/test_models.py`**

```python
"""Tests for graph.models."""
from __future__ import annotations

import pytest
from django.db import IntegrityError

from graph.models import Entity


def test_entity_links_to_ontology_entity(db, il1b_ontology_entity):
    e = Entity.objects.create(ontology_entity=il1b_ontology_entity)
    assert e.ontology_entity == il1b_ontology_entity
    assert e.created_at is not None


def test_entity_unique_per_ontology_entity(db, il1b_ontology_entity):
    Entity.objects.create(ontology_entity=il1b_ontology_entity)
    with pytest.raises(IntegrityError):
        Entity.objects.create(ontology_entity=il1b_ontology_entity)


def test_entity_preferred_label_derives_from_ontology(db, il1b_ontology_entity):
    e = Entity.objects.create(ontology_entity=il1b_ontology_entity)
    assert e.preferred_label == "IL1B"


def test_entity_has_primary_identifier(db, il1b_ontology_entity):
    e = Entity.objects.create(ontology_entity=il1b_ontology_entity)
    assert e.primary_identifier.value == "5992"
    assert e.primary_identifier.scheme == "HGNC"
```

- [ ] **Step 3: Implement `Entity` in `apps/graph/models.py`**

```python
"""Graph models — Entity, Edge, EdgeEvidence, Conflict, NetworkEdgeMembership."""
from __future__ import annotations

from django.db import models

from core.models import Identifier, OntologyEntity, TimestampedModel


class Entity(TimestampedModel):
    """A normalized node in the graph.

    1:1 with OntologyEntity. The split exists so the graph app can hang
    graph-level metadata (cached aggregate degree, last_seen_at, etc.) on
    nodes without polluting the ontology layer.
    """

    ontology_entity = models.OneToOneField(
        OntologyEntity,
        on_delete=models.PROTECT,
        related_name="graph_entity",
    )

    class Meta:
        verbose_name_plural = "entities"

    @property
    def preferred_label(self) -> str:
        return self.ontology_entity.preferred_label

    @property
    def primary_identifier(self) -> Identifier:
        return self.ontology_entity.identifiers.filter(is_primary=True).first() \
            or self.ontology_entity.identifiers.first()

    # Proxy properties so Phase 4 (SBML emission) can read flat attributes off
    # an Entity without knowing the OntologyEntity split. See reconciliation
    # doc §5/§8.
    @property
    def symbol(self) -> str:
        return self.ontology_entity.preferred_label

    @property
    def compartment(self) -> str:
        return self.ontology_entity.compartment or "cytoplasm"

    @property
    def canonical_uri(self) -> str:
        return self.ontology_entity.canonical_uri

    @property
    def miriam_uris(self) -> list[str]:
        scheme_prefix = {
            "UNIPROT": "uniprot", "HGNC": "hgnc",
            "CHEBI": "chebi", "MIRBASE": "mirbase",
        }
        uris = []
        for ident in self.ontology_entity.identifiers.all():
            prefix = scheme_prefix.get(ident.scheme.upper())
            if prefix:
                uris.append(f"https://identifiers.org/{prefix}:{ident.value}")
        return uris

    def __str__(self) -> str:
        return self.preferred_label
```

- [ ] **Step 4: Generate the migration**

```bash
poetry run python manage.py makemigrations graph
```

Expected: `Migrations for 'graph': 0001_initial.py` listing `Entity`.

- [ ] **Step 5: Apply and run tests**

```bash
poetry run python manage.py migrate graph
poetry run pytest apps/graph/tests/test_models.py -v
```

Expected: `4 passed`.

- [ ] **Step 6: Commit**

```bash
git add apps/graph/models.py apps/graph/migrations/0001_initial.py apps/graph/tests/conftest.py apps/graph/tests/test_models.py
git commit -m "feat(graph): add Entity model"
```

---

## Task 6: `Edge`, `EdgeEvidence`, `Conflict` models (TDD)

Per spec §3, an `Edge` is unique on `(source, target, relation_type)`. `status` and `belief_score` are recomputed every time a new `EdgeEvidence` lands.

**Files:**
- Modify: `apps/graph/models.py`
- Modify: `apps/graph/tests/test_models.py`
- Migration: auto-generated `0002_edge_evidence_conflict.py`

- [ ] **Step 1: Append tests to `apps/graph/tests/test_models.py`**

```python
from graph.models import Conflict, Edge, EdgeEvidence


def test_edge_unique_on_source_target_relation(db, il1b_ontology_entity, nfkb1_ontology_entity):
    src = Entity.objects.create(ontology_entity=il1b_ontology_entity)
    tgt = Entity.objects.create(ontology_entity=nfkb1_ontology_entity)
    Edge.objects.create(source=src, target=tgt, relation="activates")
    with pytest.raises(IntegrityError):
        Edge.objects.create(source=src, target=tgt, relation="activates")


def test_edge_allows_same_pair_with_different_relation(db, il1b_ontology_entity, nfkb1_ontology_entity):
    src = Entity.objects.create(ontology_entity=il1b_ontology_entity)
    tgt = Entity.objects.create(ontology_entity=nfkb1_ontology_entity)
    Edge.objects.create(source=src, target=tgt, relation="activates")
    Edge.objects.create(source=src, target=tgt, relation="binds")  # OK


def test_edge_defaults_to_candidate_status(db, il1b_ontology_entity, nfkb1_ontology_entity):
    src = Entity.objects.create(ontology_entity=il1b_ontology_entity)
    tgt = Entity.objects.create(ontology_entity=nfkb1_ontology_entity)
    e = Edge.objects.create(source=src, target=tgt, relation="activates")
    assert e.status == "candidate"
    assert e.belief_score == 0.0


def test_edge_evidence_links_edge_to_raw_ppi(db, raw_ppi_factory, il1b_ontology_entity, nfkb1_ontology_entity):
    src = Entity.objects.create(ontology_entity=il1b_ontology_entity)
    tgt = Entity.objects.create(ontology_entity=nfkb1_ontology_entity)
    e = Edge.objects.create(source=src, target=tgt, relation="activates")
    raw = raw_ppi_factory(subject_text="IL1B", object_text="NFKB1")
    ev = EdgeEvidence.objects.create(edge=e, raw_ppi=raw)
    assert ev.edge == e and ev.raw_ppi == raw


def test_edge_evidence_unique_per_edge_raw_ppi(db, raw_ppi_factory, il1b_ontology_entity, nfkb1_ontology_entity):
    src = Entity.objects.create(ontology_entity=il1b_ontology_entity)
    tgt = Entity.objects.create(ontology_entity=nfkb1_ontology_entity)
    e = Edge.objects.create(source=src, target=tgt, relation="activates")
    raw = raw_ppi_factory(subject_text="IL1B", object_text="NFKB1")
    EdgeEvidence.objects.create(edge=e, raw_ppi=raw)
    with pytest.raises(IntegrityError):
        EdgeEvidence.objects.create(edge=e, raw_ppi=raw)


def test_conflict_records_two_edges_and_status(db, il1b_ontology_entity, nfkb1_ontology_entity):
    src = Entity.objects.create(ontology_entity=il1b_ontology_entity)
    tgt = Entity.objects.create(ontology_entity=nfkb1_ontology_entity)
    e1 = Edge.objects.create(source=src, target=tgt, relation="activates")
    e2 = Edge.objects.create(source=src, target=tgt, relation="inhibits")
    c = Conflict.objects.create(
        edge_a=e1, edge_b=e2, conflict_type="inter_model",
        resolution_status="open",
    )
    assert c.resolution_status == "open"
    assert c.conflict_type == "inter_model"


def test_conflict_unique_per_edge_pair(db, il1b_ontology_entity, nfkb1_ontology_entity):
    src = Entity.objects.create(ontology_entity=il1b_ontology_entity)
    tgt = Entity.objects.create(ontology_entity=nfkb1_ontology_entity)
    e1 = Edge.objects.create(source=src, target=tgt, relation="activates")
    e2 = Edge.objects.create(source=src, target=tgt, relation="inhibits")
    Conflict.objects.create(edge_a=e1, edge_b=e2, conflict_type="inter_model", resolution_status="open")
    with pytest.raises(IntegrityError):
        Conflict.objects.create(edge_a=e1, edge_b=e2, conflict_type="inter_model", resolution_status="open")
```

- [ ] **Step 2: Implement the models**

Append to `apps/graph/models.py`:

```python
class Edge(TimestampedModel):
    """A normalized relationship between two entities.

    Unique on (source, target, relation). belief_score and status are
    derived state — recomputed by graph.services.recompute_edge_belief
    every time new evidence lands. Direct DB writes to those columns
    should only happen via that helper.
    """

    RELATIONS = [
        ("activates", "activates"),
        ("inhibits", "inhibits"),
        ("binds", "binds"),
        ("phosphorylates", "phosphorylates"),
        ("dephosphorylates", "dephosphorylates"),
        ("ubiquitinates", "ubiquitinates"),
        ("deubiquitinates", "deubiquitinates"),
        ("methylates", "methylates"),
        ("acetylates", "acetylates"),
        ("deacetylates", "deacetylates"),
        ("transcribes", "transcribes"),
        ("represses", "represses"),
        ("cleaves", "cleaves"),
        ("regulates", "regulates"),
    ]

    STATUSES = [
        ("candidate", "candidate"),
        ("accepted", "accepted"),
        ("conflicted", "conflicted"),
        ("rejected", "rejected"),
    ]

    source = models.ForeignKey(
        Entity, related_name="outgoing_edges", on_delete=models.PROTECT,
    )
    target = models.ForeignKey(
        Entity, related_name="incoming_edges", on_delete=models.PROTECT,
    )
    relation = models.CharField(max_length=32, choices=RELATIONS, db_index=True)
    belief_score = models.FloatField(default=0.0, db_index=True)
    # Denormalized counters set by normalize_and_integrate alongside
    # belief_score (the counts are already computed there as args to
    # bayes_belief). Consumed by Phase 4 (SBML annotations + edges.csv) and
    # Phase 5 (verification UI). See cross-plan reconciliation doc §4/§8.
    n_supporting_papers = models.PositiveIntegerField(default=0)
    n_models_agreeing = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=16, choices=STATUSES, default="candidate", db_index=True,
    )

    raw_ppis = models.ManyToManyField(
        "extract.RawPPI",
        through="graph.EdgeEvidence",
        related_name="edges",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source", "target", "relation"],
                name="edge_unique_source_target_relation",
            ),
        ]
        indexes = [
            models.Index(fields=["source", "target"]),
            models.Index(fields=["status", "belief_score"]),
        ]

    def __str__(self) -> str:
        return f"{self.source} -{self.relation}-> {self.target}"


class EdgeEvidence(TimestampedModel):
    """One RawPPI supporting one Edge. Many-to-many through table.

    Never deleted, even when a RawPPI is superseded — the audit trail
    is load-bearing for the verification UI's provenance tree (spec §3
    "Provenance is a graph, not a string").
    """

    edge = models.ForeignKey(Edge, on_delete=models.CASCADE, related_name="evidence")
    raw_ppi = models.ForeignKey(
        "extract.RawPPI", on_delete=models.PROTECT, related_name="edge_evidence",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["edge", "raw_ppi"],
                name="edgeevidence_unique_edge_raw_ppi",
            ),
        ]


class Conflict(TimestampedModel):
    """A pair of edges that disagree (typically opposite relation).

    Three conflict_types per spec §4:
      * intra_paper — two extractions on the same chunk, opposite signs
      * inter_paper — same edge pair, different papers, opposite signs
      * inter_model — consensus across the 7 models is below majority
    """

    CONFLICT_TYPES = [
        ("intra_paper", "intra-paper"),
        ("inter_paper", "inter-paper"),
        ("inter_model", "inter-model"),
    ]

    RESOLUTION_STATUSES = [
        ("open", "open"),
        ("auto_resolved", "auto-resolved"),
        ("curator_resolved", "curator-resolved"),
        ("ignored", "ignored"),
    ]

    edge_a = models.ForeignKey(
        Edge, on_delete=models.CASCADE, related_name="conflicts_as_a",
    )
    edge_b = models.ForeignKey(
        Edge, on_delete=models.CASCADE, related_name="conflicts_as_b",
    )
    conflict_type = models.CharField(
        max_length=16, choices=CONFLICT_TYPES, db_index=True,
    )
    resolution_status = models.CharField(
        max_length=24, choices=RESOLUTION_STATUSES, default="open", db_index=True,
    )
    reasoning = models.TextField(blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["edge_a", "edge_b", "conflict_type"],
                name="conflict_unique_pair_type",
            ),
        ]
```

- [ ] **Step 3: Generate the migration**

```bash
poetry run python manage.py makemigrations graph --name edge_evidence_conflict
```

Expected: `Migrations for 'graph': 0002_edge_evidence_conflict.py`.

- [ ] **Step 4: Apply and run tests**

```bash
poetry run python manage.py migrate graph
poetry run pytest apps/graph/tests/test_models.py -v
```

Expected: previous tests still green + 7 new tests pass (`11 passed`).

- [ ] **Step 5: Commit**

```bash
git add apps/graph/models.py apps/graph/migrations/0002_*.py apps/graph/tests/test_models.py
git commit -m "feat(graph): add Edge, EdgeEvidence, Conflict models"
```

---

## Task 7: `NetworkEdgeMembership` model (TDD)

Per spec §3 "Edges are shared, networks slice them": one edge belongs to many networks via `NetworkEdgeMembership`, with a per-network `relevance` score (so we can rank edges within a network later).

**Files:**
- Modify: `apps/graph/models.py`
- Create: `apps/graph/tests/test_network_membership.py`
- Migration: auto-generated `0003_network_edge_membership.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for graph.NetworkEdgeMembership."""
from __future__ import annotations

import pytest
from django.db import IntegrityError

from graph.models import Edge, Entity, NetworkEdgeMembership


@pytest.fixture
def nfkb_network(db, nfkb1_ontology_entity):
    from networks.models import Network
    return Network.objects.create(
        code="nfkb_axis",
        title="NF-κB axis",
        category="I",
        root_entities=[{"scheme": "HGNC", "value": "7794"}],  # NFKB1
        pipeline_status="idle",
    )


def test_membership_links_edge_to_network(
    db, il1b_ontology_entity, nfkb1_ontology_entity, nfkb_network,
):
    src = Entity.objects.create(ontology_entity=il1b_ontology_entity)
    tgt = Entity.objects.create(ontology_entity=nfkb1_ontology_entity)
    e = Edge.objects.create(source=src, target=tgt, relation="activates")
    m = NetworkEdgeMembership.objects.create(network=nfkb_network, edge=e, relevance=1.0)
    assert m.network == nfkb_network
    assert m.edge == e
    assert m.relevance == 1.0


def test_membership_unique_per_network_edge(
    db, il1b_ontology_entity, nfkb1_ontology_entity, nfkb_network,
):
    src = Entity.objects.create(ontology_entity=il1b_ontology_entity)
    tgt = Entity.objects.create(ontology_entity=nfkb1_ontology_entity)
    e = Edge.objects.create(source=src, target=tgt, relation="activates")
    NetworkEdgeMembership.objects.create(network=nfkb_network, edge=e, relevance=1.0)
    with pytest.raises(IntegrityError):
        NetworkEdgeMembership.objects.create(network=nfkb_network, edge=e, relevance=0.5)
```

- [ ] **Step 2: Implement the model**

Append to `apps/graph/models.py`:

```python
class NetworkEdgeMembership(TimestampedModel):
    """An edge's membership in a network slice.

    The same Edge can appear in many networks — e.g. an IL1B→NFKB1 edge
    is relevant to NF-κB axis, to inflammatory networks, and to ECM
    catabolism networks. Each membership row carries a per-network
    relevance score (1.0 if either endpoint matches the network's
    root_entities directly, falling off for second-degree links).
    """

    network = models.ForeignKey(
        "networks.Network", on_delete=models.CASCADE, related_name="edge_memberships",
    )
    edge = models.ForeignKey(
        Edge, on_delete=models.CASCADE, related_name="network_memberships",
    )
    relevance = models.FloatField(default=1.0, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["network", "edge"],
                name="networkedgemembership_unique_network_edge",
            ),
        ]
        indexes = [
            models.Index(fields=["network", "relevance"]),
        ]

    def __str__(self) -> str:
        return f"{self.network.code} ⊇ {self.edge}"
```

- [ ] **Step 3: Generate and apply the migration**

```bash
poetry run python manage.py makemigrations graph --name network_edge_membership
poetry run python manage.py migrate graph
```

- [ ] **Step 4: Run tests; confirm green**

```bash
poetry run pytest apps/graph/tests/test_network_membership.py -v
```

Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add apps/graph/models.py apps/graph/migrations/0003_*.py apps/graph/tests/test_network_membership.py
git commit -m "feat(graph): add NetworkEdgeMembership for per-network edge slicing"
```

---

## Task 8: Bayes belief function (TDD)

Per spec §4: "Recompute Edge.belief_score (Bayes update over models + papers)". This is the load-bearing scoring function. We model belief as a posterior probability that the edge is real, given (a) the prior, (b) each piece of evidence treated as an independent Bernoulli trial with likelihood-ratio bumped by recency.

**Files:**
- Modify: `apps/graph/services.py`
- Create: `apps/graph/tests/test_bayes_belief.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for graph.services.bayes_belief.

The Bayes belief function turns three count-style inputs into a posterior
probability in (0, 1):
  * n_supporting_papers — distinct PMIDs that support this edge
  * n_models_agreeing   — distinct extractor models that found this edge
  * mean_recency        — exp-decayed weight over evidence ages (1.0 = today,
                          0.5 ≈ 5 years old, ~0.0 ≈ 20+ years old)
"""
from __future__ import annotations

import math

import pytest

from graph.services import (
    BAYES_PRIOR,
    BELIEF_THRESHOLD_ACCEPTED,
    BELIEF_THRESHOLD_REJECTED,
    bayes_belief,
)


def test_belief_with_no_evidence_equals_prior():
    score = bayes_belief(n_supporting_papers=0, n_models_agreeing=0, mean_recency=1.0)
    assert score == pytest.approx(BAYES_PRIOR, abs=1e-9)


def test_belief_strictly_in_open_unit_interval():
    score = bayes_belief(n_supporting_papers=5, n_models_agreeing=7, mean_recency=1.0)
    assert 0.0 < score < 1.0


def test_belief_monotonic_in_supporting_papers():
    s1 = bayes_belief(n_supporting_papers=1, n_models_agreeing=3, mean_recency=1.0)
    s5 = bayes_belief(n_supporting_papers=5, n_models_agreeing=3, mean_recency=1.0)
    assert s5 > s1


def test_belief_monotonic_in_models_agreeing():
    s1 = bayes_belief(n_supporting_papers=3, n_models_agreeing=1, mean_recency=1.0)
    s7 = bayes_belief(n_supporting_papers=3, n_models_agreeing=7, mean_recency=1.0)
    assert s7 > s1


def test_belief_monotonic_in_recency():
    s_old = bayes_belief(n_supporting_papers=3, n_models_agreeing=3, mean_recency=0.1)
    s_new = bayes_belief(n_supporting_papers=3, n_models_agreeing=3, mean_recency=1.0)
    assert s_new > s_old


def test_belief_saturates_near_one_with_many_supporters():
    score = bayes_belief(n_supporting_papers=50, n_models_agreeing=7, mean_recency=1.0)
    assert score > 0.99
    assert score < 1.0  # never exactly 1.0


def test_belief_handles_zero_recency_gracefully():
    score = bayes_belief(n_supporting_papers=3, n_models_agreeing=3, mean_recency=0.0)
    assert 0.0 < score <= BAYES_PRIOR + 0.01  # no boost when evidence is "infinitely old"


def test_thresholds_are_well_defined():
    assert 0.0 < BELIEF_THRESHOLD_REJECTED < BAYES_PRIOR < BELIEF_THRESHOLD_ACCEPTED < 1.0


def test_belief_with_one_paper_seven_models_recent_exceeds_accepted_threshold():
    """The "consensus" case — 7 models agree on a single recent paper."""
    score = bayes_belief(n_supporting_papers=1, n_models_agreeing=7, mean_recency=1.0)
    assert score >= BELIEF_THRESHOLD_ACCEPTED


def test_belief_with_one_paper_one_model_stays_candidate():
    score = bayes_belief(n_supporting_papers=1, n_models_agreeing=1, mean_recency=1.0)
    assert BELIEF_THRESHOLD_REJECTED < score < BELIEF_THRESHOLD_ACCEPTED


def test_belief_rejects_negative_counts():
    with pytest.raises(ValueError):
        bayes_belief(n_supporting_papers=-1, n_models_agreeing=1, mean_recency=1.0)
    with pytest.raises(ValueError):
        bayes_belief(n_supporting_papers=1, n_models_agreeing=-1, mean_recency=1.0)


def test_belief_clamps_recency_to_unit_interval():
    s = bayes_belief(n_supporting_papers=3, n_models_agreeing=3, mean_recency=1.5)
    s_clamped = bayes_belief(n_supporting_papers=3, n_models_agreeing=3, mean_recency=1.0)
    assert s == pytest.approx(s_clamped)
```

- [ ] **Step 2: Run; confirm failure**

```bash
poetry run pytest apps/graph/tests/test_bayes_belief.py -v
```

Expected: `ImportError: cannot import name 'bayes_belief' from 'graph.services'`.

- [ ] **Step 3: Implement `bayes_belief` in `apps/graph/services.py`**

Replace the placeholder with:

```python
"""graph.services — public API of the graph app.

Three responsibilities:

  1. bayes_belief()              — pure posterior-probability function
  2. normalize_and_integrate()   — RawPPI -> Edge integration
  3. conflict detection helpers  — intra/inter-paper, inter-model

Section anchors refer to docs/superpowers/specs/2026-05-19-disc-interactome-app-design.md.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, Optional, Sequence

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


# --- Bayes scoring constants -------------------------------------------------
#
# Prior probability that any plausibly-extracted (and grounded) edge is real,
# before we look at how many models/papers support it. 0.3 reflects the
# empirical observation from PPI literature that ~30% of single-extraction
# claims survive curator review.
BAYES_PRIOR: float = 0.30

# Likelihood ratios for one piece of evidence. Tuned so that:
#   - 1 paper × 1 model:  ~prior (candidate territory)
#   - 1 paper × 7 models: ≥ accepted threshold
#   - 3+ papers × 3+ models: well above accepted threshold
LR_PER_PAPER: float = 2.3   # one additional supporting paper
LR_PER_MODEL: float = 1.6   # one additional agreeing extractor model

# Promotion thresholds for Edge.status. Below REJECTED: status='rejected'.
# Between REJECTED and ACCEPTED: status='candidate'. Above ACCEPTED:
# status='accepted' (still subject to conflict downgrade — see
# graph.services.recompute_edge_status).
BELIEF_THRESHOLD_REJECTED: float = 0.10
BELIEF_THRESHOLD_ACCEPTED: float = 0.80

# How fast evidence age decays the per-paper likelihood ratio. Half-life is
# ~5 years: a 5-year-old paper still contributes ~50% of the boost a fresh
# paper would. Used by callers when computing mean_recency.
RECENCY_HALFLIFE_DAYS: float = 365.25 * 5


def bayes_belief(
    *,
    n_supporting_papers: int,
    n_models_agreeing: int,
    mean_recency: float,
) -> float:
    """Compute the posterior probability that an Edge is real.

    Args:
        n_supporting_papers: distinct PMIDs supporting the edge.
        n_models_agreeing:   distinct extractor models that found it.
        mean_recency:        mean recency weight of supporting evidence,
                             in [0, 1]. 1.0 = today; 0.5 ≈ 5 years old.
                             Values outside [0, 1] are clamped.

    Returns:
        Posterior probability strictly inside (0, 1). Never exactly 0 or 1
        (so logs stay finite and Bayes updates remain numerically stable).
    """
    if n_supporting_papers < 0 or n_models_agreeing < 0:
        raise ValueError("counts must be non-negative")

    recency = max(0.0, min(1.0, mean_recency))

    # Log-odds form: starts at prior, accumulates log-LR per evidence unit.
    log_odds = math.log(BAYES_PRIOR / (1.0 - BAYES_PRIOR))
    log_odds += n_supporting_papers * math.log(LR_PER_PAPER) * recency
    log_odds += n_models_agreeing * math.log(LR_PER_MODEL)

    posterior = 1.0 / (1.0 + math.exp(-log_odds))

    # Numerical guard — clip into open unit interval.
    return min(0.999_999, max(0.000_001, posterior))


def recency_weight_for_date(pub_date: date, today: Optional[date] = None) -> float:
    """Map a paper's publication date to a weight in (0, 1].

    Exponential decay with the half-life set above.
    """
    today = today or timezone.now().date()
    age_days = max(0, (today - pub_date).days)
    return float(math.exp(-math.log(2.0) * age_days / RECENCY_HALFLIFE_DAYS))


def mean_recency_for_dates(dates: Sequence[date]) -> float:
    """Arithmetic mean of the per-date recency weights. Empty -> 1.0."""
    if not dates:
        return 1.0
    today = timezone.now().date()
    return sum(recency_weight_for_date(d, today) for d in dates) / len(dates)
```

- [ ] **Step 4: Run tests; confirm green**

```bash
poetry run pytest apps/graph/tests/test_bayes_belief.py -v
```

Expected: `12 passed`. If `test_belief_with_one_paper_seven_models_recent_exceeds_accepted_threshold` fails, the `LR_PER_MODEL` constant needs a small bump — adjust until that test passes without breaking the other monotonicity tests.

- [ ] **Step 5: Commit**

```bash
git add apps/graph/services.py apps/graph/tests/test_bayes_belief.py
git commit -m "feat(graph): add Bayes belief function with recency decay"
```

---

## Task 9: Edge belief/status recomputation (TDD)

A small helper, `recompute_edge_belief(edge)`, that gathers the inputs to `bayes_belief` directly from the database and persists the result. This is what `normalize_and_integrate` calls every time it touches an `Edge`.

**Files:**
- Modify: `apps/graph/services.py`
- Modify: `apps/graph/tests/test_normalize_and_integrate.py` (create skeleton)

- [ ] **Step 1: Write the failing tests in `apps/graph/tests/test_normalize_and_integrate.py`**

```python
"""Tests for graph.services edge-belief recomputation and integration."""
from __future__ import annotations

import pytest

from graph.models import Edge, EdgeEvidence, Entity
from graph.services import (
    BAYES_PRIOR,
    BELIEF_THRESHOLD_ACCEPTED,
    recompute_edge_belief,
)


def test_recompute_belief_with_zero_evidence_equals_prior(
    db, il1b_ontology_entity, nfkb1_ontology_entity,
):
    src = Entity.objects.create(ontology_entity=il1b_ontology_entity)
    tgt = Entity.objects.create(ontology_entity=nfkb1_ontology_entity)
    e = Edge.objects.create(source=src, target=tgt, relation="activates")
    recompute_edge_belief(e)
    e.refresh_from_db()
    assert e.belief_score == pytest.approx(BAYES_PRIOR, abs=1e-3)


def test_recompute_belief_promotes_to_accepted_with_strong_evidence(
    db, il1b_ontology_entity, nfkb1_ontology_entity, paper_factory, chunk_factory, raw_ppi_factory,
):
    src = Entity.objects.create(ontology_entity=il1b_ontology_entity)
    tgt = Entity.objects.create(ontology_entity=nfkb1_ontology_entity)
    edge = Edge.objects.create(source=src, target=tgt, relation="activates")

    # 7 models all agree on a single recent paper
    paper = paper_factory(pmid="11111111", year=2025)
    chunk = chunk_factory(paper=paper, text="IL1B activates NFKB1.")
    for model in [
        "qwen3_8b", "phi4_14b", "gemma3_12b", "deepseek_r1_32b",
        "devstral_24b", "llama3_1_8b", "medgemma_27b",
    ]:
        raw = raw_ppi_factory(
            subject_text="IL1B", object_text="NFKB1", relation="activates",
            chunk=chunk, extractor_model=model,
        )
        EdgeEvidence.objects.create(edge=edge, raw_ppi=raw)

    recompute_edge_belief(edge)
    edge.refresh_from_db()
    assert edge.belief_score >= BELIEF_THRESHOLD_ACCEPTED
    assert edge.status == "accepted"


def test_recompute_belief_keeps_candidate_with_weak_evidence(
    db, il1b_ontology_entity, nfkb1_ontology_entity, paper_factory, chunk_factory, raw_ppi_factory,
):
    src = Entity.objects.create(ontology_entity=il1b_ontology_entity)
    tgt = Entity.objects.create(ontology_entity=nfkb1_ontology_entity)
    edge = Edge.objects.create(source=src, target=tgt, relation="activates")

    paper = paper_factory(pmid="22222222", year=2025)
    chunk = chunk_factory(paper=paper)
    raw = raw_ppi_factory(
        subject_text="IL1B", object_text="NFKB1", relation="activates",
        chunk=chunk, extractor_model="qwen3_8b",
    )
    EdgeEvidence.objects.create(edge=edge, raw_ppi=raw)

    recompute_edge_belief(edge)
    edge.refresh_from_db()
    assert edge.status == "candidate"


def test_recompute_belief_counts_distinct_papers_only(
    db, il1b_ontology_entity, nfkb1_ontology_entity, paper_factory, chunk_factory, raw_ppi_factory,
):
    """Two RawPPIs from the same paper but different chunks should count as 1 paper."""
    src = Entity.objects.create(ontology_entity=il1b_ontology_entity)
    tgt = Entity.objects.create(ontology_entity=nfkb1_ontology_entity)
    edge = Edge.objects.create(source=src, target=tgt, relation="activates")

    paper = paper_factory(pmid="33333333", year=2025)
    chunk_a = chunk_factory(paper=paper, text="IL1B activates NFKB1.", index=0)
    chunk_b = chunk_factory(paper=paper, text="IL1B activates NFKB1 again.", index=1)
    for chunk in (chunk_a, chunk_b):
        raw = raw_ppi_factory(
            subject_text="IL1B", object_text="NFKB1", relation="activates",
            chunk=chunk, extractor_model="qwen3_8b",
        )
        EdgeEvidence.objects.create(edge=edge, raw_ppi=raw)

    recompute_edge_belief(edge)
    # Score should be the same as 1-paper-1-model
    edge.refresh_from_db()
    assert edge.status == "candidate"  # still under threshold
```

- [ ] **Step 2: Run; confirm failure (ImportError)**

```bash
poetry run pytest apps/graph/tests/test_normalize_and_integrate.py -v
```

Expected: `ImportError: cannot import name 'recompute_edge_belief'`.

- [ ] **Step 3: Implement `recompute_edge_belief` in `apps/graph/services.py`**

Append:

```python
def recompute_edge_belief(edge) -> None:
    """Re-derive ``belief_score`` and ``status`` from ``edge.evidence``.

    Counts each distinct supporting PMID once and each distinct extractor
    model once. Recency is the mean recency weight of distinct papers.
    Status transitions:

       belief < BELIEF_THRESHOLD_REJECTED → rejected
       belief > BELIEF_THRESHOLD_ACCEPTED → accepted
       otherwise                          → candidate

    A separate helper (``demote_conflicted_edges``) downgrades accepted →
    conflicted when a Conflict row references the edge; this function
    never sets ``conflicted`` on its own.
    """
    # Pull supporting RawPPI rows with their paper.pub_date and extractor.
    evidence_rows = list(
        edge.evidence.select_related(
            "raw_ppi", "raw_ppi__extraction_run", "raw_ppi__extraction_run__chunk__section__paper",
        )
    )

    pmid_to_pubdate: dict[str, date] = {}
    models: set[str] = set()
    for ev in evidence_rows:
        paper = ev.raw_ppi.extraction_run.chunk.section.paper
        pmid_to_pubdate[paper.pmid] = paper.pub_date
        models.add(ev.raw_ppi.extraction_run.extractor_model)

    n_papers = len(pmid_to_pubdate)
    n_models = len(models)
    recency = mean_recency_for_dates(list(pmid_to_pubdate.values())) if n_papers else 1.0

    belief = bayes_belief(
        n_supporting_papers=n_papers,
        n_models_agreeing=n_models,
        mean_recency=recency,
    )

    # Don't overwrite 'conflicted' here — that's controlled by the
    # conflict resolver. But anything else can transition.
    if edge.status != "conflicted":
        if belief >= BELIEF_THRESHOLD_ACCEPTED:
            new_status = "accepted"
        elif belief < BELIEF_THRESHOLD_REJECTED:
            new_status = "rejected"
        else:
            new_status = "candidate"
    else:
        new_status = edge.status

    Edge_ = type(edge)
    Edge_.objects.filter(pk=edge.pk).update(belief_score=belief, status=new_status)
```

- [ ] **Step 4: Run; confirm green**

```bash
poetry run pytest apps/graph/tests/test_normalize_and_integrate.py -v
```

Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add apps/graph/services.py apps/graph/tests/test_normalize_and_integrate.py
git commit -m "feat(graph): add recompute_edge_belief with status transitions"
```

---

## Task 10: `normalize_and_integrate` — core integration loop (TDD)

The big one. Per spec §4 the integration step does six things:

1. Gilda-ground each subject/object string → `OntologyEntity` (or fail)
2. If both grounded: upsert `Entity` rows
3. Find or create `Edge(source, target, relation)`
4. Append `EdgeEvidence` row
5. Recompute `Edge.belief_score` (delegated to Task 9's helper)
6. Detect conflicts (delegated to Tasks 11–12) and update network membership / status (Tasks 13–14)

This task implements steps 1–5 and leaves obvious extension points for the rest. Ungrounded mentions flip `RawPPI.ungrounded=True` (Phase 2 already supports that field per the cross-phase contract; if it doesn't, the test in Step 1 will surface that — fix by adding it).

**Files:**
- Modify: `apps/graph/services.py`
- Modify: `apps/graph/tests/test_normalize_and_integrate.py`

- [ ] **Step 1: Append tests for `normalize_and_integrate`**

```python
from unittest.mock import patch

from graph.services import normalize_and_integrate


def _fake_ground(text):
    """Test stub: maps mention strings -> OntologyEntity via in-memory dict.

    Loaded by tests; the keys are whatever subject/object strings the
    fixtures use. Returns None for misses, matching the production
    contract.
    """
    return _fake_ground.table.get(text.strip().upper())


_fake_ground.table = {}


@pytest.fixture
def gilda_table(il1b_ontology_entity, nfkb1_ontology_entity):
    _fake_ground.table = {
        "IL1B": il1b_ontology_entity,
        "IL-1B": il1b_ontology_entity,
        "INTERLEUKIN-1B": il1b_ontology_entity,
        "NFKB1": nfkb1_ontology_entity,
        "NF-KB1": nfkb1_ontology_entity,
    }
    yield
    _fake_ground.table = {}


@patch("graph.services.ground_mention", side_effect=_fake_ground)
def test_normalize_creates_entities_and_edge(
    mock_ground, db, gilda_table, paper_factory, chunk_factory, raw_ppi_factory,
):
    paper = paper_factory(pmid="44444444", year=2025)
    chunk = chunk_factory(paper=paper)
    raw = raw_ppi_factory(
        subject_text="IL1B", object_text="NFKB1", relation="activates", chunk=chunk,
    )
    normalize_and_integrate([raw.pk])

    assert Entity.objects.count() == 2
    assert Edge.objects.filter(relation="activates").count() == 1
    edge = Edge.objects.get(relation="activates")
    assert edge.evidence.count() == 1


@patch("graph.services.ground_mention", side_effect=_fake_ground)
def test_normalize_is_idempotent_on_same_raw_ppi(
    mock_ground, db, gilda_table, paper_factory, chunk_factory, raw_ppi_factory,
):
    paper = paper_factory(pmid="55555555", year=2025)
    chunk = chunk_factory(paper=paper)
    raw = raw_ppi_factory(
        subject_text="IL1B", object_text="NFKB1", relation="activates", chunk=chunk,
    )
    normalize_and_integrate([raw.pk])
    normalize_and_integrate([raw.pk])

    assert Edge.objects.count() == 1
    assert EdgeEvidence.objects.count() == 1


@patch("graph.services.ground_mention", side_effect=_fake_ground)
def test_normalize_marks_ungrounded_when_subject_unmappable(
    mock_ground, db, gilda_table, paper_factory, chunk_factory, raw_ppi_factory,
):
    paper = paper_factory(pmid="66666666", year=2025)
    chunk = chunk_factory(paper=paper)
    raw = raw_ppi_factory(
        subject_text="UnknownProteinXYZ", object_text="NFKB1",
        relation="activates", chunk=chunk,
    )
    normalize_and_integrate([raw.pk])

    raw.refresh_from_db()
    assert raw.ungrounded is True
    assert Edge.objects.count() == 0
    assert EdgeEvidence.objects.count() == 0


@patch("graph.services.ground_mention", side_effect=_fake_ground)
def test_normalize_marks_ungrounded_when_object_unmappable(
    mock_ground, db, gilda_table, paper_factory, chunk_factory, raw_ppi_factory,
):
    paper = paper_factory(pmid="77777777", year=2025)
    chunk = chunk_factory(paper=paper)
    raw = raw_ppi_factory(
        subject_text="IL1B", object_text="UnknownProteinXYZ",
        relation="activates", chunk=chunk,
    )
    normalize_and_integrate([raw.pk])

    raw.refresh_from_db()
    assert raw.ungrounded is True
    assert Edge.objects.count() == 0


@patch("graph.services.ground_mention", side_effect=_fake_ground)
def test_normalize_dedupes_repeated_evidence(
    mock_ground, db, gilda_table, paper_factory, chunk_factory, raw_ppi_factory,
):
    """Three RawPPIs from three models on the same chunk -> three EdgeEvidences, one Edge."""
    paper = paper_factory(pmid="88888888", year=2025)
    chunk = chunk_factory(paper=paper)
    raws = [
        raw_ppi_factory(
            subject_text="IL1B", object_text="NFKB1", relation="activates",
            chunk=chunk, extractor_model=m,
        )
        for m in ("qwen3_8b", "phi4_14b", "gemma3_12b")
    ]
    normalize_and_integrate([r.pk for r in raws])

    assert Edge.objects.count() == 1
    assert EdgeEvidence.objects.count() == 3


@patch("graph.services.ground_mention", side_effect=_fake_ground)
def test_normalize_recomputes_belief_after_integration(
    mock_ground, db, gilda_table, paper_factory, chunk_factory, raw_ppi_factory,
):
    paper = paper_factory(pmid="99999999", year=2025)
    chunk = chunk_factory(paper=paper)
    raws = [
        raw_ppi_factory(
            subject_text="IL1B", object_text="NFKB1", relation="activates",
            chunk=chunk, extractor_model=m,
        )
        for m in (
            "qwen3_8b", "phi4_14b", "gemma3_12b", "deepseek_r1_32b",
            "devstral_24b", "llama3_1_8b", "medgemma_27b",
        )
    ]
    normalize_and_integrate([r.pk for r in raws])

    edge = Edge.objects.get()
    assert edge.belief_score >= BELIEF_THRESHOLD_ACCEPTED
    assert edge.status == "accepted"
```

- [ ] **Step 2: Run; confirm failure**

```bash
poetry run pytest apps/graph/tests/test_normalize_and_integrate.py -v
```

Expected: `ImportError: cannot import name 'normalize_and_integrate'`.

- [ ] **Step 3: Implement `normalize_and_integrate` in `apps/graph/services.py`**

Append:

```python
# Module-level import for the grounding helper. Done late so test
# patches that target ``graph.services.ground_mention`` work.
from core.services import ground_mention  # noqa: E402


def normalize_and_integrate(raw_ppi_ids: Iterable[int]) -> dict:
    """Promote a batch of RawPPI rows into Entity/Edge/EdgeEvidence.

    Spec §4 — six-step integration:

      1. Gilda-ground subject and object strings (skip on miss)
      2. Upsert Entity rows on top of the OntologyEntity match
      3. Find or create Edge(source, target, relation)
      4. Append EdgeEvidence (idempotent via the unique constraint)
      5. Recompute belief_score and status for every touched Edge
      6. Detect conflicts and reassign NetworkEdgeMembership
         (delegated to detect_conflicts_for_raw and
          reassign_network_membership; see later tasks)

    Returns a small dict of counts useful for logging and tests:
      {'edges_touched': N, 'evidences_added': M, 'ungrounded': K}
    """
    from extract.models import RawPPI  # local import to dodge any phase-import cycles
    from graph.models import Edge, EdgeEvidence, Entity

    touched_edges: set[int] = set()
    evidences_added = 0
    ungrounded = 0

    raws = list(RawPPI.objects.filter(pk__in=list(raw_ppi_ids)).select_related(
        "extraction_run", "extraction_run__chunk__section__paper",
    ))

    for raw in raws:
        subject_oe = ground_mention(raw.subject_text)
        object_oe = ground_mention(raw.object_text)

        if subject_oe is None or object_oe is None:
            if not raw.ungrounded:
                RawPPI.objects.filter(pk=raw.pk).update(ungrounded=True)
            ungrounded += 1
            continue

        with transaction.atomic():
            src_entity, _ = Entity.objects.get_or_create(ontology_entity=subject_oe)
            tgt_entity, _ = Entity.objects.get_or_create(ontology_entity=object_oe)

            edge, _ = Edge.objects.get_or_create(
                source=src_entity, target=tgt_entity, relation=raw.relation,
            )
            _, created = EdgeEvidence.objects.get_or_create(edge=edge, raw_ppi=raw)
            if created:
                evidences_added += 1
            touched_edges.add(edge.pk)

    # Belief recomputation for every touched Edge.
    for edge in Edge.objects.filter(pk__in=touched_edges):
        recompute_edge_belief(edge)

    logger.info(
        "normalize_and_integrate: edges_touched=%d evidences_added=%d ungrounded=%d",
        len(touched_edges), evidences_added, ungrounded,
    )

    # Hook for tasks 11–14 (conflict detection, network membership). Imported
    # at call time so circular-import safety is local.
    _post_integrate_hook(touched_edges, raws)

    return {
        "edges_touched": len(touched_edges),
        "evidences_added": evidences_added,
        "ungrounded": ungrounded,
    }


def _post_integrate_hook(touched_edges: set[int], raws: list) -> None:
    """Stitching point for conflict detection + network membership.

    Implemented in later tasks; this stub keeps normalize_and_integrate
    callable end-to-end while those features are being TDD'd in.
    """
    return None
```

- [ ] **Step 4: Run; confirm green**

```bash
poetry run pytest apps/graph/tests/test_normalize_and_integrate.py -v
```

Expected: `10 passed` (4 prior recompute tests + 6 new).

- [ ] **Step 5: Commit**

```bash
git add apps/graph/services.py apps/graph/tests/test_normalize_and_integrate.py
git commit -m "feat(graph): add normalize_and_integrate (steps 1-5 of spec §4)"
```

---

## Task 11: Intra-paper and inter-paper conflict detection (TDD)

Per spec §4: "Detect Conflict: same (source,target) but opposite relation in same chunk (intra-paper) or other paper (inter-paper) → open Conflict".

Define "opposite relation" via an explicit pair table — `activates` opposes `inhibits`; `phosphorylates` opposes `dephosphorylates`; etc.

**Files:**
- Modify: `apps/graph/services.py`
- Create: `apps/graph/tests/test_conflict_detection.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for graph.services conflict detection."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from graph.models import Conflict, Edge, Entity
from graph.services import (
    OPPOSITE_RELATIONS,
    detect_inter_model_conflicts,
    detect_inter_paper_conflicts,
    detect_intra_paper_conflicts,
)


def _fake_ground(text):
    return _fake_ground.table.get(text.strip().upper())


_fake_ground.table = {}


@pytest.fixture
def gilda_table(il1b_ontology_entity, nfkb1_ontology_entity):
    _fake_ground.table = {"IL1B": il1b_ontology_entity, "NFKB1": nfkb1_ontology_entity}
    yield
    _fake_ground.table = {}


def test_opposite_relations_covers_core_pairs():
    assert OPPOSITE_RELATIONS["activates"] == "inhibits"
    assert OPPOSITE_RELATIONS["inhibits"] == "activates"
    assert OPPOSITE_RELATIONS["phosphorylates"] == "dephosphorylates"
    assert OPPOSITE_RELATIONS["transcribes"] == "represses"


@patch("graph.services.ground_mention", side_effect=_fake_ground)
def test_intra_paper_conflict_when_two_models_disagree_on_one_chunk(
    mock_ground, db, gilda_table, paper_factory, chunk_factory, raw_ppi_factory,
):
    from graph.services import normalize_and_integrate

    paper = paper_factory(pmid="intra-001", year=2025)
    chunk = chunk_factory(paper=paper)
    raw_act = raw_ppi_factory(
        subject_text="IL1B", object_text="NFKB1", relation="activates",
        chunk=chunk, extractor_model="qwen3_8b",
    )
    raw_inh = raw_ppi_factory(
        subject_text="IL1B", object_text="NFKB1", relation="inhibits",
        chunk=chunk, extractor_model="phi4_14b",
    )
    normalize_and_integrate([raw_act.pk, raw_inh.pk])

    detect_intra_paper_conflicts([raw_act.pk, raw_inh.pk])

    conflicts = Conflict.objects.filter(conflict_type="intra_paper")
    assert conflicts.count() == 1
    c = conflicts.first()
    assert {c.edge_a.relation, c.edge_b.relation} == {"activates", "inhibits"}
    assert c.resolution_status == "open"


@patch("graph.services.ground_mention", side_effect=_fake_ground)
def test_no_intra_paper_conflict_when_relations_agree(
    mock_ground, db, gilda_table, paper_factory, chunk_factory, raw_ppi_factory,
):
    from graph.services import normalize_and_integrate

    paper = paper_factory(pmid="intra-002")
    chunk = chunk_factory(paper=paper)
    r1 = raw_ppi_factory(subject_text="IL1B", object_text="NFKB1", relation="activates",
                          chunk=chunk, extractor_model="qwen3_8b")
    r2 = raw_ppi_factory(subject_text="IL1B", object_text="NFKB1", relation="activates",
                          chunk=chunk, extractor_model="phi4_14b")
    normalize_and_integrate([r1.pk, r2.pk])
    detect_intra_paper_conflicts([r1.pk, r2.pk])

    assert Conflict.objects.count() == 0


@patch("graph.services.ground_mention", side_effect=_fake_ground)
def test_inter_paper_conflict_when_different_papers_disagree(
    mock_ground, db, gilda_table, paper_factory, chunk_factory, raw_ppi_factory,
):
    from graph.services import normalize_and_integrate

    paper_a = paper_factory(pmid="inter-001")
    paper_b = paper_factory(pmid="inter-002")
    chunk_a = chunk_factory(paper=paper_a)
    chunk_b = chunk_factory(paper=paper_b)

    r_act = raw_ppi_factory(subject_text="IL1B", object_text="NFKB1", relation="activates",
                             chunk=chunk_a, extractor_model="qwen3_8b")
    r_inh = raw_ppi_factory(subject_text="IL1B", object_text="NFKB1", relation="inhibits",
                             chunk=chunk_b, extractor_model="qwen3_8b")
    normalize_and_integrate([r_act.pk, r_inh.pk])

    detect_inter_paper_conflicts([r_act.pk, r_inh.pk])

    conflicts = Conflict.objects.filter(conflict_type="inter_paper")
    assert conflicts.count() == 1


@patch("graph.services.ground_mention", side_effect=_fake_ground)
def test_inter_model_conflict_when_consensus_below_majority(
    mock_ground, db, gilda_table, paper_factory, chunk_factory, raw_ppi_factory,
):
    from graph.services import normalize_and_integrate

    paper = paper_factory(pmid="inter-model-001")
    chunk = chunk_factory(paper=paper)
    # 4 models say activate, 3 say inhibit → 4/7 is just majority,
    # so we set the threshold at >= 5/7 for consensus and call this a conflict.
    raws_act = [
        raw_ppi_factory(subject_text="IL1B", object_text="NFKB1", relation="activates",
                         chunk=chunk, extractor_model=m)
        for m in ("qwen3_8b", "phi4_14b", "gemma3_12b", "deepseek_r1_32b")
    ]
    raws_inh = [
        raw_ppi_factory(subject_text="IL1B", object_text="NFKB1", relation="inhibits",
                         chunk=chunk, extractor_model=m)
        for m in ("devstral_24b", "llama3_1_8b", "medgemma_27b")
    ]
    normalize_and_integrate([r.pk for r in raws_act + raws_inh])

    detect_inter_model_conflicts([r.pk for r in raws_act + raws_inh])
    assert Conflict.objects.filter(conflict_type="inter_model").count() == 1


@patch("graph.services.ground_mention", side_effect=_fake_ground)
def test_no_inter_model_conflict_when_consensus_at_or_above_threshold(
    mock_ground, db, gilda_table, paper_factory, chunk_factory, raw_ppi_factory,
):
    from graph.services import normalize_and_integrate

    paper = paper_factory(pmid="inter-model-002")
    chunk = chunk_factory(paper=paper)
    # 6 vs 1 → no conflict
    raws_act = [
        raw_ppi_factory(subject_text="IL1B", object_text="NFKB1", relation="activates",
                         chunk=chunk, extractor_model=m)
        for m in ("qwen3_8b", "phi4_14b", "gemma3_12b", "deepseek_r1_32b",
                  "devstral_24b", "llama3_1_8b")
    ]
    raw_inh = raw_ppi_factory(subject_text="IL1B", object_text="NFKB1", relation="inhibits",
                                chunk=chunk, extractor_model="medgemma_27b")
    normalize_and_integrate([r.pk for r in raws_act + [raw_inh]])

    detect_inter_model_conflicts([r.pk for r in raws_act + [raw_inh]])
    assert Conflict.objects.filter(conflict_type="inter_model").count() == 0


@patch("graph.services.ground_mention", side_effect=_fake_ground)
def test_conflict_detection_is_idempotent(
    mock_ground, db, gilda_table, paper_factory, chunk_factory, raw_ppi_factory,
):
    from graph.services import normalize_and_integrate

    paper = paper_factory(pmid="idemp-001")
    chunk = chunk_factory(paper=paper)
    r_act = raw_ppi_factory(subject_text="IL1B", object_text="NFKB1", relation="activates",
                             chunk=chunk, extractor_model="qwen3_8b")
    r_inh = raw_ppi_factory(subject_text="IL1B", object_text="NFKB1", relation="inhibits",
                             chunk=chunk, extractor_model="phi4_14b")
    normalize_and_integrate([r_act.pk, r_inh.pk])
    detect_intra_paper_conflicts([r_act.pk, r_inh.pk])
    detect_intra_paper_conflicts([r_act.pk, r_inh.pk])

    assert Conflict.objects.filter(conflict_type="intra_paper").count() == 1
```

- [ ] **Step 2: Run; confirm failure**

```bash
poetry run pytest apps/graph/tests/test_conflict_detection.py -v
```

Expected: `ImportError`.

- [ ] **Step 3: Implement the detectors in `apps/graph/services.py`**

Append:

```python
# Map a relation to its semantic opposite. Only listed pairs are tracked
# as conflicts; relations without an opposite (e.g. ``binds``) generate
# inter-model conflicts only via the count threshold below.
OPPOSITE_RELATIONS: dict[str, str] = {
    "activates": "inhibits",
    "inhibits": "activates",
    "phosphorylates": "dephosphorylates",
    "dephosphorylates": "phosphorylates",
    "ubiquitinates": "deubiquitinates",
    "deubiquitinates": "ubiquitinates",
    "methylates": "demethylates",  # not in the Edge.RELATIONS list — ignored if absent
    "acetylates": "deacetylates",
    "deacetylates": "acetylates",
    "transcribes": "represses",
    "represses": "transcribes",
}

INTER_MODEL_CONSENSUS_MIN: int = 5  # of 7 models needed to call it "consensus"


def _opposite_edge(edge):
    """Return the persisted opposite-relation Edge if it exists, else None."""
    from graph.models import Edge
    opp_rel = OPPOSITE_RELATIONS.get(edge.relation)
    if opp_rel is None:
        return None
    return Edge.objects.filter(
        source=edge.source, target=edge.target, relation=opp_rel,
    ).first()


def _create_or_find_conflict(edge_a, edge_b, conflict_type: str):
    from graph.models import Conflict
    # Order edge_a/edge_b deterministically to make the uniqueness work.
    a, b = sorted([edge_a, edge_b], key=lambda e: e.pk)
    obj, created = Conflict.objects.get_or_create(
        edge_a=a, edge_b=b, conflict_type=conflict_type,
        defaults={"resolution_status": "open"},
    )
    if created:
        # Downgrade both edges to 'conflicted' (overrides accepted/candidate;
        # conflicts trump belief).
        from graph.models import Edge
        Edge.objects.filter(pk__in=[a.pk, b.pk]).update(status="conflicted")
    return obj


def detect_intra_paper_conflicts(raw_ppi_ids: Iterable[int]) -> int:
    """Open intra-paper Conflict rows when two RawPPIs from the same chunk
    yield opposite-relation Edges.

    Returns the number of NEW conflicts created.
    """
    from extract.models import RawPPI
    from graph.models import Edge

    raws = list(RawPPI.objects.filter(pk__in=list(raw_ppi_ids)).select_related(
        "extraction_run__chunk",
    ))
    by_chunk: dict[int, list[RawPPI]] = {}
    for r in raws:
        by_chunk.setdefault(r.extraction_run.chunk_id, []).append(r)

    new = 0
    for chunk_id, group in by_chunk.items():
        # Find pairs of (subject_text, object_text) with opposite relations
        # within the same chunk.
        seen: dict[tuple, str] = {}
        for r in group:
            key = (r.subject_text.upper(), r.object_text.upper())
            opp = OPPOSITE_RELATIONS.get(r.relation)
            if opp and seen.get(key) == opp:
                edge_a = Edge.objects.filter(
                    relation=r.relation, source__ontology_entity__preferred_label__iexact=r.subject_text,
                ).first()
                edge_b = Edge.objects.filter(
                    relation=opp, source__ontology_entity__preferred_label__iexact=r.subject_text,
                ).first()
                if edge_a and edge_b:
                    _, was_created = _create_or_find_conflict(
                        edge_a, edge_b, "intra_paper",
                    ), None
                    # get_or_create's "created" flag is wrapped; check existence after the call.
                    new += 1 if _create_or_find_conflict(edge_a, edge_b, "intra_paper") and \
                        Conflict.objects.filter(edge_a__in=[edge_a, edge_b],
                                                 edge_b__in=[edge_a, edge_b],
                                                 conflict_type="intra_paper").exists() else 0
            seen[key] = r.relation

    return new


def detect_inter_paper_conflicts(raw_ppi_ids: Iterable[int]) -> int:
    """Open inter-paper conflicts when an Edge has an opposite-relation
    sibling, but their supporting RawPPIs come from different papers.
    """
    from extract.models import RawPPI
    from graph.models import Conflict, Edge, EdgeEvidence

    raws = list(RawPPI.objects.filter(pk__in=list(raw_ppi_ids)).select_related(
        "extraction_run__chunk__section__paper",
    ))
    edge_ids_to_check = set(
        EdgeEvidence.objects.filter(raw_ppi__in=raws).values_list("edge_id", flat=True)
    )

    new = 0
    for edge in Edge.objects.filter(pk__in=edge_ids_to_check):
        opp = _opposite_edge(edge)
        if opp is None:
            continue

        pmids_a = set(EdgeEvidence.objects.filter(edge=edge).values_list(
            "raw_ppi__extraction_run__chunk__section__paper__pmid", flat=True,
        ))
        pmids_b = set(EdgeEvidence.objects.filter(edge=opp).values_list(
            "raw_ppi__extraction_run__chunk__section__paper__pmid", flat=True,
        ))
        # Inter-paper requires at least one PMID supports edge but not opp
        # AND at least one PMID supports opp but not edge.
        if (pmids_a - pmids_b) and (pmids_b - pmids_a):
            before = Conflict.objects.filter(
                conflict_type="inter_paper", edge_a__in=[edge, opp], edge_b__in=[edge, opp],
            ).exists()
            _create_or_find_conflict(edge, opp, "inter_paper")
            if not before:
                new += 1

    return new


def detect_inter_model_conflicts(raw_ppi_ids: Iterable[int]) -> int:
    """Open inter-model conflicts when, for a given (source, target),
    the majority across the 7 extractor models is below INTER_MODEL_CONSENSUS_MIN.
    """
    from collections import Counter

    from extract.models import RawPPI
    from graph.models import Conflict, Edge, EdgeEvidence

    raws = list(RawPPI.objects.filter(pk__in=list(raw_ppi_ids)).select_related(
        "extraction_run",
    ))
    pairs: set[tuple[int, int]] = set()
    edges_by_id = {
        e.pk: e for e in Edge.objects.filter(
            evidence__raw_ppi__in=raws,
        ).select_related("source", "target").distinct()
    }
    for e in edges_by_id.values():
        pairs.add((e.source_id, e.target_id))

    new = 0
    for src_id, tgt_id in pairs:
        sibling_edges = list(Edge.objects.filter(source_id=src_id, target_id=tgt_id))
        if len(sibling_edges) < 2:
            continue
        # Count distinct extractor models per edge.
        model_counts: Counter[str] = Counter()
        rel_to_models: dict[str, set[str]] = {}
        for e in sibling_edges:
            models = set(EdgeEvidence.objects.filter(edge=e).values_list(
                "raw_ppi__extraction_run__extractor_model", flat=True,
            ))
            rel_to_models[e.relation] = models
            for m in models:
                model_counts[m] += 1

        # The "winning" relation is the one with the most distinct models.
        max_models = max(len(ms) for ms in rel_to_models.values())
        if max_models < INTER_MODEL_CONSENSUS_MIN:
            # No relation reached consensus → flag a pairwise inter-model conflict
            # between the top-two relations.
            ranked = sorted(rel_to_models.items(), key=lambda kv: -len(kv[1]))
            if len(ranked) < 2:
                continue
            rel_a, rel_b = ranked[0][0], ranked[1][0]
            edge_a = next(e for e in sibling_edges if e.relation == rel_a)
            edge_b = next(e for e in sibling_edges if e.relation == rel_b)
            before = Conflict.objects.filter(
                conflict_type="inter_model", edge_a__in=[edge_a, edge_b],
                edge_b__in=[edge_a, edge_b],
            ).exists()
            _create_or_find_conflict(edge_a, edge_b, "inter_model")
            if not before:
                new += 1

    return new
```

> **Implementation note:** The intra-paper detector above does extra work
> looking up edges by `subject_text.upper()` because the same chunk can
> produce two `RawPPI`s with different surface forms that ground to the
> same `OntologyEntity`. The simpler alternative — looking up edges by
> matching grounded entities — is what the test actually exercises, so
> if any of the seven asserts in `test_conflict_detection.py` fail, prefer
> tightening the implementation to use grounded entities rather than
> loosening the tests.

- [ ] **Step 4: Wire the detectors into `_post_integrate_hook`**

Replace the stub in `apps/graph/services.py`:

```python
def _post_integrate_hook(touched_edges: set[int], raws: list) -> None:
    raw_ids = [r.pk for r in raws]
    detect_intra_paper_conflicts(raw_ids)
    detect_inter_paper_conflicts(raw_ids)
    detect_inter_model_conflicts(raw_ids)
    # Task 13 will append: reassign_network_membership(touched_edges)
```

- [ ] **Step 5: Run; confirm green**

```bash
poetry run pytest apps/graph/tests/test_conflict_detection.py -v
```

Expected: `7 passed`.

- [ ] **Step 6: Commit**

```bash
git add apps/graph/services.py apps/graph/tests/test_conflict_detection.py
git commit -m "feat(graph): detect intra-, inter-paper, inter-model conflicts"
```

---

## Task 12: Network membership reassignment + STALE demotion (TDD)

Per spec §4 and §7: when a new edge enters the graph and its endpoint entities match any `Network.root_entities`, create a `NetworkEdgeMembership` row; if the network was `verified`, demote it to `stale`.

**Files:**
- Modify: `apps/graph/services.py`
- Modify: `apps/graph/tests/test_network_membership.py`

- [ ] **Step 1: Append the failing tests**

```python
from unittest.mock import patch

from graph.services import reassign_network_membership


def _fake_ground(text):
    return _fake_ground.table.get(text.strip().upper())


_fake_ground.table = {}


@pytest.fixture
def gilda_table(il1b_ontology_entity, nfkb1_ontology_entity, sirt1_ontology_entity):
    _fake_ground.table = {
        "IL1B": il1b_ontology_entity,
        "NFKB1": nfkb1_ontology_entity,
        "SIRT1": sirt1_ontology_entity,
    }
    yield
    _fake_ground.table = {}


@patch("graph.services.ground_mention", side_effect=_fake_ground)
def test_new_edge_creates_membership_when_endpoint_matches_root(
    mock_ground, db, gilda_table, nfkb_network, paper_factory, chunk_factory, raw_ppi_factory,
):
    from graph.services import normalize_and_integrate

    paper = paper_factory(pmid="mem-001", year=2025)
    chunk = chunk_factory(paper=paper)
    raw = raw_ppi_factory(
        subject_text="IL1B", object_text="NFKB1", relation="activates", chunk=chunk,
    )
    normalize_and_integrate([raw.pk])

    edge = Edge.objects.get()
    assert NetworkEdgeMembership.objects.filter(network=nfkb_network, edge=edge).exists()


@patch("graph.services.ground_mention", side_effect=_fake_ground)
def test_no_membership_when_no_endpoint_matches_root(
    mock_ground, db, gilda_table, nfkb_network, sirt1_ontology_entity,
    paper_factory, chunk_factory, raw_ppi_factory,
):
    from graph.services import normalize_and_integrate

    # SIRT1 → IL1B has neither endpoint as NFKB1 (the only root_entity)
    paper = paper_factory(pmid="mem-002", year=2025)
    chunk = chunk_factory(paper=paper)
    raw = raw_ppi_factory(
        subject_text="SIRT1", object_text="IL1B", relation="inhibits", chunk=chunk,
    )
    normalize_and_integrate([raw.pk])

    edge = Edge.objects.get()
    assert not NetworkEdgeMembership.objects.filter(network=nfkb_network, edge=edge).exists()


@patch("graph.services.ground_mention", side_effect=_fake_ground)
def test_verified_network_demoted_to_stale_on_new_edge(
    mock_ground, db, gilda_table, nfkb_network, paper_factory, chunk_factory, raw_ppi_factory,
):
    from graph.services import normalize_and_integrate

    nfkb_network.pipeline_status = "verified"
    nfkb_network.save()

    paper = paper_factory(pmid="mem-003", year=2025)
    chunk = chunk_factory(paper=paper)
    raw = raw_ppi_factory(
        subject_text="IL1B", object_text="NFKB1", relation="activates", chunk=chunk,
    )
    normalize_and_integrate([raw.pk])

    nfkb_network.refresh_from_db()
    assert nfkb_network.pipeline_status == "stale"


@patch("graph.services.ground_mention", side_effect=_fake_ground)
def test_idle_network_remains_idle_unless_edge_arrives(
    mock_ground, db, gilda_table, nfkb_network, sirt1_ontology_entity,
    paper_factory, chunk_factory, raw_ppi_factory,
):
    """A network unrelated to the new edge should not change state."""
    from graph.services import normalize_and_integrate

    nfkb_network.pipeline_status = "idle"
    nfkb_network.save()

    paper = paper_factory(pmid="mem-004", year=2025)
    chunk = chunk_factory(paper=paper)
    raw = raw_ppi_factory(
        subject_text="SIRT1", object_text="IL1B", relation="inhibits", chunk=chunk,
    )
    normalize_and_integrate([raw.pk])

    nfkb_network.refresh_from_db()
    assert nfkb_network.pipeline_status == "idle"


@patch("graph.services.ground_mention", side_effect=_fake_ground)
def test_reassign_network_membership_is_idempotent(
    mock_ground, db, gilda_table, nfkb_network, paper_factory, chunk_factory, raw_ppi_factory,
):
    from graph.services import normalize_and_integrate

    paper = paper_factory(pmid="mem-005", year=2025)
    chunk = chunk_factory(paper=paper)
    raw = raw_ppi_factory(
        subject_text="IL1B", object_text="NFKB1", relation="activates", chunk=chunk,
    )
    normalize_and_integrate([raw.pk])

    edge = Edge.objects.get()
    reassign_network_membership({edge.pk})
    reassign_network_membership({edge.pk})

    assert NetworkEdgeMembership.objects.filter(network=nfkb_network, edge=edge).count() == 1
```

- [ ] **Step 2: Implement `reassign_network_membership` in `apps/graph/services.py`**

Append:

```python
def reassign_network_membership(edge_ids: Iterable[int]) -> dict:
    """For each edge in ``edge_ids``, create NetworkEdgeMembership rows for
    every Network whose ``root_entities`` references either endpoint's
    Identifier.

    Demote affected networks from ``verified`` → ``stale`` per spec §7.

    Returns {'memberships_created': N, 'networks_demoted': M}.
    """
    from graph.models import Edge, NetworkEdgeMembership
    from networks.models import Network

    created = 0
    demoted = 0
    edges = list(
        Edge.objects.filter(pk__in=list(edge_ids))
        .select_related("source__ontology_entity", "target__ontology_entity")
        .prefetch_related(
            "source__ontology_entity__identifiers",
            "target__ontology_entity__identifiers",
        )
    )

    for edge in edges:
        endpoint_ids: set[tuple[str, str]] = set()
        for entity in (edge.source, edge.target):
            for ident in entity.ontology_entity.identifiers.all():
                endpoint_ids.add((ident.scheme, ident.value))

        # Any Network whose root_entities mentions any of these (scheme, value)
        # pairs is a candidate. root_entities is a JSONB list of dicts.
        for network in Network.objects.all():
            roots = network.root_entities or []
            wanted = {(r.get("scheme"), r.get("value")) for r in roots if r.get("scheme")}
            if endpoint_ids & wanted:
                _, was_created = NetworkEdgeMembership.objects.get_or_create(
                    network=network, edge=edge, defaults={"relevance": 1.0},
                )
                if was_created:
                    created += 1
                    if network.pipeline_status == "verified":
                        Network.objects.filter(pk=network.pk).update(pipeline_status="stale")
                        demoted += 1
                    elif network.pipeline_status == "idle":
                        Network.objects.filter(pk=network.pk).update(pipeline_status="stale")

    return {"memberships_created": created, "networks_demoted": demoted}
```

- [ ] **Step 3: Wire it into `_post_integrate_hook`**

Replace the existing hook body:

```python
def _post_integrate_hook(touched_edges: set[int], raws: list) -> None:
    raw_ids = [r.pk for r in raws]
    detect_intra_paper_conflicts(raw_ids)
    detect_inter_paper_conflicts(raw_ids)
    detect_inter_model_conflicts(raw_ids)
    reassign_network_membership(touched_edges)
```

- [ ] **Step 4: Run; confirm green**

```bash
poetry run pytest apps/graph/tests/test_network_membership.py -v
```

Expected: previous 2 still green + 5 new = `7 passed`.

- [ ] **Step 5: Commit**

```bash
git add apps/graph/services.py apps/graph/tests/test_network_membership.py
git commit -m "feat(graph): assign NetworkEdgeMembership and demote verified→stale"
```

---

## Task 13: `graph.integrate_pending` Celery task and Beat schedule (TDD)

Per spec §6: `graph.integrate_pending` runs every 10 min, batches `RawPPI` rows that haven't been integrated, and calls `normalize_and_integrate`. Batch size 10–50.

Decision: We mark a `RawPPI` as integrated by checking whether any `EdgeEvidence` row references it, OR `ungrounded=True`. This avoids a new boolean column on `RawPPI`.

**Files:**
- Modify: `apps/graph/tasks.py`
- Create: `apps/graph/tests/test_tasks.py`
- Modify: `interactome/settings/base.py` (Beat schedule)

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for graph.tasks.integrate_pending."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from graph.models import Edge, EdgeEvidence
from graph.tasks import integrate_pending


def _fake_ground(text):
    return _fake_ground.table.get(text.strip().upper())


_fake_ground.table = {}


@pytest.fixture
def gilda_table(il1b_ontology_entity, nfkb1_ontology_entity):
    _fake_ground.table = {"IL1B": il1b_ontology_entity, "NFKB1": nfkb1_ontology_entity}
    yield
    _fake_ground.table = {}


@patch("graph.services.ground_mention", side_effect=_fake_ground)
def test_integrate_pending_processes_unintegrated_raw_ppis(
    mock_ground, db, gilda_table, paper_factory, chunk_factory, raw_ppi_factory, settings,
):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    paper = paper_factory(pmid="pending-001", year=2025)
    chunk = chunk_factory(paper=paper)
    raw_ppi_factory(subject_text="IL1B", object_text="NFKB1", relation="activates", chunk=chunk)

    integrate_pending.delay()

    assert Edge.objects.count() == 1


@patch("graph.services.ground_mention", side_effect=_fake_ground)
def test_integrate_pending_skips_already_integrated(
    mock_ground, db, gilda_table, paper_factory, chunk_factory, raw_ppi_factory, settings,
):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    paper = paper_factory(pmid="pending-002", year=2025)
    chunk = chunk_factory(paper=paper)
    raw_ppi_factory(subject_text="IL1B", object_text="NFKB1", relation="activates", chunk=chunk)

    integrate_pending.delay()
    edge_count_before = Edge.objects.count()
    evidence_count_before = EdgeEvidence.objects.count()

    integrate_pending.delay()
    assert Edge.objects.count() == edge_count_before
    assert EdgeEvidence.objects.count() == evidence_count_before


@patch("graph.services.ground_mention", side_effect=_fake_ground)
def test_integrate_pending_respects_batch_size(
    mock_ground, db, gilda_table, paper_factory, chunk_factory, raw_ppi_factory, settings,
):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    paper = paper_factory(pmid="pending-003", year=2025)
    chunk = chunk_factory(paper=paper)
    # 75 raw PPIs; default batch size 50 → first call integrates 50, second 25
    for i in range(75):
        raw_ppi_factory(
            subject_text="IL1B", object_text="NFKB1", relation="activates",
            chunk=chunk, extractor_model=f"model_{i % 7}",
        )

    # First sweep
    integrate_pending.delay()
    assert EdgeEvidence.objects.count() == 50

    # Second sweep
    integrate_pending.delay()
    assert EdgeEvidence.objects.count() == 75


@patch("graph.services.ground_mention", side_effect=_fake_ground)
def test_integrate_pending_skips_ungrounded(
    mock_ground, db, gilda_table, paper_factory, chunk_factory, raw_ppi_factory, settings,
):
    from extract.models import RawPPI

    settings.CELERY_TASK_ALWAYS_EAGER = True
    paper = paper_factory(pmid="pending-004", year=2025)
    chunk = chunk_factory(paper=paper)
    raw = raw_ppi_factory(
        subject_text="UnknownXYZ", object_text="NFKB1", relation="activates", chunk=chunk,
    )

    integrate_pending.delay()  # first pass marks it ungrounded
    raw.refresh_from_db()
    assert raw.ungrounded is True

    # Second pass: no work to do
    integrate_pending.delay()
    assert Edge.objects.count() == 0
```

- [ ] **Step 2: Implement the task in `apps/graph/tasks.py`**

```python
"""graph Celery tasks."""
from __future__ import annotations

import logging

from celery import shared_task
from django.db.models import Q

logger = logging.getLogger(__name__)

INTEGRATE_BATCH_SIZE = 50


@shared_task(name="graph.integrate_pending")
def integrate_pending() -> dict:
    """Batch-process unintegrated RawPPIs into Edges.

    Spec §4: "Integration is debounced. graph.normalize_and_integrate
    batches RawPPIs per (paper × model) so the Bayes update on belief
    scores doesn't thrash. Batch size 10–50."
    """
    from extract.models import RawPPI
    from graph.services import normalize_and_integrate

    # Pending = not ungrounded AND no EdgeEvidence row pointing at it AND
    # parent ExtractionRun is done.
    pending = (
        RawPPI.objects.filter(ungrounded=False, extraction_run__status="done")
        .filter(edge_evidence__isnull=True)
        .order_by("pk")
        .values_list("pk", flat=True)[:INTEGRATE_BATCH_SIZE]
    )
    pending_ids = list(pending)

    if not pending_ids:
        logger.info("integrate_pending: no work")
        return {"processed": 0}

    result = normalize_and_integrate(pending_ids)
    logger.info("integrate_pending: %s", result)
    return result
```

- [ ] **Step 3: Add to Beat schedule in `interactome/settings/base.py`**

After the existing Celery configuration, add (or merge into) a `CELERY_BEAT_SCHEDULE` dict:

```python
CELERY_BEAT_SCHEDULE = {
    **globals().get("CELERY_BEAT_SCHEDULE", {}),
    "graph-integrate-pending": {
        "task": "graph.integrate_pending",
        "schedule": 60 * 10,  # every 10 min — spec §6
        "options": {"queue": "q.io"},
    },
}
```

- [ ] **Step 4: Run; confirm green**

```bash
poetry run pytest apps/graph/tests/test_tasks.py -v
```

Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add apps/graph/tasks.py apps/graph/tests/test_tasks.py interactome/settings/base.py
git commit -m "feat(graph): add integrate_pending task with 10-min Beat schedule"
```

---

## Task 14: Dev UI view + JSON endpoint (TDD)

A single Django view that renders one network's edge set with Cytoscape.js. URL: `/graph/dev/networks/<code>/`. A companion JSON endpoint at `/graph/dev/networks/<code>/edges.json` feeds the graph data.

**Files:**
- Modify: `apps/graph/views.py`
- Modify: `apps/graph/urls.py`
- Create: `apps/graph/templates/graph/dev_network.html`
- Create: `apps/graph/tests/test_views.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for graph dev UI."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from django.test import Client


def _fake_ground(text):
    return _fake_ground.table.get(text.strip().upper())


_fake_ground.table = {}


@pytest.fixture
def gilda_table(il1b_ontology_entity, nfkb1_ontology_entity):
    _fake_ground.table = {"IL1B": il1b_ontology_entity, "NFKB1": nfkb1_ontology_entity}
    yield
    _fake_ground.table = {}


@pytest.fixture
def nfkb_network_with_edge(db, gilda_table, nfkb1_ontology_entity, paper_factory, chunk_factory, raw_ppi_factory):
    from networks.models import Network
    from graph.services import normalize_and_integrate

    network = Network.objects.create(
        code="nfkb_axis",
        title="NF-κB axis",
        category="I",
        root_entities=[{"scheme": "HGNC", "value": "7794"}],
        pipeline_status="idle",
    )
    paper = paper_factory(pmid="ui-001", year=2025)
    chunk = chunk_factory(paper=paper)
    with patch("graph.services.ground_mention", side_effect=_fake_ground):
        raw = raw_ppi_factory(
            subject_text="IL1B", object_text="NFKB1", relation="activates", chunk=chunk,
        )
        normalize_and_integrate([raw.pk])
    return network


@pytest.fixture
def authed_client() -> Client:
    return Client(HTTP_REMOTE_USER="fchemorion")


def test_dev_network_view_returns_200(db, nfkb_network_with_edge, authed_client):
    r = authed_client.get(f"/graph/dev/networks/{nfkb_network_with_edge.code}/")
    assert r.status_code == 200


def test_dev_network_view_contains_network_title(db, nfkb_network_with_edge, authed_client):
    r = authed_client.get(f"/graph/dev/networks/{nfkb_network_with_edge.code}/")
    assert b"NF-" in r.content


def test_dev_network_view_renders_cytoscape(db, nfkb_network_with_edge, authed_client):
    r = authed_client.get(f"/graph/dev/networks/{nfkb_network_with_edge.code}/")
    assert b"cytoscape" in r.content.lower()


def test_dev_network_view_404_on_missing_code(db, authed_client):
    r = authed_client.get("/graph/dev/networks/does_not_exist/")
    assert r.status_code == 404


def test_edges_json_endpoint_returns_edges(db, nfkb_network_with_edge, authed_client):
    r = authed_client.get(f"/graph/dev/networks/{nfkb_network_with_edge.code}/edges.json")
    assert r.status_code == 200
    data = r.json()
    assert "nodes" in data and "edges" in data
    assert len(data["edges"]) == 1
    e = data["edges"][0]
    assert e["data"]["source_label"] == "IL1B"
    assert e["data"]["target_label"] == "NFKB1"
    assert e["data"]["relation"] == "activates"
    assert "belief" in e["data"]
    assert "status" in e["data"]


def test_edges_json_includes_nodes_with_identifiers(db, nfkb_network_with_edge, authed_client):
    r = authed_client.get(f"/graph/dev/networks/{nfkb_network_with_edge.code}/edges.json")
    data = r.json()
    labels = {n["data"]["label"] for n in data["nodes"]}
    assert labels == {"IL1B", "NFKB1"}
    # Each node carries its primary identifier IRI
    for n in data["nodes"]:
        assert n["data"]["iri"].startswith("https://identifiers.org/hgnc:")
```

- [ ] **Step 2: Implement the views in `apps/graph/views.py`**

```python
"""graph dev UI views.

Minimal — Phase 5 owns the full verification surface. These exist only
so Phase 3 can be demoed: load /graph/dev/networks/nfkb_axis/ and see
the NF-κB axis rendered.
"""
from __future__ import annotations

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render

from graph.models import NetworkEdgeMembership


def dev_network(request, code: str):
    from networks.models import Network
    network = get_object_or_404(Network, code=code)
    return render(request, "graph/dev_network.html", {"network": network})


def dev_network_edges_json(request, code: str):
    from networks.models import Network
    network = get_object_or_404(Network, code=code)

    memberships = (
        NetworkEdgeMembership.objects.filter(network=network)
        .select_related(
            "edge__source__ontology_entity",
            "edge__target__ontology_entity",
        )
        .prefetch_related(
            "edge__source__ontology_entity__identifiers",
            "edge__target__ontology_entity__identifiers",
        )
    )

    nodes: dict[int, dict] = {}
    edges: list[dict] = []

    for m in memberships:
        for entity in (m.edge.source, m.edge.target):
            if entity.pk in nodes:
                continue
            pri = entity.primary_identifier
            nodes[entity.pk] = {
                "data": {
                    "id": f"n{entity.pk}",
                    "label": entity.preferred_label,
                    "iri": pri.as_iri() if pri else "",
                    "entity_type": entity.ontology_entity.entity_type,
                },
            }
        edges.append({
            "data": {
                "id": f"e{m.edge.pk}",
                "source": f"n{m.edge.source_id}",
                "target": f"n{m.edge.target_id}",
                "source_label": m.edge.source.preferred_label,
                "target_label": m.edge.target.preferred_label,
                "relation": m.edge.relation,
                "belief": round(m.edge.belief_score, 3),
                "status": m.edge.status,
                "relevance": m.relevance,
            },
        })

    return JsonResponse({"nodes": list(nodes.values()), "edges": edges})
```

- [ ] **Step 3: Wire the URL routes in `apps/graph/urls.py`**

```python
"""graph URL routes."""
from __future__ import annotations

from django.urls import path

from graph import views

app_name = "graph"
urlpatterns = [
    path("dev/networks/<str:code>/", views.dev_network, name="dev-network"),
    path(
        "dev/networks/<str:code>/edges.json",
        views.dev_network_edges_json,
        name="dev-network-edges-json",
    ),
]
```

- [ ] **Step 4: Create the template `apps/graph/templates/graph/dev_network.html`**

```html
{% load static %}
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{{ network.title }} — dev graph view</title>
  <script src="https://unpkg.com/cytoscape@3.30.2/dist/cytoscape.min.js"></script>
  <style>
    body { font-family: -apple-system, system-ui, sans-serif; margin: 0; padding: 0; }
    header { padding: 12px 20px; background: #1f2937; color: #fff; }
    header h1 { margin: 0; font-size: 18px; }
    header .meta { font-size: 12px; opacity: 0.8; margin-top: 4px; }
    #cy { width: 100vw; height: calc(100vh - 60px); background: #f9fafb; }
    .legend { position: absolute; right: 16px; top: 76px; background: #fff;
              border: 1px solid #d1d5db; border-radius: 6px; padding: 8px 12px;
              font-size: 12px; }
    .legend .row { display: flex; align-items: center; gap: 6px; margin: 2px 0; }
    .swatch { width: 14px; height: 4px; border-radius: 2px; }
  </style>
</head>
<body>
  <header>
    <h1>{{ network.title }}</h1>
    <div class="meta">
      code: <code>{{ network.code }}</code> ·
      status: <strong>{{ network.pipeline_status }}</strong> ·
      Phase 3 dev view (full verification UI: Phase 5)
    </div>
  </header>
  <div id="cy"></div>
  <div class="legend">
    <div class="row"><span class="swatch" style="background:#16a34a"></span> accepted</div>
    <div class="row"><span class="swatch" style="background:#6b7280"></span> candidate</div>
    <div class="row"><span class="swatch" style="background:#dc2626"></span> conflicted</div>
    <div class="row"><span class="swatch" style="background:#9ca3af; opacity:0.5"></span> rejected</div>
  </div>
  <script>
    fetch("{% url 'graph:dev-network-edges-json' code=network.code %}")
      .then(r => r.json())
      .then(graph => {
        cytoscape({
          container: document.getElementById("cy"),
          elements: { nodes: graph.nodes, edges: graph.edges },
          style: [
            {
              selector: "node",
              style: {
                "label": "data(label)",
                "background-color": "#3b82f6",
                "color": "#111",
                "text-valign": "center",
                "text-halign": "center",
                "font-size": 12,
                "width": "label",
                "height": 32,
                "padding": "6px",
                "shape": "round-rectangle",
              },
            },
            {
              selector: "edge",
              style: {
                "label": "data(relation)",
                "font-size": 10,
                "curve-style": "bezier",
                "target-arrow-shape": "triangle",
                "line-color": "ele => ({accepted:'#16a34a',candidate:'#6b7280',conflicted:'#dc2626',rejected:'#9ca3af'})[ele.data('status')]",
                "target-arrow-color": "ele => ({accepted:'#16a34a',candidate:'#6b7280',conflicted:'#dc2626',rejected:'#9ca3af'})[ele.data('status')]",
                "width": "mapData(belief, 0, 1, 1, 4)",
                "opacity": "ele => ele.data('status') === 'rejected' ? 0.4 : 1.0",
              },
            },
          ],
          layout: { name: "cose", animate: false },
        });
      });
  </script>
</body>
</html>
```

- [ ] **Step 5: Run; confirm green**

```bash
poetry run pytest apps/graph/tests/test_views.py -v
```

Expected: `6 passed`.

- [ ] **Step 6: Commit**

```bash
git add apps/graph/views.py apps/graph/urls.py apps/graph/templates/ apps/graph/tests/test_views.py
git commit -m "feat(graph): add dev UI for browsing one network with Cytoscape.js"
```

---

## Task 15: Django admin registration

Lets ops/devs poke at the new tables. No tests — admin is mostly declarative and exercised manually.

**Files:**
- Modify: `apps/graph/admin.py`
- Modify: `apps/core/admin.py` (create if missing)

- [ ] **Step 1: Update `apps/core/admin.py`** (create file if it doesn't exist from Phase 0)

```python
"""Django admin for core."""
from __future__ import annotations

from django.contrib import admin

from core.models import Identifier, OntologyEntity


class IdentifierInline(admin.TabularInline):
    model = Identifier
    extra = 0
    fields = ("scheme", "value", "is_primary")


@admin.register(OntologyEntity)
class OntologyEntityAdmin(admin.ModelAdmin):
    list_display = ("preferred_label", "entity_type", "created_at")
    list_filter = ("entity_type",)
    search_fields = ("preferred_label",)
    inlines = [IdentifierInline]


@admin.register(Identifier)
class IdentifierAdmin(admin.ModelAdmin):
    list_display = ("entity", "scheme", "value", "is_primary")
    list_filter = ("scheme", "is_primary")
    search_fields = ("value", "entity__preferred_label")
```

- [ ] **Step 2: Implement `apps/graph/admin.py`**

```python
"""Django admin for graph."""
from __future__ import annotations

from django.contrib import admin

from graph.models import Conflict, Edge, EdgeEvidence, Entity, NetworkEdgeMembership


@admin.register(Entity)
class EntityAdmin(admin.ModelAdmin):
    list_display = ("preferred_label", "ontology_entity", "created_at")
    search_fields = ("ontology_entity__preferred_label",)


class EdgeEvidenceInline(admin.TabularInline):
    model = EdgeEvidence
    extra = 0
    readonly_fields = ("raw_ppi", "created_at")


@admin.register(Edge)
class EdgeAdmin(admin.ModelAdmin):
    list_display = ("__str__", "status", "belief_score", "created_at")
    list_filter = ("status", "relation")
    search_fields = (
        "source__ontology_entity__preferred_label",
        "target__ontology_entity__preferred_label",
    )
    readonly_fields = ("belief_score", "status", "created_at", "updated_at")
    inlines = [EdgeEvidenceInline]


@admin.register(Conflict)
class ConflictAdmin(admin.ModelAdmin):
    list_display = ("__str__", "conflict_type", "resolution_status", "created_at")
    list_filter = ("conflict_type", "resolution_status")


@admin.register(NetworkEdgeMembership)
class NetworkEdgeMembershipAdmin(admin.ModelAdmin):
    list_display = ("network", "edge", "relevance")
    list_filter = ("network",)
```

- [ ] **Step 3: Verify Django boots cleanly**

```bash
poetry run python manage.py check
```

- [ ] **Step 4: Commit**

```bash
git add apps/core/admin.py apps/graph/admin.py
git commit -m "feat: register graph and ontology models in Django admin"
```

---

## Task 16: Documentation comment on `services.py` and module index

Add a short module-level overview to `apps/graph/services.py` listing the public symbols. Helps future-phase developers find the entry points.

**Files:**
- Modify: `apps/graph/services.py`

- [ ] **Step 1: Prepend a public-API index right under the existing docstring**

Insert after the `"""... §10 ..."""` module docstring and before any `from __future__` line — or after `from __future__` if the docstring sits below it. The exact placement: as the first executable statement after imports.

```python
__all__ = [
    "BAYES_PRIOR",
    "BELIEF_THRESHOLD_ACCEPTED",
    "BELIEF_THRESHOLD_REJECTED",
    "INTER_MODEL_CONSENSUS_MIN",
    "OPPOSITE_RELATIONS",
    "RECENCY_HALFLIFE_DAYS",
    "bayes_belief",
    "detect_inter_model_conflicts",
    "detect_inter_paper_conflicts",
    "detect_intra_paper_conflicts",
    "mean_recency_for_dates",
    "normalize_and_integrate",
    "reassign_network_membership",
    "recency_weight_for_date",
    "recompute_edge_belief",
]
```

- [ ] **Step 2: Run the full graph test suite**

```bash
poetry run pytest apps/graph -v
```

Expected: all tests still green.

- [ ] **Step 3: Commit**

```bash
git add apps/graph/services.py
git commit -m "docs(graph): document services.py public API via __all__"
```

---

## Task 17: ruff + mypy clean

**Files:** none new; this is the lint pass.

- [ ] **Step 1: Run ruff with autofix**

```bash
poetry run ruff check apps/graph apps/core --fix
poetry run ruff format apps/graph apps/core
```

- [ ] **Step 2: Run ruff in check-only mode to confirm green**

```bash
poetry run ruff check apps/graph apps/core
poetry run ruff format --check apps/graph apps/core
```

Expected: `All checks passed!` from both commands.

- [ ] **Step 3: Run mypy**

```bash
poetry run mypy apps/graph apps/core
```

Expected: `Success: no issues found in N source files.`

If any mypy error is about Django's `manager` attribute mis-resolving, ensure `django-stubs` is installed (per Phase 0 `pyproject.toml`). Do NOT add `# type: ignore` to silence real type errors.

- [ ] **Step 4: Commit (if any autofixes applied)**

```bash
git status
# If anything changed:
git add apps/graph apps/core
git commit -m "style: apply ruff format + lint fixes for Phase 3"
```

---

## Task 18: End-to-end manual verification

Drive the full Phase 3 path from `RawPPI` rows → graph view in a browser.

- [ ] **Step 1: Bring up the stack and apply migrations**

```bash
docker-compose up -d
docker-compose exec web python manage.py migrate
```

Expected: migrations for `core` (0002) and `graph` (0001, 0002, 0003) all `OK`.

- [ ] **Step 2: Seed an NF-κB network**

```bash
docker-compose exec web python manage.py shell <<'PY'
from networks.models import Network
Network.objects.update_or_create(
    code="nfkb_axis",
    defaults={
        "title": "NF-κB axis (Phase 3 demo)",
        "category": "I",
        "root_entities": [{"scheme": "HGNC", "value": "7794"}],  # NFKB1
        "pipeline_status": "idle",
    },
)
print("seeded")
PY
```

- [ ] **Step 3: Inject a handful of `RawPPI` rows**

```bash
docker-compose exec web python manage.py shell <<'PY'
from datetime import date
from corpus.models import Paper
from papers.models import Chunk, Section
from extract.models import ExtractionRun, RawPPI

paper, _ = Paper.objects.get_or_create(
    pmid="demo-phase3-001",
    defaults={"doi": "10.0/demo1", "title": "Demo paper", "abstract": "",
              "pub_date": date(2025, 6, 1), "is_original": True},
)
section, _ = Section.objects.get_or_create(
    paper=paper, doco_type="Results", order=0, defaults={"raw_xml": ""},
)
chunk, _ = Chunk.objects.get_or_create(
    section=section, index=0,
    defaults={"text": "IL1B activates NFKB1 in nucleus pulposus cells.",
              "char_start": 0, "char_end": 50},
)
for m in ["qwen3_8b", "phi4_14b", "gemma3_12b", "deepseek_r1_32b",
          "devstral_24b", "llama3_1_8b", "medgemma_27b"]:
    run, _ = ExtractionRun.objects.get_or_create(
        chunk=chunk, extractor_model=m, prompt_version="v1",
        defaults={"status": "done"},
    )
    RawPPI.objects.get_or_create(
        extraction_run=run, subject_text="IL1B", object_text="NFKB1",
        relation="activates",
        defaults={"evidence_span_start": 0, "evidence_span_end": 50,
                  "confidence": 0.92, "ungrounded": False},
    )
print("seeded", RawPPI.objects.filter(extraction_run__chunk=chunk).count(), "RawPPIs")
PY
```

- [ ] **Step 4: Run integration manually**

```bash
docker-compose exec web python manage.py shell <<'PY'
from graph.tasks import integrate_pending
print(integrate_pending())
PY
```

Expected: a result dict with `edges_touched: 1` and `evidences_added: 7`.

- [ ] **Step 5: Browse the dev UI**

In a browser, with the Authelia / Caddy stack:
```
https://localhost/graph/dev/networks/nfkb_axis/
```

(Bypass-Authelia for local dev: hit `http://localhost:8000/graph/dev/networks/nfkb_axis/` directly through gunicorn. Use `-k` or accept the self-signed cert as in Phase 0.)

Expected:
- Page renders with the network title in the header.
- Cytoscape graph shows two nodes (IL1B, NFKB1) connected by an `activates` edge in green (accepted status).
- The legend in the corner explains the four status colours.

- [ ] **Step 6: Verify a conflict renders**

```bash
docker-compose exec web python manage.py shell <<'PY'
from datetime import date
from corpus.models import Paper
from papers.models import Chunk, Section
from extract.models import ExtractionRun, RawPPI
from graph.tasks import integrate_pending

paper, _ = Paper.objects.get_or_create(
    pmid="demo-phase3-002",
    defaults={"doi": "10.0/demo2", "title": "Demo conflict",
              "abstract": "", "pub_date": date(2025, 7, 1), "is_original": True},
)
section, _ = Section.objects.get_or_create(paper=paper, doco_type="Results", order=0,
                                             defaults={"raw_xml": ""})
chunk, _ = Chunk.objects.get_or_create(section=section, index=0,
    defaults={"text": "IL1B inhibits NFKB1 here.", "char_start": 0, "char_end": 25})
run, _ = ExtractionRun.objects.get_or_create(
    chunk=chunk, extractor_model="qwen3_8b", prompt_version="v1",
    defaults={"status": "done"},
)
RawPPI.objects.get_or_create(
    extraction_run=run, subject_text="IL1B", object_text="NFKB1",
    relation="inhibits",
    defaults={"evidence_span_start": 0, "evidence_span_end": 25,
              "confidence": 0.8, "ungrounded": False},
)
print(integrate_pending())

from graph.models import Conflict
print("conflicts:", list(Conflict.objects.values("conflict_type", "resolution_status")))
PY
```

Expected output includes at least one `inter_paper` conflict with `resolution_status='open'`. Reloading the dev UI now shows both `activates` (still accepted) and `inhibits` (newly conflicted) edges in red.

- [ ] **Step 7: Verify the verified→stale demotion**

```bash
docker-compose exec web python manage.py shell <<'PY'
from networks.models import Network
n = Network.objects.get(code="nfkb_axis")
n.pipeline_status = "verified"
n.save()
PY
```

Repeat Step 6 with a new pmid (`demo-phase3-003`) and confirm:

```bash
docker-compose exec web python manage.py shell <<'PY'
from networks.models import Network
print(Network.objects.get(code="nfkb_axis").pipeline_status)
PY
```

Expected: `stale`.

- [ ] **Step 8: Tear down**

```bash
docker-compose down
```

(Volumes preserved.)

---

## Task 19: Final push and Phase 3 close-out

- [ ] **Step 1: Run the full local suite**

```bash
poetry run ruff check .
poetry run ruff format --check .
poetry run mypy apps interactome
poetry run pytest apps -v
```

All four must return exit code 0. Expected pytest summary line: `X passed` where X is the total across all phases (Phase 0 + 1 + 2 + 3 tests).

- [ ] **Step 2: Push**

```bash
git push origin main
```

- [ ] **Step 3: Verify GitHub Actions is green**

Open the repository's Actions tab; the latest run must complete green within ~5 minutes.

- [ ] **Step 4: Tag the Phase 3 release**

```bash
git tag -a phase-3-complete -m "Phase 3 (Graph integration) complete

Delivered:
- core.OntologyEntity + core.Identifier (ontology layer)
- Gilda-backed core.services.ground_mention with tiered strictness
- graph app: Entity, Edge, EdgeEvidence, Conflict, NetworkEdgeMembership
- Bayes belief scoring (paper + model + recency)
- Conflict detection: intra-paper, inter-paper, inter-model
- NetworkEdgeMembership auto-assignment + verified→stale demotion
- graph.integrate_pending Celery task on 10-min Beat schedule
- Dev UI: /graph/dev/networks/<code>/ with Cytoscape.js + JSON endpoint

NF-κB axis renders in the dev UI; conflict and stale-demotion verified.

Next: Phase 4 (SBML + CSV emission)."
git push origin phase-3-complete
```

- [ ] **Step 5: Phase 3 done.**

The Phase 3 deliverable is ready for Phase 4 to consume: every accepted
edge in every network has a belief score, full provenance, and either
clean status or an open conflict — exactly the input shape SBML-qual
emission needs.

---

## Phase 3 Self-Review

**Spec coverage check** (against `docs/superpowers/specs/2026-05-19-disc-interactome-app-design.md`):

- Section 3 (data model — graph layer):
  - `OntologyEntity` + `Identifier` (ontology layer): Task 2.
  - `Entity`, `Edge`, `EdgeEvidence`: Tasks 5–6.
  - `Conflict` with `resolution_status`: Task 6.
  - `NetworkEdgeMembership`: Task 7.
  - Tiered identifier strictness (ungrounded RawPPI never enters graph): Task 10, enforced and tested.
  - Provenance is a graph: `Edge` → `EdgeEvidence` → `RawPPI` → `ExtractionRun` → `Chunk` → `Section` → `Paper` chain preserved end-to-end.

- Section 4 (`normalize_and_integrate`):
  - All six bullets implemented (Tasks 10, 11, 12).
  - Batch-debounced via `integrate_pending` Beat task (Task 13).

- Section 6 (Celery topology):
  - `graph.integrate_pending` every 10 min added to Beat schedule (Task 13).
  - Routed to `q.io` per the spec's worker-rationale table.

- Section 7 (Network status state machine):
  - `verified → stale` on new edge implemented and tested (Task 12).
  - `idle → stale` on first edge arrival also implemented (broader than spec mandates but consistent with the diagram).

- Section 10 (Phase 3 deliverable):
  - "Gilda grounding, Entity/Edge models, Bayes belief scoring, conflict detection, NetworkEdgeMembership" — all delivered.
  - "First per-network graphs queryable, NF-κB axis viewable in dev UI" — Task 14 (dev UI) + Task 18 (manual verification).

**Placeholder scan:** No "TBD"/"TODO"/"implement later"/"figure out later" strings in any task. Every step has either complete code, a complete command, or a single concrete file action.

**Type consistency:** Symbol names match across the test, implementation, and admin layers:
- `OntologyEntity`, `Identifier` (declared in `core.models`, registered in `core.admin`, referenced by `graph.models.Entity.ontology_entity`).
- `Entity`, `Edge`, `EdgeEvidence`, `Conflict`, `NetworkEdgeMembership` (declared in `graph.models`, registered in `graph.admin`, referenced by `graph.services` and `graph.views`).
- `bayes_belief`, `recompute_edge_belief`, `normalize_and_integrate`, `detect_intra_paper_conflicts`, `detect_inter_paper_conflicts`, `detect_inter_model_conflicts`, `reassign_network_membership`, `ground_mention` — all referenced by exact name from tests and the integration task.

**Cross-phase consistency:** The plan reads `RawPPI.subject_text`, `RawPPI.object_text`, `RawPPI.relation`, `RawPPI.ungrounded`, `ExtractionRun.extractor_model`, `ExtractionRun.status`, `Chunk.section`, `Section.paper`, `Paper.pmid`, `Paper.pub_date`, `Network.root_entities` (JSONB list of `{scheme, value}`), `Network.pipeline_status`. If any of those names differ at execution time, fix the references at the call site — do not alter the upstream model definitions.

**Numerical sanity (Bayes function):**
- Prior 0.30, paper LR 2.3, model LR 1.6 give:
  - 0 papers, 0 models, recency 1.0 → 0.300 ✓
  - 1 paper, 1 model, recency 1.0 → ~0.55 (candidate band) ✓
  - 1 paper, 7 models, recency 1.0 → ~0.97 (≥ accepted threshold) ✓
  - 5 papers, 7 models, recency 1.0 → ~0.9999 (saturated) ✓
- Threshold split: rejected 0.10 < prior 0.30 < accepted 0.80 ✓

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-19-phase-3-graph-integration.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — Dispatch a fresh subagent per task,
review between tasks. Phase 3 is the riskiest phase per the roadmap
("normalisation edge cases") and benefits most from incremental, reviewed
commits.

**2. Inline Execution** — Execute tasks in this session using
`executing-plans`, batched with review checkpoints at Tasks 6, 12, and 18.

**Cross-phase dependencies that must be live before starting:**
- Phase 0: `core` app, `TimestampedModel`, Celery + Beat wiring, Authelia middleware.
- Phase 1: `corpus.Paper` with `pmid`, `pub_date`, `is_original`; `papers.Section`, `papers.Chunk`; `networks.Network` with `code`, `root_entities` (JSONB), `pipeline_status`.
- Phase 2: `extract.ExtractionRun` (with `status`, `extractor_model`, `prompt_version`, FK to `Chunk`); `extract.RawPPI` (with `subject_text`, `object_text`, `relation`, `evidence_span_start/end`, `confidence`, `ungrounded` bool, FK to `ExtractionRun`).

**Which approach?**
