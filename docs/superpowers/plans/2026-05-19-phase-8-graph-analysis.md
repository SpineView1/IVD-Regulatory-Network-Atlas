# Phase 8: Graph Analysis & Crosstalk — Implementation Plan

> **⚠ CROSS-PLAN CONTRACT OVERRIDE:** Before implementing, read
> `2026-05-19-cross-plan-reconciliation.md`. It is authoritative where this
> plan's cross-phase references disagree. For this phase specifically, the
> `analysis` app is a *pure consumer* of Phase 3's `graph` models, so it must
> use the canonical names: `Edge.relation` (NOT `relation_type`),
> `Edge.belief_score`, `Edge.status` (choices `candidate`/`accepted`/
> `conflicted`/`rejected`), and the now-persisted denormalized counters
> `Edge.n_supporting_papers` / `Edge.n_models_agreeing` (reconciliation §4/§8).
> For nodes, read entities through the Phase 3 proxy properties
> `Entity.symbol`, `Entity.compartment`, `Entity.canonical_uri`,
> `Entity.miriam_uris` (reconciliation §5/§8) plus `Entity.ontology_entity.entity_type`.
> Network slices come from `graph.NetworkEdgeMembership` (`network`, `edge`,
> `relevance`) and `networks.Network` (`code`, `category`, `title`). The
> `EdgeEvidence` reverse name is `edge.evidence` (reconciliation §10). **This
> plan defines NO new Postgres models and MUST NOT alter any upstream model —
> if a referenced attribute differs at execution time, fix it at the call site
> in `analysis`, never in `graph`/`core`.**

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up Neo4j as a *derived, rebuildable* read-model of the accepted-`Edge` graph and ship the `analysis` app on top of it: incremental Postgres→Neo4j projection (signal-triggered on integration) plus a nightly reconciliation/rebuild sweep, an interactive cross-network crosstalk explorer (HTMX + Cytoscape.js), and a network-analysis module (k-hop neighborhood, crosstalk edges, shortest/all-simple paths, GDS centrality, GDS Louvain communities, feedback-loop / double-negative motif detection). End state: a biologist navigates to `/analysis/`, picks gene X → sees everything N hops away across the whole atlas colored by network membership; picks two networks → sees only the crosstalk edges bridging them; runs centrality/communities/feedback-loops over the current view; and if Neo4j is wiped, `analysis.tasks.reconcile_neo4j()` rebuilds it from Postgres with zero loss.

**Architecture:** One new app, `analysis`, which owns the Neo4j read-model and *only reads* Postgres via the `graph` models. **Postgres remains the system of record; Neo4j is derived and rebuildable** (spec §1 Neo4j invariant). The dependency direction is strictly `analysis → graph`; `graph` must NOT import `analysis` (that would be circular). Projection is therefore triggered the other way round: Phase 3's `graph.normalize_and_integrate` emits a Django signal `graph.signals.edges_integrated` after a batch lands; `analysis` connects a receiver that enqueues `analysis.tasks.project_edges(edge_ids)`. (The receiver dispatches the Celery task by *name* — `celery.current_app.send_task("analysis.tasks.project_edges", ...)` — so even the signal hop carries no static import of `analysis` into `graph`.) All Neo4j access goes through a `GraphBackend` interface (`analysis/backends/base.py`) with a real `Neo4jBackend` and an in-memory `FakeGraphBackend` (networkx-backed), so the Cypher-building and service logic are unit-testable without a live database; a small `@pytest.mark.neo4j` integration suite (skipped when `NEO4J_URI` is unset) exercises the real driver + a real GDS centrality call.

**Tech Stack:** Python 3.12, Django 5.0, Celery 5.3, PostgreSQL 16 (system of record), **Neo4j 5 Community** with the **Graph Data Science (GDS)** and **APOC** plugins (new service), the **`neo4j` Python driver 5.x** (new dependency), **networkx 3.x** (new dev/test dependency, backs `FakeGraphBackend`), HTMX 1.9 + Cytoscape.js 3.30 served from CDN (consistent with Phase 3/5 UI conventions), pytest 8 + pytest-django 4.8, ruff 0.6, mypy 1.10.

**Reference spec:** `docs/superpowers/specs/2026-05-19-disc-interactome-app-design.md` Sections 1 (Neo4j-is-a-derived-read-model invariant), 2 (`analysis` app row in the app table), 9 (`neo4j` service in docker-compose), 10 (roadmap row 8 — "Graph analysis & crosstalk"; dep: Phase 3 + Phase 5).

**Cross-phase dependencies (must already be in place):**
- Phase 0: `core` app, `TimestampedModel`, settings package, Celery wiring (`interactome/celery.py`, `autodiscover_tasks`), `AutheliaRemoteUserMiddleware`, `docker-compose.yml`, `.env.example`.
- Phase 3: `graph.Entity`, `graph.Edge`, `graph.EdgeEvidence`, `graph.NetworkEdgeMembership`; `core.OntologyEntity`/`Identifier`; the `graph.normalize_and_integrate` integration task with its `_post_integrate_hook` extension point; `networks.Network` with `code`/`category`/`title`/`root_entities`.
- Phase 5: the HTMX + Cytoscape.js + CDN UI conventions and the authenticated-page shell (this plan reuses those conventions but does not import Phase 5 modules).

This plan adds exactly ONE line of new behaviour to a Phase 3 file (emitting the `edges_integrated` signal inside `_post_integrate_hook`). Everything else is new code under `apps/analysis/`, plus additive entries in `docker-compose.yml`, `.env.example`, `pyproject.toml`, and `interactome/settings/base.py`.

---

## File Structure After Phase 8

```
/                                       (git repo root, unchanged outside the listed paths)
├── pyproject.toml                      ADD: neo4j driver; networkx (dev)
├── docker-compose.yml                  ADD: neo4j service + neo4jdata volume (already sketched in spec §9)
├── .env.example                        ADD: NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
├── apps/
│   ├── graph/
│   │   ├── signals.py                  NEW: edges_integrated Django signal
│   │   └── services.py                 MODIFY: _post_integrate_hook emits edges_integrated
│   └── analysis/                       NEW APP
│       ├── __init__.py
│       ├── apps.py                     AnalysisConfig (connects the signal receiver in ready())
│       ├── signals.py                  receiver: on edges_integrated → send_task(project_edges)
│       ├── services.py                 public API: neighborhood / crosstalk_edges / shortest_paths /
│       │                               all_simple_paths / centrality / communities / feedback_loops
│       ├── projection.py               Postgres→backend projection mapping (node/rel builders, diff)
│       ├── tasks.py                    project_edges, reconcile_neo4j Celery tasks
│       ├── backends/
│       │   ├── __init__.py             get_backend() factory (reads settings)
│       │   ├── base.py                 GraphBackend abstract interface
│       │   ├── neo4j_backend.py        Neo4jBackend (real driver + GDS/APOC Cypher)
│       │   └── fake.py                 FakeGraphBackend (in-memory, networkx-backed)
│       ├── views.py                    explorer page + JSON/HTMX-partial endpoints
│       ├── urls.py                     /analysis/ routes
│       ├── templates/analysis/
│       │   ├── explorer.html           full page: query box + Cytoscape canvas + analysis panel
│       │   └── _analysis_panel.html    HTMX partial: centrality / communities / feedback loops
│       ├── migrations/
│       │   └── __init__.py             (no Postgres models — empty package for app discovery)
│       └── tests/
│           ├── __init__.py
│           ├── conftest.py             fixtures: fake_backend, projected_atlas, neo4j_backend
│           ├── test_projection.py      node/rel builders + incremental diff (FakeGraphBackend)
│           ├── test_tasks.py           project_edges idempotency, reconcile add/remove (Fake)
│           ├── test_signal_wiring.py   edges_integrated → project_edges enqueue (mocked send_task)
│           ├── test_services.py        neighborhood/crosstalk/paths/centrality/communities/loops (Fake)
│           ├── test_views.py           explorer renders; JSON endpoints shape; HTMX partial
│           └── test_neo4j_integration.py   @pytest.mark.neo4j live projection + GDS call
└── interactome/
    └── settings/
        ├── base.py                     ADD: "analysis" app, NEO4J_* settings, ANALYSIS_GRAPH_BACKEND,
        │                               Beat schedule entry analysis.reconcile_neo4j
        └── (dev/production unchanged)
```

**Why this layout:**
- `analysis` owns the Neo4j read-model end-to-end. It has no Postgres models, so its `migrations/` package only exists for app discovery (an empty `__init__.py`). This matches the spec's app table entry: "(no Postgres models — owns the Neo4j read-model)".
- The `GraphBackend` interface is the seam that makes the whole app testable. `services.py` and `projection.py` never touch the `neo4j` driver directly — they call backend methods. Unit tests inject `FakeGraphBackend`; one integration suite injects `Neo4jBackend`. This mirrors the spec's "(most unit tests run with a fake in-memory backend; a handful of integration tests run against a live Neo4j service)".
- The `edges_integrated` signal lives in `graph` (the *emitter* owns the signal definition), and the *receiver* lives in `analysis`. This keeps the import arrow pointing `analysis → graph`: `analysis/signals.py` imports `graph.signals.edges_integrated`, never the reverse.
- `projection.py` (pure mapping/diff logic over plain dicts) is separated from `tasks.py` (Celery orchestration) and `backends/` (I/O), so each layer is independently testable.

---

## Neo4j read-model schema (the projection target)

This is the contract `projection.py` and every service in `services.py` build against. It is *derived* from Postgres; Postgres is authoritative.

**Nodes**

```
(:Entity {
    pg_id:         <int>     // graph.Entity.id — the MERGE key, unique
    ontology_id:   <int>     // core.OntologyEntity.id
    symbol:        <string>  // Entity.symbol  (== ontology_entity.preferred_label)
    entity_type:   <string>  // ontology_entity.entity_type (gene/protein/miRNA/metabolite/complex)
    compartment:   <string>  // Entity.compartment
    canonical_uri: <string>  // Entity.canonical_uri
})

(:Network {
    code:     <string>   // networks.Network.code — the MERGE key, unique
    title:    <string>   // networks.Network.title
    category: <string>   // networks.Network.category
})
```

**Relationships**

```
(:Entity)-[:REGULATES {
    edge_id:             <int>          // graph.Edge.id — the MERGE key, unique
    relation:            <string>       // Edge.relation  (canonical: NOT relation_type)
    belief_score:        <float>        // Edge.belief_score
    n_supporting_papers: <int>          // Edge.n_supporting_papers (now persisted, §8)
    n_models_agreeing:   <int>          // Edge.n_models_agreeing  (now persisted, §8)
    status:              <string>       // Edge.status (always 'accepted' for projected rels)
    networks:            <list<string>> // network codes this edge belongs to (cheap crosstalk)
}]->(:Entity)

(:Entity)-[:IN_NETWORK]->(:Network)    // entity is in a network if ANY of its edges are members
```

**Projection rule:** only `Edge.status == "accepted"` edges become `:REGULATES`
relationships. An `:Entity` node exists iff it is an endpoint of at least one
projected edge. An `:Entity)-[:IN_NETWORK]->(:Network)` edge exists iff the
entity is an endpoint of an accepted edge that has a `NetworkEdgeMembership` in
that network. The `networks` array property on each `:REGULATES` rel is the set
of `Network.code`s for that edge's memberships — this lets crosstalk queries
avoid a join-style traversal.

**Idempotency / uniqueness constraints (created once on first projection):**

```cypher
CREATE CONSTRAINT entity_pg_id  IF NOT EXISTS FOR (e:Entity)  REQUIRE e.pg_id IS UNIQUE;
CREATE CONSTRAINT network_code  IF NOT EXISTS FOR (n:Network) REQUIRE n.code  IS UNIQUE;
CREATE CONSTRAINT regulates_id  IF NOT EXISTS FOR ()-[r:REGULATES]-() REQUIRE r.edge_id IS UNIQUE;
```

---

## Task 1: Add Neo4j infrastructure (compose service, env, driver dependency)

The spec §9 already sketches the `neo4j` service. This task makes it concrete
and adds the env/driver wiring. No tests run here — verification is
`docker-compose config` parsing cleanly and the driver importing.

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Modify: `pyproject.toml`

- [ ] **Step 1: Add the `neo4j` service and volume to `docker-compose.yml`**

Add this service alongside the existing services (it matches the spec §9
sketch, with the volume and an env-driven `NEO4J_AUTH`):

```yaml
  neo4j:                # derived read-model for crosstalk + GDS analysis (Phase 8)
    image: neo4j:5-community
    environment:
      NEO4J_AUTH: neo4j/${NEO4J_PASSWORD}
      NEO4J_PLUGINS: '["graph-data-science","apoc"]'
      NEO4J_dbms_security_procedures_unrestricted: 'gds.*,apoc.*'
      NEO4J_dbms_security_procedures_allowlist: 'gds.*,apoc.*'
    ports:
      - "7474:7474"   # browser (behind Caddy/Authelia in production)
      - "7687:7687"   # bolt
    volumes:
      - neo4jdata:/data
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://localhost:7474 >/dev/null || exit 1"]
      interval: 15s
      timeout: 5s
      retries: 10
```

Add `neo4jdata` to the top-level `volumes:` block:

```yaml
volumes:
  pgdata: {}
  redisdata: {}
  miniodata: {}
  neo4jdata: {}
```

Add `neo4j` to the `depends_on:` of the `web`, `beat`, and `worker_io`
services (the projection/reconcile tasks run on `worker_io`):

```yaml
    depends_on:
      neo4j:
        condition: service_healthy
```

(Merge into the existing `depends_on` lists rather than replacing them.)

- [ ] **Step 2: Add Neo4j env vars to `.env.example`**

Append:

```
# --- Neo4j (Phase 8 — derived read-model for crosstalk + GDS analysis) ---
# Postgres remains the system of record; Neo4j is rebuildable from it.
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=changeme-neo4j
```

(Single password var: compose's `NEO4J_AUTH: neo4j/${NEO4J_PASSWORD}` and the
Django driver both read `NEO4J_PASSWORD`, so they cannot drift. They must be
the same value because the driver authenticates to the very Neo4j that compose
provisions.)

