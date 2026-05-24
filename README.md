# IVD Regulatory Network Atlas — v1.0.0

Autonomous PubMed → SBML-qual pipeline for intervertebral disc regulatory
networks. Built as a Django application hosted alongside the SIMBIOsys
Ollama gateway.

**Status: v1.0.0 (Phase 7 complete).** All phases (0–8) implemented.
The NF-κB axis network is the first to be signed off by a curator at v1.0.0.
The stack runs 18–20 Docker Compose services on the SIMBIOsys cluster.
855 tests passing (ruff + mypy + pytest all green).

## Documentation

- [Full design specification](docs/superpowers/specs/2026-05-19-disc-interactome-app-design.md)
- [Operations runbook](docs/runbook.md) — six named procedures (deploy, restore, hardware failure, Ollama outage, full bring-up, Authelia outage)
- [Biologist onboarding guide](docs/onboarding-biologist.md) — access, dashboard, colour codes, first edge review, sign-off semantics
- [Sign-off ceremony record](docs/signoff-ceremony.md) — NF-κB axis ceremony procedure + record template
- [Security review](docs/security-review.md) — Caddy/Authelia/Django hardening record
- [Phase 0 implementation plan](docs/superpowers/plans/2026-05-19-phase-0-foundation.md)
- [Phase 1 implementation plan (master corpus — complete)](docs/superpowers/plans/2026-05-19-phase-1-master-corpus.md)
- [Phase 4 implementation plan (SBML-qual emission — complete)](docs/superpowers/plans/2026-05-19-phase-4-sbml-emission.md)
- [Phase 7 implementation plan (hardening + handoff — complete)](docs/superpowers/plans/2026-05-19-phase-7-hardening.md)

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
docker-compose ps         # check all 9 services are healthy (Phase 1 added worker_fast)
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

## Phase 8 — Graph Analysis & Crosstalk Explorer (complete, branch: phase-8-graph-analysis)

Phase 8 adds the `analysis` app, which stands up Neo4j as a *derived, rebuildable*
read-model of the accepted-`Edge` graph and ships an interactive cross-network
crosstalk explorer on top of it.

### Neo4j read-model

Postgres is the system of record; Neo4j is derived and fully rebuildable from it
via `analysis.tasks.reconcile_neo4j(rebuild=True)` — the "pull the plug" guarantee.
Accepted `Edge` records are projected as `(:Entity)-[:REGULATES {edge_id,...}]->(:Entity)`
relationships; network membership is stored as `(:Entity)-[:IN_NETWORK]->(:Network)`.

```bash
# Trigger a full reconcile/rebuild from Postgres
docker compose exec web poetry run python manage.py shell -c "
from analysis.tasks import reconcile_neo4j
print(reconcile_neo4j(rebuild=True))
"
```

### Analysis explorer

Navigate to `/analysis/` to use the interactive Cytoscape.js + HTMX explorer:

- **Neighborhood** — k-hop neighborhood of any entity across the whole atlas
- **Crosstalk** — edges bridging any two networks
- **Paths** — shortest or all simple directed paths between two entities
- **Analysis panel** — GDS PageRank / betweenness / degree centrality, Louvain
  community detection, directed feedback loops (with double-negative motif flagging)

JSON endpoints are available for programmatic use:

```bash
# k-hop neighborhood (entity_id is graph.Entity.pk)
curl -H 'Remote-User: fchemorion' \
  'http://localhost:8000/analysis/neighborhood.json?entity_id=1&k=2'

# Cross-network crosstalk
curl -H 'Remote-User: fchemorion' \
  'http://localhost:8000/analysis/crosstalk.json?network_a=nfkb_axis&network_b=sirt_axis'
```

### Running Phase 8 integration tests against a live Neo4j

The `@pytest.mark.neo4j` suite is skipped by default (no `NEO4J_URI` → deselected,
not failed). To run against a live Neo4j with GDS + APOC:

```bash
docker compose up -d neo4j   # wait for (healthy)
NEO4J_URI=bolt://localhost:7687 NEO4J_USER=neo4j \
  NEO4J_PASSWORD="$(grep NEO4J_PASSWORD .env | cut -d= -f2)" \
  poetry run pytest -m neo4j -v
```

Expected: `5 passed`.

### Tests

- **740 offline tests passing** — ruff + mypy + pytest all green; `neo4j` marker tests deselected
- Offline e2e (`test_e2e_offline.py`) seeds Postgres → runs `project_edges` →
  asserts services (crosstalk, centrality, feedback loops) → checks explorer JSON
  Cytoscape shape — all without a live Neo4j instance

## Phase 5 — Verification UI (complete, branch: phase-5-verification-ui)

Phase 5 adds the `verify` app and extends the `dashboard` app with the full
curator verification workflow:

- **Network grid** (`/`) — 17-category dashboard with status pills, edge counts, open conflict counts
- **Per-network detail** (`/networks/<code>/`) — Cytoscape.js graph, ModelVersion versions panel, sign-off button
- **Disagreement queue** (`/networks/<code>/queue/`) — side-by-side conflict evidence + HTMX resolve form
- **Audit trail** (`/edges/<pk>/audit/`) — full Paper → Chunk → ExtractionRun → RawPPI → EdgeEvidence → Edge provenance chain
- **Subscription manager** (`/subscriptions/`) — per-user subscription toggle/delete with HTMX
- **Sign-off endpoint** (`POST /verify/networks/<code>/sign-off/<semver>/`) — transitions network to `verified`, enqueues `sbml.tasks.regenerate(triggered_by_curator=True)`, notifies subscribers
- **mark_stale hook** — `graph.services.reassign_network_membership` now calls `verify.services.mark_stale` so verified/idle networks are demoted to stale AND subscribers are notified when new edges arrive
- **CSRF + Authelia** — HTMX `configRequest` listener in `base.html` auto-injects `X-CSRFToken` from the `csrftoken` cookie; production `CSRF_TRUSTED_ORIGINS` is wired from `DJANGO_CSRF_TRUSTED_ORIGINS` env var
- **Beat schedule** — `verify.notify` and `verify.dispatch_review_assignments` both on `q.io` (handled by `worker_io`)
- **682 tests passing** — ruff + mypy + pytest all green

