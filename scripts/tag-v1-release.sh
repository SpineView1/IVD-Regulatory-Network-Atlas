#!/usr/bin/env bash
# Guarded v1.0.0 release tagger — see Phase 7 plan Task 16.
#
# Usage:
#   bash scripts/tag-v1-release.sh
#
# This script MUST be run AFTER:
#   1. The sign-off ceremony has been completed and recorded in
#      docs/signoff-ceremony.md (Guard 4 checks this).
#   2. The branch has been merged to main (Guard 2 checks this).
#   3. The working tree is clean (Guard 1 checks this).
#
# The script does NOT push. After it succeeds, run:
#   git push origin v1.0.0
#
# It also does NOT create a GitHub Release. That is the controller's job.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "=== v1.0.0 release tagger ==="

# Guard 1: working tree must be clean.
if ! git diff-index --quiet HEAD --; then
    echo "ERROR: working tree has uncommitted changes. Commit or stash first." >&2
    exit 1
fi
echo "[PASS] Guard 1: working tree is clean"

# Guard 2: must be on main.
branch=$(git rev-parse --abbrev-ref HEAD)
if [ "$branch" != "main" ]; then
    echo "ERROR: must be on branch 'main'; currently on '$branch'." >&2
    echo "       Merge the phase-7-hardening branch to main first." >&2
    exit 1
fi
echo "[PASS] Guard 2: on branch main"

# Guard 3: v1.0.0 tag must not already exist.
if git rev-parse --verify --quiet "refs/tags/v1.0.0" >/dev/null; then
    echo "ERROR: tag v1.0.0 already exists. Nothing to do." >&2
    exit 1
fi
echo "[PASS] Guard 3: v1.0.0 tag does not yet exist"

# Guard 4: at least one ceremony record line in docs/signoff-ceremony.md.
# A record line looks like: | 2026-05-24 | nfkb_axis_mmp_adamts | ...
if ! grep -qE '^\| 20[0-9]{2}-[0-9]{2}-[0-9]{2} \|' docs/signoff-ceremony.md 2>/dev/null; then
    echo "ERROR: docs/signoff-ceremony.md has no completed ceremony record." >&2
    echo "       Complete the first sign-off ceremony before tagging." >&2
    exit 1
fi
echo "[PASS] Guard 4: signoff-ceremony.md has a recorded ceremony"

# Guard 5: full CI gate (ruff + mypy + pytest).
echo "--- running ruff check ..."
poetry run ruff check .
echo "--- running ruff format check ..."
poetry run ruff format --check .
echo "--- running mypy ..."
poetry run mypy .
echo "--- running pytest ..."
poetry run pytest -q

echo "[PASS] Guard 5: ruff + mypy + pytest all green"

# All guards passed — tag.
sha=$(git rev-parse --short HEAD)

git tag -a v1.0.0 -m "v1.0.0 — Phase 7 closeout

First production-ready release of the IVD Regulatory Network Atlas.

Phases 0–6 / 8:
  0  Foundation — Django / Celery / Postgres / Redis / MinIO / Authelia
  1  Master IDD corpus — PubMed ingest, classification, sectioning
  2  Extraction — 7-model PPI extraction via Ollama
  3  Graph integration — belief-scored Edge graph, Gilda grounding
  4  SBML-qual emission — MIRIAM-annotated models, semver, per-version ZIP
  5  Verification UI — biologist review, disagreement queue, sign-off
  6  Continuous monitoring — healthcheck, paper→notification loop
  8  Graph analysis — Neo4j read-model, crosstalk explorer

Phase 7 (this release):
  Pgbackrest backups (daily incr + weekly full + weekly restore-test)
  Sentry exception capture (web + all workers)
  Prometheus + Grafana sidecars + /metrics/ endpoint
  Phase 7 covering indexes on dashboard hot paths
  signoff_ceremony management command (dry-run + commit)
  Operations runbook (docs/runbook.md) — 6 named procedures
  Biologist onboarding (docs/onboarding-biologist.md)
  First sign-off ceremony on nfkb_axis_mmp_adamts (docs/signoff-ceremony.md)
  Security review + hardening (docs/security-review.md)
  Deployment summary email draft (docs/deployment-summary-email.md)

Git SHA: $sha
"

echo ""
echo "=== Tagged v1.0.0 at $sha ==="
echo ""
echo "Next steps:"
echo "  git push origin v1.0.0"
echo "  Create GitHub Release at https://github.com/SpineView1/IVD-Regulatory-Network-Atlas/releases"