- [ ] **Step 3: Add the `neo4j` driver to `pyproject.toml`**

Under `[tool.poetry.dependencies]`:

```toml
neo4j = "^5.24"
```

Under `[tool.poetry.group.dev.dependencies]` (backs `FakeGraphBackend` and
the in-memory GDS-equivalent algorithms in tests):

```toml
networkx = "^3.3"
```

- [ ] **Step 4: Install and verify the driver imports**

```bash
poetry lock --no-update && poetry install
poetry run python -c "import neo4j, networkx; print(neo4j.__version__)"
```

Expected (version may differ):
```
5.24.0
```

- [ ] **Step 5: Verify the compose file still parses**

```bash
docker compose config >/dev/null && echo "compose OK"
```

Expected:
```
compose OK
```

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml .env.example pyproject.toml poetry.lock
git commit -m "build(analysis): add neo4j service, env vars, and neo4j driver dependency"
```

---

## Task 2: Scaffold the `analysis` app

**Files:**
- Create: `apps/analysis/__init__.py`
- Create: `apps/analysis/apps.py`
- Create: `apps/analysis/migrations/__init__.py`
- Create: `apps/analysis/tests/__init__.py`
- Modify: `interactome/settings/base.py`

- [ ] **Step 1: Create `apps/analysis/__init__.py`**

```python
"""analysis — Neo4j-backed crosstalk explorer and network-analysis app.

Owns the derived Neo4j read-model of the accepted-Edge graph. Reads
Postgres (graph.Edge / Entity / NetworkEdgeMembership) only; never the
system of record's writer. See docs/superpowers/specs §1 Neo4j invariant.
"""
```

- [ ] **Step 2: Create `apps/analysis/apps.py`**

```python
"""AnalysisConfig — wires the edges_integrated signal receiver on startup."""
from __future__ import annotations

from django.apps import AppConfig


class AnalysisConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "analysis"
    verbose_name = "Graph analysis & crosstalk"

    def ready(self) -> None:
        # Importing the module connects the @receiver. Safe at import time:
        # it imports graph.signals (allowed direction analysis -> graph).
        from analysis import signals  # noqa: F401
```

- [ ] **Step 3: Create empty package markers**

`apps/analysis/migrations/__init__.py`:
```python
```

`apps/analysis/tests/__init__.py`:
```python
```

- [ ] **Step 4: Register the app, Neo4j settings, and backend selector in `interactome/settings/base.py`**

Add `"analysis"` to `INSTALLED_APPS` (after `"graph"`):

```python
INSTALLED_APPS = [
    # ... existing entries ...
    "graph",
    "analysis",
]
```

Add a Neo4j / backend configuration block (after the Celery config):

```python
# --- Neo4j read-model (Phase 8) ---------------------------------------------
# Postgres is the system of record; Neo4j is derived and rebuildable.
NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "")

# Which GraphBackend the analysis app uses. "neo4j" in real deployments;
# tests override to "fake" via the settings fixture.
ANALYSIS_GRAPH_BACKEND = os.environ.get("ANALYSIS_GRAPH_BACKEND", "neo4j")
```

- [ ] **Step 5: Confirm the app is discovered**

```bash
poetry run python manage.py check
```

Expected:
```
System check identified no issues (0 silenced).
```

- [ ] **Step 6: Commit**

```bash
git add apps/analysis/__init__.py apps/analysis/apps.py apps/analysis/migrations/__init__.py apps/analysis/tests/__init__.py interactome/settings/base.py
git commit -m "feat(analysis): scaffold app with Neo4j settings and backend selector"
```

---

## Task 3: `GraphBackend` interface + `FakeGraphBackend` (TDD)

The interface is the testability seam. The fake is an in-memory implementation
that every unit test runs against. We write the fake's tests first so the
interface contract is pinned by executable expectations.

**Files:**
- Create: `apps/analysis/backends/__init__.py`
- Create: `apps/analysis/backends/base.py`
- Create: `apps/analysis/backends/fake.py`
- Create: `apps/analysis/tests/conftest.py`
- Create: `apps/analysis/tests/test_projection.py` (backend portion first)

- [ ] **Step 1: Write the failing backend-contract tests in `apps/analysis/tests/test_projection.py`**

```python
"""Tests for the GraphBackend contract via FakeGraphBackend, and projection mapping."""
from __future__ import annotations

import pytest

from analysis.backends.fake import FakeGraphBackend


@pytest.fixture
def backend() -> FakeGraphBackend:
    return FakeGraphBackend()


def test_upsert_entity_then_get(backend):
    backend.upsert_entity({"pg_id": 1, "symbol": "IL1B", "entity_type": "protein",
                           "compartment": "extracellular", "canonical_uri": "u", "ontology_id": 11})
    node = backend.get_entity(1)
    assert node["symbol"] == "IL1B"


def test_upsert_entity_is_idempotent(backend):
    for _ in range(2):
        backend.upsert_entity({"pg_id": 1, "symbol": "IL1B", "entity_type": "protein",
                               "compartment": "x", "canonical_uri": "u", "ontology_id": 11})
    assert backend.count_entities() == 1


def test_upsert_edge_creates_relationship(backend):
    backend.upsert_entity({"pg_id": 1, "symbol": "IL1B", "entity_type": "protein",
                           "compartment": "x", "canonical_uri": "u", "ontology_id": 11})
    backend.upsert_entity({"pg_id": 2, "symbol": "NFKB1", "entity_type": "protein",
                           "compartment": "n", "canonical_uri": "u2", "ontology_id": 12})
    backend.upsert_edge(source_pg_id=1, target_pg_id=2, props={
        "edge_id": 100, "relation": "activates", "belief_score": 0.9,
        "n_supporting_papers": 3, "n_models_agreeing": 5, "status": "accepted",
        "networks": ["nfkb_axis"],
    })
    assert backend.count_edges() == 1


def test_upsert_edge_is_idempotent_on_edge_id(backend):
    backend.upsert_entity({"pg_id": 1, "symbol": "A", "entity_type": "p", "compartment": "c",
                           "canonical_uri": "u", "ontology_id": 1})
    backend.upsert_entity({"pg_id": 2, "symbol": "B", "entity_type": "p", "compartment": "c",
                           "canonical_uri": "u", "ontology_id": 2})
    props = {"edge_id": 100, "relation": "activates", "belief_score": 0.5,
             "n_supporting_papers": 1, "n_models_agreeing": 1, "status": "accepted",
             "networks": []}
    backend.upsert_edge(source_pg_id=1, target_pg_id=2, props=props)
    props["belief_score"] = 0.95
    backend.upsert_edge(source_pg_id=1, target_pg_id=2, props=props)
    assert backend.count_edges() == 1
    assert backend.get_edge(100)["belief_score"] == 0.95  # updated in place


def test_delete_edge_removes_relationship(backend):
    backend.upsert_entity({"pg_id": 1, "symbol": "A", "entity_type": "p", "compartment": "c",
                           "canonical_uri": "u", "ontology_id": 1})
    backend.upsert_entity({"pg_id": 2, "symbol": "B", "entity_type": "p", "compartment": "c",
                           "canonical_uri": "u", "ontology_id": 2})
    backend.upsert_edge(source_pg_id=1, target_pg_id=2, props={
        "edge_id": 100, "relation": "activates", "belief_score": 0.5,
        "n_supporting_papers": 1, "n_models_agreeing": 1, "status": "accepted", "networks": []})
    backend.delete_edge(100)
    assert backend.count_edges() == 0


def test_all_edge_ids_returns_projected_set(backend):
    backend.upsert_entity({"pg_id": 1, "symbol": "A", "entity_type": "p", "compartment": "c",
                           "canonical_uri": "u", "ontology_id": 1})
    backend.upsert_entity({"pg_id": 2, "symbol": "B", "entity_type": "p", "compartment": "c",
                           "canonical_uri": "u", "ontology_id": 2})
    backend.upsert_edge(source_pg_id=1, target_pg_id=2, props={
        "edge_id": 100, "relation": "activates", "belief_score": 0.5,
        "n_supporting_papers": 1, "n_models_agreeing": 1, "status": "accepted", "networks": []})
    assert backend.all_edge_ids() == {100}
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
poetry run pytest apps/analysis/tests/test_projection.py -v
```

Expected:
```
ModuleNotFoundError: No module named 'analysis.backends'
```

- [ ] **Step 3: Create `apps/analysis/backends/__init__.py`**

```python
"""Graph backends. The factory hides which implementation is active."""
from __future__ import annotations

from django.conf import settings

from analysis.backends.base import GraphBackend


def get_backend() -> GraphBackend:
    """Return the configured GraphBackend instance.

    Selected by settings.ANALYSIS_GRAPH_BACKEND ("neo4j" | "fake").
    Tests flip this to "fake" via the settings fixture; production uses
    "neo4j". Importing the neo4j backend is deferred so the fake path has
    no hard dependency on a running database.
    """
    backend = getattr(settings, "ANALYSIS_GRAPH_BACKEND", "neo4j")
    if backend == "fake":
        from analysis.backends.fake import FakeGraphBackend

        return FakeGraphBackend()
    from analysis.backends.neo4j_backend import Neo4jBackend

    return Neo4jBackend(
        uri=settings.NEO4J_URI,
        user=settings.NEO4J_USER,
        password=settings.NEO4J_PASSWORD,
    )
```

- [ ] **Step 4: Create the interface in `apps/analysis/backends/base.py`**

```python
"""GraphBackend — the abstract seam between analysis logic and Neo4j.

Every projection and query in the analysis app goes through this interface,
so unit tests can swap in FakeGraphBackend and never need a live database.
All methods take/return plain Python dicts and lists (JSON-serializable),
never neo4j driver objects.
"""
from __future__ import annotations

import abc


class GraphBackend(abc.ABC):
    # --- schema / lifecycle -------------------------------------------------
    @abc.abstractmethod
    def ensure_constraints(self) -> None:
        """Create node/relationship uniqueness constraints (idempotent)."""

    @abc.abstractmethod
    def clear_all(self) -> None:
        """Wipe the entire read-model. Used by the rebuild-from-scratch path."""

    # --- node / relationship upserts ---------------------------------------
    @abc.abstractmethod
    def upsert_entity(self, props: dict) -> None:
        """MERGE an (:Entity {pg_id}) and set its properties."""

    @abc.abstractmethod
    def upsert_network(self, props: dict) -> None:
        """MERGE a (:Network {code}) and set its properties."""

    @abc.abstractmethod
    def upsert_edge(self, *, source_pg_id: int, target_pg_id: int, props: dict) -> None:
        """MERGE a (:Entity)-[:REGULATES {edge_id}]->(:Entity) and set properties."""

    @abc.abstractmethod
    def link_in_network(self, *, entity_pg_id: int, network_code: str) -> None:
        """MERGE (:Entity)-[:IN_NETWORK]->(:Network)."""

    @abc.abstractmethod
    def delete_edge(self, edge_id: int) -> None:
        """DELETE the :REGULATES relationship with this edge_id (idempotent)."""

    @abc.abstractmethod
    def prune_orphan_entities(self) -> int:
        """Delete :Entity nodes with no :REGULATES relationships. Returns count."""

    # --- read helpers used by reconcile + tests ----------------------------
    @abc.abstractmethod
    def all_edge_ids(self) -> set[int]:
        """Set of edge_id values currently projected as :REGULATES rels."""

    @abc.abstractmethod
    def count_entities(self) -> int: ...

    @abc.abstractmethod
    def count_edges(self) -> int: ...

    @abc.abstractmethod
    def get_entity(self, pg_id: int) -> dict | None: ...

    @abc.abstractmethod
    def get_edge(self, edge_id: int) -> dict | None: ...

    # --- query surface used by services.py ----------------------------------
    @abc.abstractmethod
    def neighborhood(self, *, entity_pg_id: int, k: int) -> dict:
        """k-hop neighborhood. Returns {"nodes": [...], "edges": [...]}."""

    @abc.abstractmethod
    def crosstalk_edges(self, *, network_a: str, network_b: str) -> dict:
        """Edges bridging two networks. Returns {"nodes": [...], "edges": [...]}."""

    @abc.abstractmethod
    def shortest_paths(self, *, source_pg_id: int, target_pg_id: int, max_len: int) -> list[dict]:
        """Shortest path(s). Returns a list of {"nodes": [...], "edges": [...]}."""

    @abc.abstractmethod
    def all_simple_paths(self, *, source_pg_id: int, target_pg_id: int, max_len: int) -> list[dict]:
        """All simple paths up to max_len. Returns a list of path dicts."""

    @abc.abstractmethod
    def centrality(self, *, network: str | None, measure: str) -> list[dict]:
        """GDS centrality ranking. Returns [{"pg_id", "symbol", "score"}, ...]."""

    @abc.abstractmethod
    def communities(self, *, network: str | None) -> list[dict]:
        """GDS Louvain communities. Returns [{"pg_id", "symbol", "community"}, ...]."""

    @abc.abstractmethod
    def feedback_loops(self, *, max_len: int, network: str | None) -> list[dict]:
        """Directed cycles. Returns [{"nodes": [...], "edges": [...], "double_negative": bool}]."""
```

- [ ] **Step 5: Implement `FakeGraphBackend` in `apps/analysis/backends/fake.py`**

```python
"""In-memory GraphBackend backed by networkx — for unit tests.

Stores the same node/relationship shapes the Neo4jBackend produces, so
service logic and projection diffing are exercised identically. GDS calls
are emulated with networkx algorithms (PageRank, betweenness, degree,
greedy-modularity communities, simple_cycles) so the *shape* of the result
matches what the real backend returns.
"""
from __future__ import annotations

import networkx as nx

from analysis.backends.base import GraphBackend

# Relations whose semantics are inhibitory — used for double-negative motif tagging.
INHIBITORY = {"inhibits", "represses", "dephosphorylates", "deubiquitinates",
              "deacetylates", "demethylates"}