### Verification workflow (curator)

1. Log in at `https://interactome.simbiosys.sb.upf.edu/` via Authelia SSO.
2. See all networks at a glance; click a network with open disagreements.
3. Walk the disagreement queue; resolve each conflict via the HTMX form.
4. Review individual edges via the inline approve/reject/discuss buttons.
5. Click "Sign off" on the version_draft network; enter curator notes.
6. Network transitions to `verified`; SBML regeneration with MAJOR semver bump is queued; subscribers are notified.

## Phase 4 — SBML-qual Emission (complete)

Phase 4 adds the `sbml` app, which converts accepted `Edge` records from the
graph into versioned SBML-qual model files:

- `ModelVersion` — one row per `(network, semver)` snapshot, frozen after upload
- `ExportArtifact` — append-only download audit log
- `sbml.tasks.regenerate` — builds SBML-qual + `edges.csv` + `evidence.csv` + ZIP, uploads to MinIO, creates+freezes `ModelVersion`
- `sbml.tasks.regenerate_stale_networks` — daily Beat task that enqueues all stale networks
- Download endpoint: `GET /networks/<code>/v/<semver>/download?type=zip|sbml|edges_csv|evidence_csv`
- MinIO bucket bootstrap via `minio_bootstrap` compose service (idempotent)

### Downloading SBML artifacts

```bash
# Download the latest ZIP for a network (requires Authelia auth header in prod)
curl -H 'Remote-User: fchemorion' \
  'https://interactome.simbiosys.sb.upf.edu/networks/nfkb_axis/v/0.1.0/download?type=zip' \
  -L -o nfkb_v0.1.0.zip

# Or just the SBML file
curl -H 'Remote-User: fchemorion' \
  'https://interactome.simbiosys.sb.upf.edu/networks/nfkb_axis/v/0.1.0/download?type=sbml' \
  -L -o model.sbml
```

### Running the MinIO end-to-end test

```bash
# Bring up MinIO locally first
docker compose up -d minio minio_bootstrap

# Then run the minio marker tests
MINIO_TEST_ENDPOINT=http://localhost:9000 \
MINIO_TEST_ACCESS_KEY=interactome \
MINIO_TEST_SECRET_KEY=interactome \
  poetry run pytest -m minio -v
```

## Project layout

See [the design spec](docs/superpowers/specs/2026-05-19-disc-interactome-app-design.md#2-django-apps-and-module-boundaries)
for the full architecture. Phase 0 provides the `core` app; Phase 1 (complete)
adds `networks`, `corpus`, `papers`, `schedule`, and `dashboard` — including
the full PubMed→SBML pipeline and `/corpus/export.csv` master corpus export.
Phase 4 (complete) adds `sbml` — SBML-qual emission, versioning, and artifact
download. Subsequent phases add `verify` and `graph analysis`.

## Corpus export (Phase 1 deliverable)

```bash
# All papers as CSV
curl -H 'Remote-User: fchemorion' https://interactome.simbiosys.sb.upf.edu/corpus/export.csv -o corpus.csv

# Network-filtered (score >= 0.5 by default)
curl -H 'Remote-User: fchemorion' \
  'https://interactome.simbiosys.sb.upf.edu/corpus/export.csv?network=nfkb_axis' \
  -o nfkb.csv

# Wide format with classifier and full-text columns
curl -H 'Remote-User: fchemorion' \
  'https://interactome.simbiosys.sb.upf.edu/corpus/export.csv?format=full' \
  -o corpus_full.csv

# Corpus statistics dashboard
curl -H 'Remote-User: fchemorion' https://interactome.simbiosys.sb.upf.edu/corpus/stats
```

## Phase 7 — Hardening + Handoff (complete, v1.0.0)

Phase 7 makes the stack production-grade:

- **pgbackrest backups** — daily incremental + weekly full + automated restore-test
- **Off-host rsync** — weekly copy of `backupdata` + `miniodata` to backup host
- **Sentry** — exception capture wired into Django and all Celery workers
- **Prometheus + Grafana** — `/metrics/` endpoint, custom collectors (queue depth, healthcheck age), provisioned dashboard
- **Covering indexes** — Phase 7 adds performance indexes on `corpus_paper`, `graph_edge`, `verify_reviewassignment` for the hottest dashboard queries
- **`signoff_ceremony` management command** — scripted first-sign-off with `--dry-run` mode
- **Operations runbook** — `docs/runbook.md` with six named procedures
- **Biologist onboarding** — `docs/onboarding-biologist.md`
- **Sign-off ceremony record** — `docs/signoff-ceremony.md`
- **Security hardening** — Caddy security headers, deprecated setting removal, full review in `docs/security-review.md`
- **855 tests passing**

## Deployment

The cluster host runs the same `docker-compose.yml`. See the
[operations runbook](docs/runbook.md) for the full bring-up procedure.
For IT prerequisites (DNS, Authelia AD group `simbiosys-lab`), see
[Section 9 of the spec](docs/superpowers/specs/2026-05-19-disc-interactome-app-design.md#9-deployment-and-operations).

## License

UPF / SIMBIOsys research code. Contact Francis Chemorion before
redistributing.