class FakeGraphBackend(GraphBackend):
    def __init__(self) -> None:
        self._g = nx.MultiDiGraph()          # entity nodes + REGULATES edges
        self._networks: dict[str, dict] = {}  # code -> props
        self._in_network: set[tuple[int, str]] = set()
        self._edge_by_id: dict[int, tuple[int, int]] = {}  # edge_id -> (src, tgt)

    # --- lifecycle ---
    def ensure_constraints(self) -> None:
        return None

    def clear_all(self) -> None:
        self._g.clear()
        self._networks.clear()
        self._in_network.clear()
        self._edge_by_id.clear()

    # --- upserts ---
    def upsert_entity(self, props: dict) -> None:
        self._g.add_node(props["pg_id"], **props)

    def upsert_network(self, props: dict) -> None:
        self._networks[props["code"]] = dict(props)

    def upsert_edge(self, *, source_pg_id: int, target_pg_id: int, props: dict) -> None:
        eid = props["edge_id"]
        if eid in self._edge_by_id:  # idempotent update-in-place
            self.delete_edge(eid)
        self._g.add_edge(source_pg_id, target_pg_id, key=eid, **props)
        self._edge_by_id[eid] = (source_pg_id, target_pg_id)

    def link_in_network(self, *, entity_pg_id: int, network_code: str) -> None:
        self._in_network.add((entity_pg_id, network_code))

    def delete_edge(self, edge_id: int) -> None:
        pair = self._edge_by_id.pop(edge_id, None)
        if pair is not None and self._g.has_edge(pair[0], pair[1], key=edge_id):
            self._g.remove_edge(pair[0], pair[1], key=edge_id)

    def prune_orphan_entities(self) -> int:
        orphans = [n for n in self._g.nodes if self._g.degree(n) == 0]
        self._g.remove_nodes_from(orphans)
        self._in_network = {(e, c) for (e, c) in self._in_network if e not in orphans}
        return len(orphans)

    # --- reads ---
    def all_edge_ids(self) -> set[int]:
        return set(self._edge_by_id)

    def count_entities(self) -> int:
        return self._g.number_of_nodes()

    def count_edges(self) -> int:
        return self._g.number_of_edges()

    def get_entity(self, pg_id: int) -> dict | None:
        return dict(self._g.nodes[pg_id]) if pg_id in self._g else None

    def get_edge(self, edge_id: int) -> dict | None:
        pair = self._edge_by_id.get(edge_id)
        if pair is None:
            return None
        return dict(self._g.edges[pair[0], pair[1], edge_id])

    # --- subgraph serialization helper ---
    def _serialize(self, node_ids: set[int], edge_ids: set[int]) -> dict:
        nodes = [self._node_payload(n) for n in node_ids if n in self._g]
        edges = []
        for eid in edge_ids:
            pair = self._edge_by_id.get(eid)
            if pair is None:
                continue
            edges.append(self._edge_payload(eid, pair))
        return {"nodes": nodes, "edges": edges}

    def _node_payload(self, n: int) -> dict:
        d = self._g.nodes[n]
        networks = sorted(c for (e, c) in self._in_network if e == n)
        return {"data": {"id": str(n), "pg_id": n, "label": d.get("symbol", str(n)),
                         "entity_type": d.get("entity_type", ""),
                         "compartment": d.get("compartment", ""),
                         "networks": networks}}

    def _edge_payload(self, eid: int, pair: tuple[int, int]) -> dict:
        d = self._g.edges[pair[0], pair[1], eid]
        return {"data": {"id": f"e{eid}", "edge_id": eid, "source": str(pair[0]),
                         "target": str(pair[1]), "relation": d.get("relation"),
                         "belief": d.get("belief_score"), "status": d.get("status"),
                         "n_supporting_papers": d.get("n_supporting_papers"),
                         "n_models_agreeing": d.get("n_models_agreeing"),
                         "networks": d.get("networks", [])}}

    # --- query surface ---
    def neighborhood(self, *, entity_pg_id: int, k: int) -> dict:
        if entity_pg_id not in self._g:
            return {"nodes": [], "edges": []}
        und = self._g.to_undirected(as_view=True)
        reach = nx.single_source_shortest_path_length(und, entity_pg_id, cutoff=k)
        node_ids = set(reach)
        edge_ids = {eid for eid, (s, t) in self._edge_by_id.items()
                    if s in node_ids and t in node_ids}
        return self._serialize(node_ids, edge_ids)

    def crosstalk_edges(self, *, network_a: str, network_b: str) -> dict:
        in_a = {e for (e, c) in self._in_network if c == network_a}
        in_b = {e for (e, c) in self._in_network if c == network_b}
        edge_ids = set()
        for eid, (s, t) in self._edge_by_id.items():
            nets = set(self._g.edges[s, t, eid].get("networks", []))
            bridges = (s in in_a and t in in_b) or (s in in_b and t in in_a) \
                or ({network_a, network_b} <= nets)
            if bridges:
                edge_ids.add(eid)
        node_ids = set()
        for eid in edge_ids:
            s, t = self._edge_by_id[eid]
            node_ids.update({s, t})
        return self._serialize(node_ids, edge_ids)

    def shortest_paths(self, *, source_pg_id: int, target_pg_id: int, max_len: int) -> list[dict]:
        try:
            path = nx.shortest_path(self._g, source_pg_id, target_pg_id)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return []
        if len(path) - 1 > max_len:
            return []
        return [self._path_to_dict(path)]

    def all_simple_paths(self, *, source_pg_id: int, target_pg_id: int, max_len: int) -> list[dict]:
        if source_pg_id not in self._g or target_pg_id not in self._g:
            return []
        paths = nx.all_simple_paths(self._g, source_pg_id, target_pg_id, cutoff=max_len)
        return [self._path_to_dict(p) for p in paths]

    def _path_to_dict(self, path: list[int]) -> dict:
        node_ids = set(path)
        edge_ids = set()
        for s, t in zip(path, path[1:]):
            for eid, pair in self._edge_by_id.items():
                if pair == (s, t):
                    edge_ids.add(eid)
                    break
        return self._serialize(node_ids, edge_ids)

    def _scope_graph(self, network: str | None) -> nx.MultiDiGraph:
        if network is None:
            return self._g
        nodes = {e for (e, c) in self._in_network if c == network}
        return self._g.subgraph(nodes)

    def centrality(self, *, network: str | None, measure: str) -> list[dict]:
        g = self._scope_graph(network)
        if g.number_of_nodes() == 0:
            return []
        if measure == "pagerank":
            scores = nx.pagerank(nx.DiGraph(g))
        elif measure == "betweenness":
            scores = nx.betweenness_centrality(nx.DiGraph(g))
        elif measure == "degree":
            scores = dict(g.degree())
        else:
            raise ValueError(f"unknown centrality measure: {measure}")
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        return [{"pg_id": n, "symbol": self._g.nodes[n].get("symbol", str(n)),
                 "score": float(s)} for n, s in ranked]

    def communities(self, *, network: str | None) -> list[dict]:
        g = self._scope_graph(network)
        if g.number_of_nodes() == 0:
            return []
        comms = nx.community.greedy_modularity_communities(nx.Graph(g))
        out = []
        for idx, members in enumerate(comms):
            for n in members:
                out.append({"pg_id": n, "symbol": self._g.nodes[n].get("symbol", str(n)),
                            "community": idx})
        return out

    def feedback_loops(self, *, max_len: int, network: str | None) -> list[dict]:
        g = self._scope_graph(network)
        loops = []
        for cycle in nx.simple_cycles(nx.DiGraph(g)):
            if len(cycle) > max_len:
                continue
            ring = cycle + [cycle[0]]
            edge_ids, inhib_count = set(), 0
            for s, t in zip(ring, ring[1:]):
                for eid, pair in self._edge_by_id.items():
                    if pair == (s, t):
                        edge_ids.add(eid)
                        if self._g.edges[s, t, eid].get("relation") in INHIBITORY:
                            inhib_count += 1
                        break
            payload = self._serialize(set(cycle), edge_ids)
            payload["double_negative"] = (len(cycle) == 2 and inhib_count == 2)
            loops.append(payload)
        return loops
```

- [ ] **Step 6: Run the backend tests; confirm green**

```bash
poetry run pytest apps/analysis/tests/test_projection.py -v
```

Expected:
```
test_upsert_entity_then_get PASSED
test_upsert_entity_is_idempotent PASSED
test_upsert_edge_creates_relationship PASSED
test_upsert_edge_is_idempotent_on_edge_id PASSED
test_delete_edge_removes_relationship PASSED
test_all_edge_ids_returns_projected_set PASSED

6 passed
```

- [ ] **Step 7: Commit**

```bash
git add apps/analysis/backends/__init__.py apps/analysis/backends/base.py apps/analysis/backends/fake.py apps/analysis/tests/test_projection.py
git commit -m "feat(analysis): add GraphBackend interface and networkx-backed fake"
```

---

## Task 4: Projection mapping — Postgres rows → backend payloads (TDD)

Pure functions that read Postgres (via the `graph` models) and build the dicts
the backend understands. No backend I/O here — just the mapping. This keeps the
canonical-name plumbing (`Edge.relation`, `n_supporting_papers`, `Entity.symbol`,
etc.) in one tested place.

**Files:**
- Create: `apps/analysis/projection.py`
- Modify: `apps/analysis/tests/conftest.py`
- Modify: `apps/analysis/tests/test_projection.py`

- [ ] **Step 1: Create `apps/analysis/tests/conftest.py`**

```python
"""Shared fixtures for analysis tests."""
from __future__ import annotations

import os

import pytest

from analysis.backends.fake import FakeGraphBackend


@pytest.fixture
def fake_backend(settings) -> FakeGraphBackend:
    """Force the analysis app onto the in-memory backend for the test."""
    settings.ANALYSIS_GRAPH_BACKEND = "fake"
    return FakeGraphBackend()


@pytest.fixture
def accepted_edge(db):
    """An accepted IL1B->NFKB1 edge with a NetworkEdgeMembership in nfkb_axis.

    Builds the Phase 3 graph rows directly (no integration run) so the
    projection mapping can be exercised in isolation. Uses ONLY canonical
    field names (reconciliation §4/§5/§6).
    """
    from core.models import Identifier, OntologyEntity
    from graph.models import Edge, Entity, NetworkEdgeMembership
    from networks.models import Network

    def make_entity(label, etype, scheme, value, uri):
        oe = OntologyEntity.objects.create(
            entity_type=etype, preferred_label=label, canonical_uri=uri,
            compartment="cytoplasm",
        )
        Identifier.objects.create(entity=oe, scheme=scheme, value=value)
        return Entity.objects.create(ontology_entity=oe)

    src = make_entity("IL1B", "protein", "HGNC", "5992",
                      "https://identifiers.org/hgnc:5992")
    tgt = make_entity("NFKB1", "protein", "HGNC", "7794",
                      "https://identifiers.org/hgnc:7794")
    edge = Edge.objects.create(
        source=src, target=tgt, relation="activates", belief_score=0.91,
        n_supporting_papers=3, n_models_agreeing=5, status="accepted",
    )
    net = Network.objects.create(code="nfkb_axis", title="NF-κB axis", category="I",
                                 root_entities=[{"scheme": "HGNC", "value": "7794"}],
                                 pipeline_status="idle")
    NetworkEdgeMembership.objects.create(network=net, edge=edge, relevance=1.0)
    return edge


@pytest.fixture
def projected_atlas(db, accepted_edge, fake_backend):
    """A fake backend with `accepted_edge` already projected into it."""
    from analysis.projection import project_edge_ids
    project_edge_ids([accepted_edge.id], backend=fake_backend)
    return fake_backend


@pytest.fixture
def neo4j_backend():
    """Live Neo4jBackend for @pytest.mark.neo4j tests; skip if unconfigured."""
    if not os.environ.get("NEO4J_URI"):
        pytest.skip("NEO4J_URI not set — skipping live Neo4j integration test")
    from analysis.backends.neo4j_backend import Neo4jBackend

    backend = Neo4jBackend(
        uri=os.environ["NEO4J_URI"],
        user=os.environ.get("NEO4J_USER", "neo4j"),
        password=os.environ.get("NEO4J_PASSWORD", ""),
    )
    backend.ensure_constraints()
    backend.clear_all()
    yield backend
    backend.clear_all()
    backend.close()
```

- [ ] **Step 2: Append projection-mapping tests to `apps/analysis/tests/test_projection.py`**

```python
def test_build_entity_payload_uses_canonical_proxy_props(db, accepted_edge):
    from analysis.projection import build_entity_payload

    payload = build_entity_payload(accepted_edge.source)
    assert payload["pg_id"] == accepted_edge.source_id
    assert payload["symbol"] == "IL1B"            # Entity.symbol proxy (§5)
    assert payload["entity_type"] == "protein"
    assert payload["compartment"] == "cytoplasm"
    assert payload["canonical_uri"] == "https://identifiers.org/hgnc:5992"


def test_build_edge_payload_uses_canonical_edge_fields(db, accepted_edge):
    from analysis.projection import build_edge_payload

    props = build_edge_payload(accepted_edge)
    assert props["edge_id"] == accepted_edge.id
    assert props["relation"] == "activates"        # Edge.relation, NOT relation_type (§4)
    assert props["belief_score"] == pytest.approx(0.91)
    assert props["n_supporting_papers"] == 3       # now persisted (§8)
    assert props["n_models_agreeing"] == 5
    assert props["status"] == "accepted"
    assert props["networks"] == ["nfkb_axis"]      # from NetworkEdgeMembership


def test_project_edge_ids_writes_nodes_edges_and_membership(db, accepted_edge, fake_backend):
    from analysis.projection import project_edge_ids

    project_edge_ids([accepted_edge.id], backend=fake_backend)
    assert fake_backend.count_entities() == 2
    assert fake_backend.count_edges() == 1
    # both endpoints linked to the network
    cross = fake_backend.crosstalk_edges(network_a="nfkb_axis", network_b="nfkb_axis")
    assert len(cross["edges"]) == 1


def test_project_edge_ids_deletes_relationship_when_not_accepted(db, accepted_edge, fake_backend):
    from analysis.projection import project_edge_ids

    project_edge_ids([accepted_edge.id], backend=fake_backend)
    assert fake_backend.count_edges() == 1

    accepted_edge.status = "rejected"
    accepted_edge.save(update_fields=["status"])
    project_edge_ids([accepted_edge.id], backend=fake_backend)
    assert fake_backend.count_edges() == 0


def test_accepted_edge_ids_in_postgres(db, accepted_edge):
    from analysis.projection import accepted_edge_ids

    assert accepted_edge_ids() == {accepted_edge.id}
```

- [ ] **Step 3: Run; confirm failure**

```bash
poetry run pytest apps/analysis/tests/test_projection.py -k "payload or project_edge_ids or accepted_edge_ids" -v
```

Expected:
```
ModuleNotFoundError: No module named 'analysis.projection'
```

- [ ] **Step 4: Implement `apps/analysis/projection.py`**

```python
"""Postgres → backend projection mapping.

Pure-ish: reads the graph models, builds JSON-serializable payloads, and
drives a GraphBackend. Postgres is the system of record; this module never
writes graph truth — it only reflects accepted edges into the read-model.

Canonical field names (cross-plan reconciliation §4/§5/§6):
  Edge.relation, Edge.belief_score, Edge.status, Edge.n_supporting_papers,
  Edge.n_models_agreeing; Entity.symbol/compartment/canonical_uri proxies;
  Network.code/title/category; NetworkEdgeMembership.network/edge.
"""
from __future__ import annotations

from collections.abc import Iterable

from analysis.backends.base import GraphBackend


def accepted_edge_ids() -> set[int]:
    """Set of all Edge.id where status == 'accepted' in Postgres."""
    from graph.models import Edge

    return set(
        Edge.objects.filter(status="accepted").values_list("id", flat=True)
    )


def build_entity_payload(entity) -> dict:
    """Map a graph.Entity to the (:Entity) node props."""
    oe = entity.ontology_entity
    return {
        "pg_id": entity.id,
        "ontology_id": oe.id,
        "symbol": entity.symbol,            # proxy -> preferred_label (§5)
        "entity_type": oe.entity_type,
        "compartment": entity.compartment,  # proxy (§5)
        "canonical_uri": entity.canonical_uri,
    }


def _edge_network_codes(edge) -> list[str]:
    """Network codes this edge belongs to, sorted, via NetworkEdgeMembership."""
    return sorted(
        edge.network_memberships.values_list("network__code", flat=True)
    )


def build_edge_payload(edge) -> dict:
    """Map a graph.Edge to the [:REGULATES] relationship props."""
    return {
        "edge_id": edge.id,
        "relation": edge.relation,                       # NOT relation_type (§4)
        "belief_score": edge.belief_score,
        "n_supporting_papers": edge.n_supporting_papers,  # persisted (§8)
        "n_models_agreeing": edge.n_models_agreeing,      # persisted (§8)
        "status": edge.status,
        "networks": _edge_network_codes(edge),
    }


def build_network_payload(network) -> dict:
    return {"code": network.code, "title": network.title, "category": network.category}


def project_edge_ids(edge_ids: Iterable[int], *, backend: GraphBackend) -> dict:
    """Incrementally reflect the given edges into the backend.

    For each edge:
      * status == 'accepted'  → MERGE both endpoint entities, the REGULATES
        relationship, the Network nodes, and the IN_NETWORK links.
      * otherwise (rejected/conflicted/candidate) → DELETE its relationship.
    Idempotent: re-running with the same accepted edge updates props in place.
    """
    from graph.models import Edge

    edge_ids = list(edge_ids)
    edges = (
        Edge.objects.filter(id__in=edge_ids)
        .select_related("source__ontology_entity", "target__ontology_entity")
        .prefetch_related("network_memberships__network")
    )
    by_id = {e.id: e for e in edges}

    projected = 0
    removed = 0
    for eid in edge_ids:
        edge = by_id.get(eid)
        if edge is None or edge.status != "accepted":
            backend.delete_edge(eid)
            removed += 1
            continue

        src_payload = build_entity_payload(edge.source)
        tgt_payload = build_entity_payload(edge.target)
        backend.upsert_entity(src_payload)
        backend.upsert_entity(tgt_payload)
        backend.upsert_edge(
            source_pg_id=edge.source_id,
            target_pg_id=edge.target_id,
            props=build_edge_payload(edge),
        )
        for membership in edge.network_memberships.all():
            net = membership.network
            backend.upsert_network(build_network_payload(net))
            backend.link_in_network(entity_pg_id=edge.source_id, network_code=net.code)
            backend.link_in_network(entity_pg_id=edge.target_id, network_code=net.code)
        projected += 1

    return {"projected": projected, "removed": removed}
```

- [ ] **Step 5: Run; confirm green**

```bash
poetry run pytest apps/analysis/tests/test_projection.py -v
```

Expected: prior 6 backend tests still green + 5 mapping tests pass (`11 passed`).

- [ ] **Step 6: Commit**

```bash
git add apps/analysis/projection.py apps/analysis/tests/conftest.py apps/analysis/tests/test_projection.py
git commit -m "feat(analysis): add Postgres->backend projection mapping (canonical names)"
```

---

## Task 5: `Neo4jBackend` real implementation

The Cypher/GDS implementation of `GraphBackend`. It is *not* unit-tested in
isolation (that is the integration suite's job in Task 11); this task's
verification is that it imports and that its method set matches the interface.

**Files:**
- Create: `apps/analysis/backends/neo4j_backend.py`

- [ ] **Step 1: Implement `apps/analysis/backends/neo4j_backend.py`**

```python
"""Neo4jBackend — the production GraphBackend.

All graph truth lives in Postgres; this backend reflects accepted edges into
Neo4j and answers traversal/GDS queries. Uses parameterized Cypher and the
GDS library (gds.graph.project on an anonymous in-memory projection per call,
then drops it). Returns plain dicts/lists shaped exactly like FakeGraphBackend.
"""
from __future__ import annotations

import uuid

from neo4j import GraphDatabase

from analysis.backends.base import GraphBackend

INHIBITORY = {"inhibits", "represses", "dephosphorylates", "deubiquitinates",
              "deacetylates", "demethylates"}


class Neo4jBackend(GraphBackend):
    def __init__(self, *, uri: str, user: str, password: str) -> None:
        self._driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self) -> None:
        self._driver.close()

    def _run(self, cypher: str, **params):
        with self._driver.session() as session:
            return list(session.run(cypher, **params))

    # --- lifecycle ---
    def ensure_constraints(self) -> None:
        self._run("CREATE CONSTRAINT entity_pg_id IF NOT EXISTS "
                  "FOR (e:Entity) REQUIRE e.pg_id IS UNIQUE")
        self._run("CREATE CONSTRAINT network_code IF NOT EXISTS "
                  "FOR (n:Network) REQUIRE n.code IS UNIQUE")
        self._run("CREATE CONSTRAINT regulates_id IF NOT EXISTS "
                  "FOR ()-[r:REGULATES]-() REQUIRE r.edge_id IS UNIQUE")

    def clear_all(self) -> None:
        self._run("MATCH (n) DETACH DELETE n")

    # --- upserts ---
    def upsert_entity(self, props: dict) -> None:
        self._run(
            "MERGE (e:Entity {pg_id: $pg_id}) "
            "SET e.ontology_id=$ontology_id, e.symbol=$symbol, "
            "e.entity_type=$entity_type, e.compartment=$compartment, "
            "e.canonical_uri=$canonical_uri",
            **props,
        )

    def upsert_network(self, props: dict) -> None:
        self._run(
            "MERGE (n:Network {code: $code}) SET n.title=$title, n.category=$category",
            **props,
        )

    def upsert_edge(self, *, source_pg_id: int, target_pg_id: int, props: dict) -> None:
        self._run(
            "MATCH (s:Entity {pg_id:$source_pg_id}), (t:Entity {pg_id:$target_pg_id}) "
            "MERGE (s)-[r:REGULATES {edge_id:$edge_id}]->(t) "
            "SET r.relation=$relation, r.belief_score=$belief_score, "
            "r.n_supporting_papers=$n_supporting_papers, "
            "r.n_models_agreeing=$n_models_agreeing, r.status=$status, "
            "r.networks=$networks",
            source_pg_id=source_pg_id, target_pg_id=target_pg_id, **props,
        )

    def link_in_network(self, *, entity_pg_id: int, network_code: str) -> None:
        self._run(
            "MATCH (e:Entity {pg_id:$entity_pg_id}), (n:Network {code:$network_code}) "
            "MERGE (e)-[:IN_NETWORK]->(n)",
            entity_pg_id=entity_pg_id, network_code=network_code,
        )

    def delete_edge(self, edge_id: int) -> None:
        self._run("MATCH ()-[r:REGULATES {edge_id:$edge_id}]->() DELETE r", edge_id=edge_id)

    def prune_orphan_entities(self) -> int:
        rows = self._run(
            "MATCH (e:Entity) WHERE NOT (e)-[:REGULATES]-() "
            "WITH collect(e) AS orphans, count(e) AS c "
            "FOREACH (o IN orphans | DETACH DELETE o) RETURN c AS c"
        )
        return rows[0]["c"] if rows else 0

    # --- reads ---
    def all_edge_ids(self) -> set[int]:
        rows = self._run("MATCH ()-[r:REGULATES]->() RETURN r.edge_id AS id")
        return {row["id"] for row in rows}

    def count_entities(self) -> int:
        return self._run("MATCH (e:Entity) RETURN count(e) AS c")[0]["c"]

    def count_edges(self) -> int:
        return self._run("MATCH ()-[r:REGULATES]->() RETURN count(r) AS c")[0]["c"]

    def get_entity(self, pg_id: int) -> dict | None:
        rows = self._run("MATCH (e:Entity {pg_id:$pg_id}) RETURN e", pg_id=pg_id)
        return dict(rows[0]["e"]) if rows else None

    def get_edge(self, edge_id: int) -> dict | None:
        rows = self._run(
            "MATCH ()-[r:REGULATES {edge_id:$edge_id}]->() RETURN r", edge_id=edge_id
        )
        return dict(rows[0]["r"]) if rows else None

    # --- serialization helpers ---
    @staticmethod
    def _node_payload(node) -> dict:
        return {"data": {"id": str(node["pg_id"]), "pg_id": node["pg_id"],
                         "label": node.get("symbol", ""),
                         "entity_type": node.get("entity_type", ""),
                         "compartment": node.get("compartment", ""),
                         "networks": node.get("networks", [])}}

    @staticmethod
    def _rel_payload(rel, src_pg, tgt_pg) -> dict:
        return {"data": {"id": f"e{rel['edge_id']}", "edge_id": rel["edge_id"],
                         "source": str(src_pg), "target": str(tgt_pg),
                         "relation": rel.get("relation"), "belief": rel.get("belief_score"),
                         "status": rel.get("status"),
                         "n_supporting_papers": rel.get("n_supporting_papers"),
                         "n_models_agreeing": rel.get("n_models_agreeing"),
                         "networks": rel.get("networks", [])}}

    def _subgraph(self, cypher: str, **params) -> dict:
        """Run a query returning paths/rels and serialize to {nodes, edges}."""
        rows = self._run(cypher, **params)
        nodes: dict[int, dict] = {}
        edges: dict[int, dict] = {}
        for row in rows:
            for rel in row.get("rels", []):
                s, t = rel.start_node, rel.end_node
                nodes[s["pg_id"]] = self._node_payload(s)
                nodes[t["pg_id"]] = self._node_payload(t)
                edges[rel["edge_id"]] = self._rel_payload(rel, s["pg_id"], t["pg_id"])
        return {"nodes": list(nodes.values()), "edges": list(edges.values())}

    # --- query surface ---
    def neighborhood(self, *, entity_pg_id: int, k: int) -> dict:
        return self._subgraph(
            f"MATCH p=(c:Entity {{pg_id:$pg_id}})-[:REGULATES*1..{int(k)}]-(:Entity) "
            "UNWIND relationships(p) AS rel RETURN collect(rel) AS rels",
            pg_id=entity_pg_id,
        )

    def crosstalk_edges(self, *, network_a: str, network_b: str) -> dict:
        return self._subgraph(
            "MATCH (s:Entity)-[r:REGULATES]->(t:Entity) "
            "WHERE ($a IN r.networks AND $b IN r.networks) "
            "   OR ((s)-[:IN_NETWORK]->(:Network {code:$a}) AND "
            "       (t)-[:IN_NETWORK]->(:Network {code:$b})) "
            "   OR ((s)-[:IN_NETWORK]->(:Network {code:$b}) AND "
            "       (t)-[:IN_NETWORK]->(:Network {code:$a})) "
            "RETURN collect(r) AS rels",
            a=network_a, b=network_b,
        )

    def shortest_paths(self, *, source_pg_id: int, target_pg_id: int, max_len: int) -> list[dict]:
        rows = self._run(
            f"MATCH p=shortestPath((s:Entity {{pg_id:$s}})-[:REGULATES*..{int(max_len)}]->"
            "(t:Entity {pg_id:$t})) RETURN relationships(p) AS rels",
            s=source_pg_id, t=target_pg_id,
        )
        return self._rows_to_paths(rows)

    def all_simple_paths(self, *, source_pg_id: int, target_pg_id: int, max_len: int) -> list[dict]:
        rows = self._run(
            f"MATCH p=(s:Entity {{pg_id:$s}})-[:REGULATES*1..{int(max_len)}]->"
            "(t:Entity {pg_id:$t}) WHERE all(n IN nodes(p) WHERE "
            "size([m IN nodes(p) WHERE m=n])=1) RETURN relationships(p) AS rels",
            s=source_pg_id, t=target_pg_id,
        )
        return self._rows_to_paths(rows)

    def _rows_to_paths(self, rows) -> list[dict]:
        paths = []
        for row in rows:
            nodes: dict[int, dict] = {}
            edges: dict[int, dict] = {}
            for rel in row["rels"]:
                s, t = rel.start_node, rel.end_node
                nodes[s["pg_id"]] = self._node_payload(s)
                nodes[t["pg_id"]] = self._node_payload(t)
                edges[rel["edge_id"]] = self._rel_payload(rel, s["pg_id"], t["pg_id"])
            paths.append({"nodes": list(nodes.values()), "edges": list(edges.values())})
        return paths

    # --- GDS-backed analytics (anonymous projection per call) ---
    def _with_projection(self, network: str | None):
        """Context-manager-ish helper: project a named GDS graph, yield its name."""
        name = f"g_{uuid.uuid4().hex}"
        node_filter = "Entity"
        if network is None:
            self._run(
                "CALL gds.graph.project($name, $labels, "
                "{REGULATES: {orientation: 'NATURAL'}})",
                name=name, labels=node_filter,
            )
        else:
            self._run(
                "MATCH (e:Entity)-[:IN_NETWORK]->(:Network {code:$code}) "
                "WITH collect(e) AS ns "
                "CALL gds.graph.project.cypher($name, "
                "  'MATCH (e:Entity) WHERE e IN $ns RETURN id(e) AS id', "
                "  'MATCH (a:Entity)-[r:REGULATES]->(b:Entity) "
                "   WHERE a IN $ns AND b IN $ns RETURN id(a) AS source, id(b) AS target', "
                "  {parameters: {ns: ns}}) YIELD graphName RETURN graphName",
                name=name, code=network,
            )
        return name

    def _drop_projection(self, name: str) -> None:
        self._run("CALL gds.graph.drop($name, false) YIELD graphName", name=name)

    def centrality(self, *, network: str | None, measure: str) -> list[dict]:
        proc = {"pagerank": "gds.pageRank", "betweenness": "gds.betweenness",
                "degree": "gds.degree"}.get(measure)
        if proc is None:
            raise ValueError(f"unknown centrality measure: {measure}")
        name = self._with_projection(network)
        try:
            rows = self._run(
                f"CALL {proc}.stream($name) YIELD nodeId, score "
                "MATCH (e) WHERE id(e)=nodeId "
                "RETURN e.pg_id AS pg_id, e.symbol AS symbol, score "
                "ORDER BY score DESC",
                name=name,
            )
        finally:
            self._drop_projection(name)
        return [{"pg_id": r["pg_id"], "symbol": r["symbol"], "score": float(r["score"])}
                for r in rows]

    def communities(self, *, network: str | None) -> list[dict]:
        name = self._with_projection(network)
        try:
            rows = self._run(
                "CALL gds.louvain.stream($name) YIELD nodeId, communityId "
                "MATCH (e) WHERE id(e)=nodeId "
                "RETURN e.pg_id AS pg_id, e.symbol AS symbol, communityId AS community",
                name=name,
            )
        finally:
            self._drop_projection(name)
        return [{"pg_id": r["pg_id"], "symbol": r["symbol"], "community": r["community"]}
                for r in rows]

    def feedback_loops(self, *, max_len: int, network: str | None) -> list[dict]:
        scope = ""
        params = {"max_len": int(max_len)}
        if network is not None:
            scope = ("MATCH (start)-[:IN_NETWORK]->(:Network {code:$code}) "
                     "WITH collect(start) AS scope ")
            params["code"] = network
        rows = self._run(
            scope +
            f"MATCH p=(a:Entity)-[:REGULATES*1..{int(max_len)}]->(a) "
            + ("WHERE all(n IN nodes(p) WHERE n IN scope) " if network else "")
            + "RETURN nodes(p) AS ns, relationships(p) AS rels",
            **params,
        )
        loops = []
        for row in rows:
            edges: dict[int, dict] = {}
            nodes: dict[int, dict] = {}
            inhib = 0
            for rel in row["rels"]:
                s, t = rel.start_node, rel.end_node
                nodes[s["pg_id"]] = self._node_payload(s)
                nodes[t["pg_id"]] = self._node_payload(t)
                edges[rel["edge_id"]] = self._rel_payload(rel, s["pg_id"], t["pg_id"])
                if rel.get("relation") in INHIBITORY:
                    inhib += 1
            ring_len = len(row["rels"])
            loops.append({"nodes": list(nodes.values()), "edges": list(edges.values()),
                          "double_negative": ring_len == 2 and inhib == 2})
        return loops
```

- [ ] **Step 2: Verify it imports and satisfies the interface**

```bash
poetry run python -c "from analysis.backends.neo4j_backend import Neo4jBackend; from analysis.backends.base import GraphBackend; assert not getattr(Neo4jBackend, '__abstractmethods__', set()), Neo4jBackend.__abstractmethods__; print('Neo4jBackend concrete OK')"
```

Expected:
```
Neo4jBackend concrete OK
```

(If this prints a non-empty set, an abstract method is unimplemented — fix the
method set before proceeding.)

- [ ] **Step 3: Commit**

```bash
git add apps/analysis/backends/neo4j_backend.py
git commit -m "feat(analysis): add Neo4jBackend with Cypher + GDS implementation"
```

---

## Task 6: `edges_integrated` signal in `graph` + receiver in `analysis` (TDD)

This is the ONE behavioural change to a Phase 3 file. The signal is *defined*
in `graph` (the emitter owns it). The receiver lives in `analysis`. The
receiver dispatches the Celery task **by name** so `graph` carries no static
import of `analysis`, preserving the `analysis → graph` arrow.

**Files:**
- Create: `apps/graph/signals.py`
- Modify: `apps/graph/services.py` (`_post_integrate_hook` only)
- Create: `apps/analysis/signals.py`
- Create: `apps/analysis/tests/test_signal_wiring.py`

- [ ] **Step 1: Write the failing test in `apps/analysis/tests/test_signal_wiring.py`**

```python
"""The edges_integrated signal must enqueue project_edges by task name."""
from __future__ import annotations

from unittest.mock import patch

import pytest


def test_edges_integrated_enqueues_project_edges(db):
    from graph.signals import edges_integrated

    with patch("analysis.signals.current_app.send_task") as send_task:
        edges_integrated.send(sender=None, edge_ids=[101, 102])

    send_task.assert_called_once()
    args, kwargs = send_task.call_args
    assert args[0] == "analysis.tasks.project_edges"
    # edge_ids passed through to the task
    assert kwargs["args"][0] == [101, 102] or args[1] == [101, 102]


def test_edges_integrated_with_empty_ids_does_not_enqueue(db):
    from graph.signals import edges_integrated

    with patch("analysis.signals.current_app.send_task") as send_task:
        edges_integrated.send(sender=None, edge_ids=[])

    send_task.assert_not_called()


def test_graph_does_not_import_analysis():
    """Static guard: importing graph.signals/services must not import analysis."""
    import sys

    for mod in list(sys.modules):
        if mod.startswith("analysis"):
            del sys.modules[mod]
    import graph.services  # noqa: F401
    import graph.signals   # noqa: F401
    assert not any(m == "analysis" or m.startswith("analysis.") for m in sys.modules), \
        "graph must not import analysis (would be circular)"
```

- [ ] **Step 2: Run; confirm failure**

```bash
poetry run pytest apps/analysis/tests/test_signal_wiring.py -v
```

Expected:
```
ModuleNotFoundError: No module named 'graph.signals'
```

- [ ] **Step 3: Define the signal in `apps/graph/signals.py`**

```python
"""Graph app signals.

`edges_integrated` fires after normalize_and_integrate commits a batch of
edges. Downstream consumers (the analysis app's Neo4j projector) connect a
receiver. Defining the signal here keeps the import direction correct:
consumers import this module; graph never imports its consumers.
"""
from __future__ import annotations

import django.dispatch

# Providing arg: edge_ids -> list[int] of Edge.id touched by the batch.
edges_integrated = django.dispatch.Signal()
```

- [ ] **Step 4: Emit the signal from `_post_integrate_hook` in `apps/graph/services.py`**

Phase 3's `_post_integrate_hook(touched_edges, raws)` is the documented
extension point. Add the signal emission at its end (keep whatever conflict /
membership wiring later Phase 3 tasks already placed there):

```python
def _post_integrate_hook(touched_edges: set[int], raws: list) -> None:
    """Stitching point for conflict detection + network membership +
    downstream read-model projection.

    ... (existing Phase 3 body: detect_conflicts / reassign_network_membership) ...
    """
    # ... existing Phase 3 logic stays above this line ...

    # Phase 8: notify the read-model projector. Decoupled via signal so graph
    # never imports analysis (would be circular). Receiver lives in
    # analysis.signals and dispatches the Celery task by name.
    from graph.signals import edges_integrated

    edges_integrated.send(sender=None, edge_ids=list(touched_edges))
```

> **Note for the implementer:** if Phase 3's `_post_integrate_hook` is still the
> bare `return None` stub at execution time, replace the stub body with just the
> two-line signal emission above (the `from graph.signals import ...` and the
> `.send(...)`). The single load-bearing addition is that the signal fires with
> `edge_ids=list(touched_edges)` once per integrated batch.

- [ ] **Step 5: Implement the receiver in `apps/analysis/signals.py`**

```python
"""analysis signal receivers.

Connects to graph.signals.edges_integrated and enqueues the Neo4j projection
task BY NAME (celery send_task) so importing this module pulls in no graph
internals beyond the Signal object, and graph never imports analysis.
"""
from __future__ import annotations

from celery import current_app
from django.dispatch import receiver

from graph.signals import edges_integrated


@receiver(edges_integrated, dispatch_uid="analysis.project_on_edges_integrated")
def project_on_edges_integrated(sender, edge_ids, **kwargs) -> None:
    """On each integrated batch, enqueue analysis.tasks.project_edges."""
    edge_ids = list(edge_ids or [])
    if not edge_ids:
        return
    current_app.send_task(
        "analysis.tasks.project_edges",
        args=[edge_ids],
        queue="q.io",
    )
```

- [ ] **Step 6: Run; confirm green**

```bash
poetry run pytest apps/analysis/tests/test_signal_wiring.py -v
```

Expected:
```
test_edges_integrated_enqueues_project_edges PASSED
test_edges_integrated_with_empty_ids_does_not_enqueue PASSED
test_graph_does_not_import_analysis PASSED

3 passed
```

- [ ] **Step 7: Commit**

```bash
git add apps/graph/signals.py apps/graph/services.py apps/analysis/signals.py apps/analysis/tests/test_signal_wiring.py
git commit -m "feat(analysis): wire edges_integrated signal -> project_edges (analysis->graph only)"
```

---

## Task 7: Projection tasks — `project_edges` + `reconcile_neo4j` (TDD)

The Celery tasks that drive the backend. `project_edges` is incremental;
`reconcile_neo4j` diffs Postgres vs the read-model (nightly + rebuild path).

**Files:**
- Create: `apps/analysis/tasks.py`
- Create: `apps/analysis/tests/test_tasks.py`
- Modify: `interactome/settings/base.py` (Beat schedule)

- [ ] **Step 1: Write the failing tests in `apps/analysis/tests/test_tasks.py`**

```python
"""Tests for analysis.tasks: project_edges + reconcile_neo4j (FakeGraphBackend)."""
from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture
def patch_backend(fake_backend):
    """Make get_backend() return the shared in-memory fake."""
    with patch("analysis.tasks.get_backend", return_value=fake_backend):
        yield fake_backend


def test_project_edges_projects_accepted_edge(db, accepted_edge, patch_backend):
    from analysis.tasks import project_edges

    project_edges([accepted_edge.id])
    assert patch_backend.count_edges() == 1


def test_project_edges_is_idempotent(db, accepted_edge, patch_backend):
    from analysis.tasks import project_edges

    project_edges([accepted_edge.id])
    project_edges([accepted_edge.id])
    assert patch_backend.count_edges() == 1


def test_project_edges_removes_now_rejected_edge(db, accepted_edge, patch_backend):
    from analysis.tasks import project_edges

    project_edges([accepted_edge.id])
    accepted_edge.status = "rejected"
    accepted_edge.save(update_fields=["status"])
    project_edges([accepted_edge.id])
    assert patch_backend.count_edges() == 0


def test_reconcile_adds_missing_edges(db, accepted_edge, patch_backend):
    from analysis.tasks import reconcile_neo4j

    # Backend starts empty; Postgres has one accepted edge.
    assert patch_backend.count_edges() == 0
    result = reconcile_neo4j()
    assert patch_backend.count_edges() == 1
    assert result["added"] == 1
    assert result["removed"] == 0


def test_reconcile_removes_orphaned_edges(db, accepted_edge, patch_backend):
    from analysis.projection import project_edge_ids
    from analysis.tasks import reconcile_neo4j

    project_edge_ids([accepted_edge.id], backend=patch_backend)
    # Edge rejected in Postgres but still present in the read-model.
    accepted_edge.status = "rejected"
    accepted_edge.save(update_fields=["status"])
    result = reconcile_neo4j()
    assert patch_backend.count_edges() == 0
    assert result["removed"] == 1


def test_reconcile_rebuild_from_scratch(db, accepted_edge, patch_backend):
    from analysis.tasks import reconcile_neo4j

    # Simulate Neo4j loss: backend already cleared (empty). Full rebuild path.
    result = reconcile_neo4j(rebuild=True)
    assert patch_backend.count_edges() == 1
    assert result["added"] == 1
```

- [ ] **Step 2: Run; confirm failure**

```bash
poetry run pytest apps/analysis/tests/test_tasks.py -v
```

Expected:
```
ModuleNotFoundError: No module named 'analysis.tasks'
```

- [ ] **Step 3: Implement `apps/analysis/tasks.py`**

```python
"""analysis Celery tasks — incremental projection + nightly reconciliation.

Postgres is the system of record. project_edges reflects a batch of edges
into the Neo4j read-model; reconcile_neo4j sweeps the whole accepted-edge set
(nightly Beat) and is also the rebuild-from-scratch path after Neo4j loss.
"""
from __future__ import annotations

import logging

from celery import shared_task

from analysis.backends import get_backend
from analysis.projection import accepted_edge_ids, project_edge_ids

logger = logging.getLogger(__name__)

RECONCILE_CHUNK = 500


@shared_task(name="analysis.tasks.project_edges")
def project_edges(edge_ids: list[int]) -> dict:
    """Incrementally reflect the given edges into the read-model.

    Idempotent. Accepted edges are MERGEd; non-accepted (rejected/conflicted/
    candidate) edges have their relationship DELETEd. Called by the
    edges_integrated signal receiver after each integration batch.
    """
    backend = get_backend()
    backend.ensure_constraints()
    result = project_edge_ids(edge_ids, backend=backend)
    logger.info("project_edges: %s", result)
    return result


@shared_task(name="analysis.tasks.reconcile_neo4j")
def reconcile_neo4j(rebuild: bool = False) -> dict:
    """Diff Postgres accepted-edge set vs the read-model; converge them.

    * rebuild=False (nightly Beat): add edges present in Postgres but missing
      from Neo4j; remove relationships orphaned in Neo4j; prune dangling nodes.
    * rebuild=True (after Neo4j loss): clear the read-model first, then project
      the entire accepted-edge set. This is the "pull the plug" guarantee —
      Neo4j is fully reconstructable from Postgres.
    """
    backend = get_backend()
    backend.ensure_constraints()

    pg_ids = accepted_edge_ids()

    if rebuild:
        backend.clear_all()
        backend.ensure_constraints()
        present: set[int] = set()
    else:
        present = backend.all_edge_ids()

    missing = pg_ids - present
    orphaned = present - pg_ids

    # Add missing (chunked to avoid giant transactions).
    missing_list = sorted(missing)
    for i in range(0, len(missing_list), RECONCILE_CHUNK):
        project_edge_ids(missing_list[i:i + RECONCILE_CHUNK], backend=backend)

    # Remove orphaned relationships.
    for edge_id in orphaned:
        backend.delete_edge(edge_id)

    pruned = backend.prune_orphan_entities()

    result = {"added": len(missing), "removed": len(orphaned), "pruned": pruned,
              "rebuild": rebuild}
    logger.info("reconcile_neo4j: %s", result)
    return result
```

- [ ] **Step 4: Add the nightly Beat schedule entry in `interactome/settings/base.py`**

Merge into the existing `CELERY_BEAT_SCHEDULE` dict (following Phase 3's merge
idiom):

```python
CELERY_BEAT_SCHEDULE = {
    **globals().get("CELERY_BEAT_SCHEDULE", {}),
    "analysis-reconcile-neo4j": {
        "task": "analysis.tasks.reconcile_neo4j",
        "schedule": crontab(hour=4, minute=0),  # daily 04:00 UTC, after sbml.regenerate (02:00)
        "options": {"queue": "q.io"},
    },
}
```

(Ensure `from celery.schedules import crontab` is imported in `base.py`; Phase 3
may already import it. If not, add it near the top of the Celery section.)

- [ ] **Step 5: Run; confirm green**

```bash
poetry run pytest apps/analysis/tests/test_tasks.py -v
```

Expected:
```
test_project_edges_projects_accepted_edge PASSED
test_project_edges_is_idempotent PASSED
test_project_edges_removes_now_rejected_edge PASSED
test_reconcile_adds_missing_edges PASSED
test_reconcile_removes_orphaned_edges PASSED
test_reconcile_rebuild_from_scratch PASSED

6 passed
```

- [ ] **Step 6: Commit**

```bash
git add apps/analysis/tasks.py apps/analysis/tests/test_tasks.py interactome/settings/base.py
git commit -m "feat(analysis): add project_edges + reconcile_neo4j tasks with nightly Beat"
```

---

## Task 8: Crosstalk + analysis services (TDD)

The public API of the app: thin functions over the backend that return
JSON-serializable dicts/lists. Every one is tested against `FakeGraphBackend`
via a small projected atlas, so the service logic is verified without Neo4j.

**Files:**
- Create: `apps/analysis/services.py`
- Create: `apps/analysis/tests/test_services.py`

- [ ] **Step 1: Build a richer atlas fixture and write the failing tests in `apps/analysis/tests/test_services.py`**

```python
"""Service-layer tests over a projected FakeGraphBackend atlas."""
from __future__ import annotations

import pytest

from analysis.backends.fake import FakeGraphBackend


@pytest.fixture
def atlas() -> FakeGraphBackend:
    """A small two-network atlas with a crosstalk edge and a 2-cycle.

    Network A (nfkb): 1(IL1B) -> 2(NFKB1) -> 3(MMP3)
    Network B (sirt): 4(SIRT1) -> 2(NFKB1)            # 4 bridges B into A's NFKB1
    Mutual inhibition (double-negative): 2 -inhibits-> 4 and 4 -inhibits-> 2
    """
    b = FakeGraphBackend()
    nodes = {1: "IL1B", 2: "NFKB1", 3: "MMP3", 4: "SIRT1"}
    for pg, sym in nodes.items():
        b.upsert_entity({"pg_id": pg, "symbol": sym, "entity_type": "protein",
                         "compartment": "c", "canonical_uri": f"u{pg}", "ontology_id": pg})
    b.upsert_network({"code": "nfkb", "title": "NF-kB", "category": "I"})
    b.upsert_network({"code": "sirt", "title": "Sirtuin", "category": "III"})

    def edge(eid, s, t, rel, nets):
        b.upsert_edge(source_pg_id=s, target_pg_id=t, props={
            "edge_id": eid, "relation": rel, "belief_score": 0.8,
            "n_supporting_papers": 2, "n_models_agreeing": 3, "status": "accepted",
            "networks": nets})
    edge(10, 1, 2, "activates", ["nfkb"])
    edge(11, 2, 3, "activates", ["nfkb"])
    edge(12, 4, 2, "inhibits", ["sirt"])
    edge(13, 2, 4, "inhibits", ["nfkb"])   # together with 12 -> double negative

    for pg, code in [(1, "nfkb"), (2, "nfkb"), (3, "nfkb"), (2, "sirt"), (4, "sirt")]:
        b.link_in_network(entity_pg_id=pg, network_code=code)
    return b


@pytest.fixture
def svc(atlas, monkeypatch):
    """Point analysis.services at the prebuilt atlas backend."""
    import analysis.services as services
    monkeypatch.setattr(services, "get_backend", lambda: atlas)
    return services


def test_neighborhood_one_hop(db, svc):
    out = svc.neighborhood(entity_id=2, k=1)
    labels = {n["data"]["label"] for n in out["nodes"]}
    assert labels == {"IL1B", "NFKB1", "MMP3", "SIRT1"}


def test_crosstalk_edges_between_networks(db, svc):
    out = svc.crosstalk_edges(network_a="sirt", network_b="nfkb")
    # SIRT1->NFKB1 (12) bridges sirt into nfkb; NFKB1->SIRT1 (13) bridges back
    eids = {e["data"]["edge_id"] for e in out["edges"]}
    assert {12, 13} <= eids


def test_shortest_paths(db, svc):
    out = svc.shortest_paths(source_entity=1, target_entity=3, max_len=5)
    assert len(out) == 1
    eids = {e["data"]["edge_id"] for e in out[0]["edges"]}
    assert eids == {10, 11}


def test_all_simple_paths(db, svc):
    out = svc.all_simple_paths(source_entity=1, target_entity=3, max_len=5)
    assert len(out) >= 1


def test_centrality_pagerank_default(db, svc):
    ranked = svc.centrality()
    assert ranked[0]["symbol"] == "NFKB1"   # highest in-degree hub
    assert all("score" in r for r in ranked)


def test_centrality_rejects_unknown_measure(db, svc):
    with pytest.raises(ValueError):
        svc.centrality(measure="nonsense")


def test_communities(db, svc):
    comms = svc.communities()
    assert all("community" in c for c in comms)


def test_feedback_loops_flags_double_negative(db, svc):
    loops = svc.feedback_loops(max_len=4)
    dn = [loop for loop in loops if loop["double_negative"]]
    assert len(dn) >= 1   # the NFKB1<->SIRT1 mutual inhibition
```

- [ ] **Step 2: Run; confirm failure**

```bash
poetry run pytest apps/analysis/tests/test_services.py -v
```

Expected:
```
ModuleNotFoundError: No module named 'analysis.services'  (or AttributeError)
```

- [ ] **Step 3: Implement `apps/analysis/services.py`**

```python
"""analysis public API.

The app's services.py is the boundary other code calls (spec §2 boundary
discipline). Each function is a thin pass-through to the active GraphBackend,
returning plain JSON-serializable structures the views serialize directly.
Postgres remains the system of record; these are read-only queries over the
derived Neo4j read-model.
"""
from __future__ import annotations

from analysis.backends import get_backend


def neighborhood(*, entity_id: int, k: int = 1) -> dict:
    """k-hop neighborhood of an entity across the whole atlas.

    Returns {"nodes": [...], "edges": [...]} in Cytoscape element shape.
    """
    return get_backend().neighborhood(entity_pg_id=entity_id, k=k)


def crosstalk_edges(*, network_a: str, network_b: str) -> dict:
    """Relationships bridging network_a and network_b."""
    return get_backend().crosstalk_edges(network_a=network_a, network_b=network_b)


def shortest_paths(*, source_entity: int, target_entity: int, max_len: int = 6) -> list[dict]:
    """Shortest directed path(s) from source to target (each a subgraph dict)."""
    return get_backend().shortest_paths(
        source_pg_id=source_entity, target_pg_id=target_entity, max_len=max_len
    )


def all_simple_paths(*, source_entity: int, target_entity: int, max_len: int = 6) -> list[dict]:
    """All simple directed paths up to max_len hops."""
    return get_backend().all_simple_paths(
        source_pg_id=source_entity, target_pg_id=target_entity, max_len=max_len
    )


def centrality(*, network: str | None = None, measure: str = "pagerank") -> list[dict]:
    """GDS centrality ranking, optionally scoped to one network.

    measure ∈ {"pagerank", "betweenness", "degree"}.
    """
    if measure not in {"pagerank", "betweenness", "degree"}:
        raise ValueError(f"unknown centrality measure: {measure}")
    return get_backend().centrality(network=network, measure=measure)


def communities(*, network: str | None = None) -> list[dict]:
    """GDS Louvain community assignment, optionally scoped to one network."""
    return get_backend().communities(network=network)


def feedback_loops(*, max_len: int = 4, network: str | None = None) -> list[dict]:
    """Directed cycles up to max_len, each flagged with `double_negative`.

    A double-negative motif is a 2-cycle where both relations are inhibitory
    (mutual inhibition / toggle switch) — a load-bearing regulatory pattern.
    """
    return get_backend().feedback_loops(max_len=max_len, network=network)
```

- [ ] **Step 4: Run; confirm green**

```bash
poetry run pytest apps/analysis/tests/test_services.py -v
```

Expected:
```
test_neighborhood_one_hop PASSED
test_crosstalk_edges_between_networks PASSED
test_shortest_paths PASSED
test_all_simple_paths PASSED
test_centrality_pagerank_default PASSED
test_centrality_rejects_unknown_measure PASSED
test_communities PASSED
test_feedback_loops_flags_double_negative PASSED

8 passed
```

- [ ] **Step 5: Commit**

```bash
git add apps/analysis/services.py apps/analysis/tests/test_services.py
git commit -m "feat(analysis): add crosstalk + GDS analysis services over GraphBackend"
```

---

## Task 9: Explorer JSON/HTMX endpoints (TDD)

The view layer: JSON endpoints feeding Cytoscape and an HTMX partial for the
analysis panel. Views read the entity registry from Postgres (for the
entity-picker autocomplete) but graph traversal goes through `services.py`.

**Files:**
- Create: `apps/analysis/views.py`
- Create: `apps/analysis/urls.py`
- Modify: `interactome/urls.py`
- Create: `apps/analysis/tests/test_views.py`

- [ ] **Step 1: Write the failing tests in `apps/analysis/tests/test_views.py`**

```python
"""Tests for the analysis explorer views (FakeGraphBackend via settings)."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from django.test import Client


@pytest.fixture
def authed_client() -> Client:
    return Client(HTTP_REMOTE_USER="fchemorion")


@pytest.fixture
def patch_services_backend(projected_atlas):
    """Make every services.get_backend() call return the projected atlas."""
    with patch("analysis.services.get_backend", return_value=projected_atlas):
        yield projected_atlas


def test_explorer_page_renders(db, authed_client, settings):
    settings.ANALYSIS_GRAPH_BACKEND = "fake"
    r = authed_client.get("/analysis/")
    assert r.status_code == 200
    assert b"cytoscape" in r.content.lower()
    assert b"htmx" in r.content.lower()


def test_neighborhood_json(db, authed_client, accepted_edge, patch_services_backend):
    r = authed_client.get(f"/analysis/neighborhood.json?entity_id={accepted_edge.source_id}&k=1")
    assert r.status_code == 200
    data = r.json()
    assert "nodes" in data and "edges" in data
    assert len(data["edges"]) == 1


def test_crosstalk_json(db, authed_client, patch_services_backend):
    r = authed_client.get("/analysis/crosstalk.json?network_a=nfkb_axis&network_b=nfkb_axis")
    assert r.status_code == 200
    assert "edges" in r.json()


def test_paths_json_shortest(db, authed_client, accepted_edge, patch_services_backend):
    r = authed_client.get(
        f"/analysis/paths.json?source={accepted_edge.source_id}"
        f"&target={accepted_edge.target_id}&mode=shortest&max_len=3"
    )
    assert r.status_code == 200
    assert isinstance(r.json()["paths"], list)


def test_analysis_panel_partial_is_htmx(db, authed_client, patch_services_backend):
    r = authed_client.get("/analysis/panel/?measure=pagerank&max_len=4")
    assert r.status_code == 200
    # Returns an HTML fragment (no <html> shell) suitable for hx-target swap.
    assert b"<html" not in r.content.lower()
    assert b"Centrality" in r.content or b"centrality" in r.content


def test_neighborhood_json_requires_entity_id(db, authed_client, settings):
    settings.ANALYSIS_GRAPH_BACKEND = "fake"
    r = authed_client.get("/analysis/neighborhood.json")
    assert r.status_code == 400
```

- [ ] **Step 2: Run; confirm failure**

```bash
poetry run pytest apps/analysis/tests/test_views.py -v
```

Expected:
```
404 (no /analysis/ route) — or TemplateDoesNotExist
```

- [ ] **Step 3: Implement `apps/analysis/views.py`**

```python
"""analysis explorer views — JSON feeds + HTMX partials + the page shell."""
from __future__ import annotations

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render

from analysis import services


def explorer(request: HttpRequest) -> HttpResponse:
    """The full crosstalk-explorer page. Graph data is fetched async via JSON."""
    from networks.models import Network

    networks = list(Network.objects.values("code", "title", "category").order_by("category", "code"))
    return render(request, "analysis/explorer.html", {"networks": networks})


def neighborhood_json(request: HttpRequest) -> JsonResponse:
    entity_id = request.GET.get("entity_id")
    if not entity_id:
        return JsonResponse({"error": "entity_id required"}, status=400)
    k = int(request.GET.get("k", 1))
    data = services.neighborhood(entity_id=int(entity_id), k=k)
    return JsonResponse(data)


def crosstalk_json(request: HttpRequest) -> JsonResponse:
    a = request.GET.get("network_a")
    b = request.GET.get("network_b")
    if not a or not b:
        return JsonResponse({"error": "network_a and network_b required"}, status=400)
    return JsonResponse(services.crosstalk_edges(network_a=a, network_b=b))


def paths_json(request: HttpRequest) -> JsonResponse:
    try:
        source = int(request.GET["source"])
        target = int(request.GET["target"])
    except (KeyError, ValueError):
        return JsonResponse({"error": "source and target required"}, status=400)
    mode = request.GET.get("mode", "shortest")
    max_len = int(request.GET.get("max_len", 6))
    if mode == "all":
        paths = services.all_simple_paths(source_entity=source, target_entity=target, max_len=max_len)
    else:
        paths = services.shortest_paths(source_entity=source, target_entity=target, max_len=max_len)
    return JsonResponse({"paths": paths})


def analysis_panel(request: HttpRequest) -> HttpResponse:
    """HTMX partial: centrality ranking + communities + feedback loops.

    `network` (optional) scopes the GDS algorithms; `measure` selects the
    centrality measure; `max_len` bounds feedback-loop cycle length.
    """
    network = request.GET.get("network") or None
    measure = request.GET.get("measure", "pagerank")
    max_len = int(request.GET.get("max_len", 4))
    try:
        ranking = services.centrality(network=network, measure=measure)
    except ValueError:
        ranking = []
    context = {
        "measure": measure,
        "network": network,
        "centrality": ranking[:25],
        "communities": services.communities(network=network),
        "feedback_loops": services.feedback_loops(max_len=max_len, network=network),
    }
    return render(request, "analysis/_analysis_panel.html", context)
```

- [ ] **Step 4: Implement `apps/analysis/urls.py`**

```python
"""analysis URL conf."""
from __future__ import annotations

from django.urls import path

from analysis import views

app_name = "analysis"

urlpatterns = [
    path("", views.explorer, name="explorer"),
    path("neighborhood.json", views.neighborhood_json, name="neighborhood_json"),
    path("crosstalk.json", views.crosstalk_json, name="crosstalk_json"),
    path("paths.json", views.paths_json, name="paths_json"),
    path("panel/", views.analysis_panel, name="analysis_panel"),
]
```

- [ ] **Step 5: Include the URLs in `interactome/urls.py`**

Add to `urlpatterns`:

```python
    path("analysis/", include("analysis.urls")),
```

(Ensure `from django.urls import include, path` is present.)

- [ ] **Step 6: Run; confirm failure points only at missing templates**

```bash
poetry run pytest apps/analysis/tests/test_views.py -v
```

Expected: routing now resolves; failures are `TemplateDoesNotExist:
analysis/explorer.html`. Proceed to Task 10 for templates.

---

## Task 10: Explorer templates (HTMX + Cytoscape.js)

The UI surface, consistent with Phase 3/5 conventions (server-rendered Django
templates, HTMX partial swaps, Cytoscape.js from CDN).

**Files:**
- Create: `apps/analysis/templates/analysis/explorer.html`
- Create: `apps/analysis/templates/analysis/_analysis_panel.html`

- [ ] **Step 1: Create `apps/analysis/templates/analysis/explorer.html`**

```html
{% load static %}
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Atlas Crosstalk Explorer</title>
  <script src="https://unpkg.com/htmx.org@1.9.12"></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/cytoscape/3.30.2/cytoscape.min.js"></script>
  <style>
    body { font-family: system-ui, sans-serif; margin: 0; display: flex; height: 100vh; }
    #controls { width: 320px; padding: 1rem; border-right: 1px solid #ddd; overflow-y: auto; }
    #cy { flex: 1; }
    #panel { width: 340px; padding: 1rem; border-left: 1px solid #ddd; overflow-y: auto; }
    label { display: block; margin-top: .75rem; font-weight: 600; font-size: .85rem; }
    input, select, button { width: 100%; margin-top: .25rem; padding: .35rem; box-sizing: border-box; }
    button { cursor: pointer; margin-top: .75rem; }
    .hint { color: #777; font-size: .75rem; }
  </style>
</head>
<body>
  <div id="controls">
    <h3>Crosstalk Explorer</h3>

    <label>Entity neighborhood</label>
    <input id="entity_id" type="number" placeholder="Entity pg_id (e.g. 42)">
    <label>k (hops)</label>
    <input id="khops" type="number" value="1" min="1" max="4">
    <button onclick="loadNeighborhood()">Render neighborhood</button>

    <hr>
    <label>Network A</label>
    <select id="net_a">
      {% for n in networks %}<option value="{{ n.code }}">{{ n.title }}</option>{% endfor %}
    </select>
    <label>Network B</label>
    <select id="net_b">
      {% for n in networks %}<option value="{{ n.code }}">{{ n.title }}</option>{% endfor %}
    </select>
    <button onclick="loadCrosstalk()">Render crosstalk</button>

    <hr>
    <label>Path: source → target</label>
    <input id="src" type="number" placeholder="source pg_id">
    <input id="tgt" type="number" placeholder="target pg_id">
    <select id="path_mode">
      <option value="shortest">shortest</option>
      <option value="all">all simple</option>
    </select>
    <button onclick="loadPaths()">Render path(s)</button>
    <p class="hint">Nodes are colored by network membership.</p>
  </div>

  <div id="cy"></div>

  <div id="panel">
    <h3>Analysis</h3>
    <label>Centrality measure</label>
    <select id="measure" name="measure"
            hx-get="/analysis/panel/" hx-target="#analysis_panel" hx-trigger="change"
            hx-include="#max_len,#scope_net">
      <option value="pagerank">PageRank</option>
      <option value="betweenness">Betweenness</option>
      <option value="degree">Degree</option>
    </select>
    <label>Feedback loop max length</label>
    <input id="max_len" name="max_len" type="number" value="4" min="2" max="8"
           hx-get="/analysis/panel/" hx-target="#analysis_panel" hx-trigger="change"
           hx-include="#measure,#scope_net">
    <label>Scope to network (optional)</label>
    <select id="scope_net" name="network"
            hx-get="/analysis/panel/" hx-target="#analysis_panel" hx-trigger="change"
            hx-include="#measure,#max_len">
      <option value="">(whole atlas)</option>
      {% for n in networks %}<option value="{{ n.code }}">{{ n.title }}</option>{% endfor %}
    </select>
    <div id="analysis_panel" hx-get="/analysis/panel/?measure=pagerank&max_len=4"
         hx-trigger="load"></div>
  </div>

  <script>
    const cy = cytoscape({
      container: document.getElementById('cy'),
      style: [
        { selector: 'node', style: {
            'label': 'data(label)', 'font-size': 9, 'background-color': '#888',
            'text-valign': 'center', 'color': '#fff', 'width': 26, 'height': 26 } },
        { selector: 'node[?multinet]', style: { 'background-color': '#d62728' } },
        { selector: 'edge', style: {
            'label': 'data(relation)', 'font-size': 7, 'curve-style': 'bezier',
            'target-arrow-shape': 'triangle', 'width': 'mapData(belief, 0, 1, 1, 5)',
            'line-color': '#bbb', 'target-arrow-color': '#bbb' } },
      ],
      layout: { name: 'cose' },
    });

    function paint(data) {
      cy.elements().remove();
      (data.nodes || []).forEach(n => {
        n.data.multinet = (n.data.networks || []).length > 1;
      });
      cy.add((data.nodes || []).concat(data.edges || []));
      cy.layout({ name: 'cose', animate: false }).run();
    }
    function paintPaths(payload) {
      const nodes = {}, edges = {};
      (payload.paths || []).forEach(p => {
        (p.nodes || []).forEach(n => nodes[n.data.id] = n);
        (p.edges || []).forEach(e => edges[e.data.id] = e);
      });
      paint({ nodes: Object.values(nodes), edges: Object.values(edges) });
    }
    function loadNeighborhood() {
      const id = document.getElementById('entity_id').value;
      const k = document.getElementById('khops').value || 1;
      if (!id) return;
      fetch(`/analysis/neighborhood.json?entity_id=${id}&k=${k}`).then(r => r.json()).then(paint);
    }
    function loadCrosstalk() {
      const a = document.getElementById('net_a').value;
      const b = document.getElementById('net_b').value;
      fetch(`/analysis/crosstalk.json?network_a=${a}&network_b=${b}`).then(r => r.json()).then(paint);
    }
    function loadPaths() {
      const s = document.getElementById('src').value;
      const t = document.getElementById('tgt').value;
      const m = document.getElementById('path_mode').value;
      if (!s || !t) return;
      fetch(`/analysis/paths.json?source=${s}&target=${t}&mode=${m}&max_len=6`)
        .then(r => r.json()).then(paintPaths);
    }
  </script>
</body>
</html>
```

- [ ] **Step 2: Create `apps/analysis/templates/analysis/_analysis_panel.html`**

```html
<div>
  <h4>Centrality ({{ measure }}{% if network %} · {{ network }}{% endif %})</h4>
  <ol style="padding-left:1.1rem; font-size:.8rem;">
    {% for row in centrality %}
      <li>{{ row.symbol }} <span style="color:#777;">{{ row.score|floatformat:4 }}</span></li>
    {% empty %}
      <li class="hint">No nodes in scope.</li>
    {% endfor %}
  </ol>

  <h4>Communities</h4>
  <p style="font-size:.8rem;">
    {{ communities|length }} node assignments across detected communities.
  </p>

  <h4>Feedback loops (≤ length)</h4>
  <ul style="padding-left:1.1rem; font-size:.8rem;">
    {% for loop in feedback_loops %}
      <li>
        {{ loop.edges|length }}-edge cycle
        {% if loop.double_negative %}<strong style="color:#d62728;">· double-negative</strong>{% endif %}
      </li>
    {% empty %}
      <li class="hint">No cycles found in scope.</li>
    {% endfor %}
  </ul>
</div>
```

- [ ] **Step 3: Run the view tests; confirm green**

```bash
poetry run pytest apps/analysis/tests/test_views.py -v
```

Expected:
```
test_explorer_page_renders PASSED
test_neighborhood_json PASSED
test_crosstalk_json PASSED
test_paths_json_shortest PASSED
test_analysis_panel_partial_is_htmx PASSED
test_neighborhood_json_requires_entity_id PASSED

6 passed
```

- [ ] **Step 4: Commit**

```bash
git add apps/analysis/views.py apps/analysis/urls.py interactome/urls.py apps/analysis/templates/analysis/explorer.html apps/analysis/templates/analysis/_analysis_panel.html apps/analysis/tests/test_views.py
git commit -m "feat(analysis): add HTMX + Cytoscape.js crosstalk explorer UI"
```

---

## Task 11: Live Neo4j integration tests + pytest marker (TDD-flavored)

A small suite proving the real `Neo4jBackend` projects and answers a real GDS
call. Marked `@pytest.mark.neo4j`; skipped when `NEO4J_URI` is unset so the
default `pytest` run (and CI without a Neo4j) stays green.

**Files:**
- Modify: `pytest.ini` (register the `neo4j` marker)
- Create: `apps/analysis/tests/test_neo4j_integration.py`

- [ ] **Step 1: Register the marker in `pytest.ini`**

Add a `markers` section (merge with any existing one):

```ini
[pytest]
DJANGO_SETTINGS_MODULE = interactome.settings.dev
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = --strict-markers --strict-config --tb=short
markers =
    neo4j: integration tests requiring a live Neo4j (skipped if NEO4J_URI unset)
filterwarnings =
    error
    ignore::DeprecationWarning:celery.*
    ignore::DeprecationWarning:kombu.*
testpaths = apps
```

(Keep the existing `filterwarnings`/`testpaths` lines; the load-bearing addition
is the `markers =` block with the `neo4j` marker. `--strict-markers` makes an
unregistered `@pytest.mark.neo4j` an error, which is why registration is
required.)

- [ ] **Step 2: Write `apps/analysis/tests/test_neo4j_integration.py`**

```python
"""Live Neo4j integration tests.

Skipped automatically when NEO4J_URI is unset (the neo4j_backend fixture in
conftest.py calls pytest.skip). Run locally with:

    NEO4J_URI=bolt://localhost:7687 NEO4J_USER=neo4j \\
    NEO4J_PASSWORD=<pw> poetry run pytest -m neo4j -v

These verify the real driver + a real GDS PageRank call against the docker
neo4j service — the part FakeGraphBackend cannot exercise.
"""
from __future__ import annotations

import pytest


@pytest.mark.neo4j
def test_real_projection_and_counts(db, accepted_edge, neo4j_backend, settings):
    from analysis.projection import project_edge_ids

    project_edge_ids([accepted_edge.id], backend=neo4j_backend)
    assert neo4j_backend.count_entities() == 2
    assert neo4j_backend.count_edges() == 1
    assert neo4j_backend.all_edge_ids() == {accepted_edge.id}


@pytest.mark.neo4j
def test_real_projection_is_idempotent(db, accepted_edge, neo4j_backend):
    from analysis.projection import project_edge_ids

    project_edge_ids([accepted_edge.id], backend=neo4j_backend)
    project_edge_ids([accepted_edge.id], backend=neo4j_backend)
    assert neo4j_backend.count_edges() == 1


@pytest.mark.neo4j
def test_real_delete_on_reject(db, accepted_edge, neo4j_backend):
    from analysis.projection import project_edge_ids

    project_edge_ids([accepted_edge.id], backend=neo4j_backend)
    accepted_edge.status = "rejected"
    accepted_edge.save(update_fields=["status"])
    project_edge_ids([accepted_edge.id], backend=neo4j_backend)
    assert neo4j_backend.count_edges() == 0


@pytest.mark.neo4j
def test_real_gds_pagerank_runs(db, accepted_edge, neo4j_backend):
    """Exercise a real GDS projection + PageRank stream end-to-end."""
    from analysis.projection import project_edge_ids

    project_edge_ids([accepted_edge.id], backend=neo4j_backend)
    ranked = neo4j_backend.centrality(network=None, measure="pagerank")
    assert len(ranked) == 2
    assert all("score" in r and "symbol" in r for r in ranked)


@pytest.mark.neo4j
def test_real_neighborhood_query(db, accepted_edge, neo4j_backend):
    from analysis.projection import project_edge_ids

    project_edge_ids([accepted_edge.id], backend=neo4j_backend)
    out = neo4j_backend.neighborhood(entity_pg_id=accepted_edge.source_id, k=1)
    labels = {n["data"]["label"] for n in out["nodes"]}
    assert labels == {"IL1B", "NFKB1"}
```

- [ ] **Step 3: Verify the suite skips cleanly with no Neo4j**

```bash
poetry run pytest apps/analysis/tests/test_neo4j_integration.py -v
```

Expected (no `NEO4J_URI` in env):
```
test_real_projection_and_counts SKIPPED (NEO4J_URI not set ...)
test_real_projection_is_idempotent SKIPPED (NEO4J_URI not set ...)
test_real_delete_on_reject SKIPPED (NEO4J_URI not set ...)
test_real_gds_pagerank_runs SKIPPED (NEO4J_URI not set ...)
test_real_neighborhood_query SKIPPED (NEO4J_URI not set ...)

5 skipped
```

- [ ] **Step 4: (optional, requires docker) Run against the live service**

```bash
docker compose up -d neo4j
# wait for the healthcheck to report healthy
NEO4J_URI=bolt://localhost:7687 NEO4J_USER=neo4j \
  NEO4J_PASSWORD="$NEO4J_PASSWORD" \
  poetry run pytest -m neo4j -v
```

Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add pytest.ini apps/analysis/tests/test_neo4j_integration.py
git commit -m "test(analysis): add @pytest.mark.neo4j live projection + GDS integration suite"
```

---

## Task 12: ruff + mypy clean

**Files:** none new — fix lint/type findings only.

- [ ] **Step 1: Run ruff**

```bash
poetry run ruff check apps/analysis apps/graph/signals.py
poetry run ruff format --check apps/analysis
```

Fix anything reported (unused imports, line length). Re-run until clean.

- [ ] **Step 2: Run mypy**

```bash
poetry run mypy apps/analysis
```

Resolve type findings. Notes:
- `neo4j` and `networkx` ship types/`py.typed`; if mypy complains about
  missing stubs for `networkx`, add `networkx.*` to the mypy `ignore_missing_imports`
  override in `mypy.ini` (additive; do not loosen global strictness).
- The backend `_run` helper returns `list` of driver `Record`s; annotate it as
  `list` and access keys via `row["k"]` to keep the dict-shaped contract.

- [ ] **Step 3: Commit**

```bash
git add apps/analysis mypy.ini
git commit -m "chore(analysis): ruff + mypy clean"
```

---

## Task 13: End-to-end manual verification

Proves the whole Phase 8 loop on a running stack: integration → signal →
projection → explorer → GDS, plus the rebuild-from-loss guarantee.

- [ ] **Step 1: Bring the stack up (including neo4j)**

```bash
docker compose up -d postgres redis neo4j web beat worker_io
docker compose ps   # neo4j should be (healthy)
```

- [ ] **Step 2: Confirm constraints + an empty read-model**

```bash
docker compose exec web poetry run python manage.py shell -c "
from analysis.backends import get_backend
b = get_backend(); b.ensure_constraints()
print('entities', b.count_entities(), 'edges', b.count_edges())
"
```

Expected: `entities 0 edges 0` on a fresh database.

- [ ] **Step 3: Trigger a full reconcile (projects all accepted edges from Postgres)**

```bash
docker compose exec web poetry run python manage.py shell -c "
from analysis.tasks import reconcile_neo4j
print(reconcile_neo4j())
"
```

Expected: a dict like `{'added': N, 'removed': 0, 'pruned': 0, 'rebuild': False}`
where N == count of accepted edges in Postgres.

- [ ] **Step 4: Verify the explorer renders**

```bash
curl -s -H 'Remote-User: fchemorion' http://localhost:8000/analysis/ | grep -o 'Crosstalk Explorer'
```

Expected: `Crosstalk Explorer`.

- [ ] **Step 5: Verify a JSON endpoint and a GDS call**

```bash
# (substitute a real Entity pg_id from your data)
curl -s -H 'Remote-User: fchemorion' \
  "http://localhost:8000/analysis/neighborhood.json?entity_id=1&k=2" | head -c 200
docker compose exec web poetry run python manage.py shell -c "
from analysis import services
print(services.centrality(measure='pagerank')[:3])
"
```

Expected: a `{"nodes":[...],"edges":[...]}` fragment and a 3-row PageRank list.

- [ ] **Step 6: Verify the "pull the plug" rebuild guarantee**

```bash
docker compose stop neo4j
docker volume rm "$(docker compose config --volumes | grep neo4jdata | head -1)" || \
  docker volume rm interactome_neo4jdata
docker compose up -d neo4j   # wait for healthy
docker compose exec web poetry run python manage.py shell -c "
from analysis.tasks import reconcile_neo4j
print(reconcile_neo4j(rebuild=True))
"
```

Expected: `{'added': N, ...}` with N matching Step 3 — Neo4j fully rebuilt from
Postgres with zero data loss. Postgres was never touched.

- [ ] **Step 7: Confirm the signal path (incremental projection)**

```bash
docker compose exec web poetry run python manage.py shell -c "
from graph.signals import edges_integrated
edges_integrated.send(sender=None, edge_ids=[])  # no-op, proves wiring imports
print('signal wired OK')
"
docker compose logs --tail 20 worker_io | grep -i project_edges || echo "(no recent project_edges — fine if no integration ran)"
```

Expected: `signal wired OK`. After a real integration batch runs (Phase 3's
`graph.integrate_pending`), `worker_io` logs should show `project_edges`.

---

## Task 14: Final push and Phase 8 close-out

- [ ] **Step 1: Run the full local CI suite**

```bash
poetry run ruff check .
poetry run ruff format --check .
poetry run mypy apps interactome
poetry run pytest -v
```

All four must return exit code 0. The `@pytest.mark.neo4j` suite reports
`5 skipped` (no `NEO4J_URI` in CI), which does not fail the run.

- [ ] **Step 2: Push to origin**

```bash
git push origin main
```

- [ ] **Step 3: Verify GitHub Actions CI is green**

Open the repository's Actions tab; the latest run should be green within ~3 min.

- [ ] **Step 4: Tag the Phase 8 release**

```bash
git tag -a phase-8-complete -m "Phase 8 (Graph analysis & crosstalk) complete

- neo4j:5-community service (GDS + APOC) added to docker-compose
- analysis app: Postgres->Neo4j projection (incremental + nightly reconcile)
- GraphBackend interface + Neo4jBackend + FakeGraphBackend
- edges_integrated signal wiring (analysis -> graph, no circular import)
- crosstalk explorer UI (HTMX + Cytoscape.js)
- services: neighborhood, crosstalk, paths, centrality, communities, feedback loops
- @pytest.mark.neo4j live integration suite (skipped without NEO4J_URI)
- rebuild-from-Postgres verified (pull-the-plug guarantee intact)"
git push origin phase-8-complete
```

- [ ] **Step 5: Phase 8 done.**

The biologist can now query "everything N hops from gene X across the atlas"
and inter-network crosstalk interactively, run GDS centrality / Louvain
communities / feedback-loop motif detection, and the Neo4j read-model is fully
rebuildable from Postgres. Spec §10 roadmap row 8 deliverable met.

---

## Phase 8 Self-Review

**Spec coverage check** (against `docs/superpowers/specs/2026-05-19-disc-interactome-app-design.md`):

- ✅ **Section 1 (Neo4j-is-a-derived-read-model invariant)** — Postgres remains the system of record (Task 4 `accepted_edge_ids` reads it; projection never writes graph truth to Neo4j first). `reconcile_neo4j(rebuild=True)` reconstructs Neo4j fully from Postgres (Task 7 + Task 13 Step 6), so the "pull the plug" guarantee is preserved.
- ✅ **Section 2 (`analysis` app)** — new app with no Postgres models, owning the Neo4j read-model; depends on `graph` (reads `Edge`/`Entity`/`NetworkEdgeMembership`), never imported by `graph` (Task 6 `test_graph_does_not_import_analysis` enforces this). `services.py` is the public API boundary.
- ⏭️ Sections 3–8 (data model, pipeline, corpus, Celery topology details, SBML, resumability) — owned by Phases 1–7; this phase only *reads* the Phase 3 graph layer and adds one Beat entry.
- ✅ **Section 9 (deployment)** — `neo4j:5-community` service with `graph-data-science` + `apoc` plugins, `neo4jdata` volume, `NEO4J_AUTH` from env (Task 1); `.env.example` + settings additions; `neo4j` Python driver in `pyproject.toml`.
- ✅ **Section 10 (roadmap row 8)** — projection (incremental `project_edges` + nightly `reconcile_neo4j`), crosstalk explorer (Cytoscape.js + HTMX), GDS analysis (centrality, Louvain communities, feedback-loop motifs, pathfinding). Dependency on Phase 3 (Edge/NetworkEdgeMembership) and Phase 5 (UI conventions) honored.

**Subsystem coverage (from the task brief):**
1. Neo4j infra — Task 1. ✅
2. `analysis` scaffold (apps/services/tasks/backends/views/urls/templates/tests) — Tasks 2–11. ✅
3. Schema/projection mapping (Entity nodes keyed by `pg_id`; `:REGULATES` with canonical Edge props; `:Network` + `:IN_NETWORK`; `networks` array on rels) — "Neo4j read-model schema" section + Tasks 4/5. ✅
4. Projection tasks (`project_edges` incremental MERGE/DELETE idempotent; `reconcile_neo4j` nightly diff + rebuild; one-line signal emission in Phase 3's hook; receiver enqueues `project_edges`; Beat entry) — Tasks 6/7. ✅
5. Crosstalk + analysis services (`neighborhood`, `crosstalk_edges`, `shortest_paths`, `all_simple_paths`, `centrality`, `communities`, `feedback_loops` incl. double-negative flag; all return plain JSON-ready structures) — Task 8. ✅
6. Interactive explorer UI (entity neighborhood, two-network crosstalk, path A↔B, analysis panel; JSON + HTMX-partial endpoints; nodes colored by network membership) — Tasks 9/10. ✅
7. Testing (`FakeGraphBackend` unit tests; `@pytest.mark.neo4j` skipped-if-unset integration suite; marker config) — Tasks 3/8/11. ✅

**Placeholder scan:** No "TBD"/"TODO"/"implement later" strings. The only stub referenced is Phase 3's pre-existing `_post_integrate_hook`, which Task 6 *fills/extends* with the concrete two-line signal emission. Every step contains complete code, a complete command, or a single concrete file action.

**Type consistency / canonical names:** Read-model props are sourced exclusively through canonical names — `Edge.relation` (never `relation_type`), `Edge.belief_score`, `Edge.status`, `Edge.n_supporting_papers`, `Edge.n_models_agreeing` (reconciliation §4/§8), `Entity.symbol`/`compartment`/`canonical_uri` proxies + `ontology_entity.entity_type` (§5/§8), `Network.code`/`title`/`category` (§6), `NetworkEdgeMembership.network`/`edge`/`relevance`. `GraphBackend` method signatures are identical across `base.py`, `fake.py`, `neo4j_backend.py`, and call sites in `services.py`/`projection.py`/`tasks.py` (Task 5 Step 2 asserts `__abstractmethods__` is empty). The Celery task name `analysis.tasks.project_edges` is identical in `tasks.py` (`@shared_task(name=...)`) and the signal receiver's `send_task(...)`; `analysis.tasks.reconcile_neo4j` identical in `tasks.py` and the Beat schedule.

**Cross-phase dependency review:**
- **graph → analysis wiring (the load-bearing direction rule):** the `edges_integrated` signal is *defined in `graph`* (`graph/signals.py`) and *received in `analysis`* (`analysis/signals.py`), and the receiver dispatches the task by name via `current_app.send_task` — so `graph` carries no static import of `analysis`. Enforced by `test_graph_does_not_import_analysis`. The single behavioural change to a Phase 3 file is the two-line emission inside the documented `_post_integrate_hook` extension point.
- **Phase 3 models consumed:** `graph.Edge` (`id`, `relation`, `belief_score`, `status`, `n_supporting_papers`, `n_models_agreeing`, `source`/`target`, `network_memberships` reverse), `graph.Entity` (`id`, proxy `symbol`/`compartment`/`canonical_uri`, `ontology_entity.entity_type`/`id`), `graph.NetworkEdgeMembership` (`network__code` via reverse `network_memberships`). No upstream model altered.
- **Phase 5 conventions reused:** HTMX + Cytoscape.js + CDN, server-rendered Django templates with partial swaps — matched, not imported.
- **Phase 0 infra reused:** Celery `autodiscover_tasks` (picks up `analysis/tasks.py`), `AppConfig.ready()` (connects the receiver), settings package, `docker-compose.yml`, `.env.example`.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-19-phase-8-graph-analysis.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task with
review between tasks. The backend/interface seam (Tasks 3–5), the signal wiring
(Task 6), and the services (Task 8) each benefit from independent review of a
single commit. Tasks 1–2 (infra/scaffold) and 9–10 (views/templates) are
naturally independent units.

**2. Inline Execution** — execute tasks in this session using `executing-plans`,
with checkpoints after Task 7 (projection loop closed) and after Task 11
(integration suite). Verify the live Neo4j path (Task 13) on the cluster, since
local docker may not have the GDS plugin warmed.

**Pre-flight:** confirm Phase 3 is merged (the `graph.Edge`/`Entity`/
`NetworkEdgeMembership` models and the `normalize_and_integrate`
`_post_integrate_hook` extension point exist) and that
`2026-05-19-cross-plan-reconciliation.md` §4/§5/§6/§8 canonical names are the
ones present in the live `graph` models before wiring the projection mapping.
