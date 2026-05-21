# Phase 5: Verification UI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the biologist-facing verification UI on top of the Phase 3 `Edge` / `Conflict` graph and the Phase 4 `ModelVersion` snapshots. End state: a biologist logs in via Authelia, sees all 200+ networks on a grid dashboard, drills into a network to view a Cytoscape.js graph of its edges, walks the disagreement queue resolving conflicts via HTMX-driven forms, downloads the SBML/CSV bundle, and finally signs off — bumping the model from `version_draft` to `verified` and cutting a curator MAJOR semver via `sbml.regenerate`. Subscribers receive email + in-app notifications on every status transition.

**Architecture:** Two new Django apps (`verify`, `dashboard`) plus an extension of the existing `sbml` app's URL surface. `verify` owns the append-only `Review` + `Signoff` + `ReviewAssignment` + `Subscription` + `Notification` tables and the workflow state machine. `dashboard` owns templates + read-only views over every other app. No SPA: every interaction is an HTMX POST → Django view → DB write → `hx-swap` partial template. Cytoscape.js, DataTables.js, htmx.org all loaded via CDN. Email sent through Django's `EMAIL_BACKEND` (console in dev, SMTP in production). All persistent state remains in Postgres — the verification layer obeys the spec's append-only audit-row invariant: a `Review` row is never UPDATEd; every decision change is a new row.

**Tech Stack:** Python 3.12, Django 5.0, HTMX 2.0 (CDN), Cytoscape.js 3.30 (CDN), DataTables.js 2.1 (CDN), Bootstrap 5.3 (CDN — for layout primitives), python-libsbml (already a Phase 4 dependency), pytest 8 + pytest-django 4.8 + pytest-mock 3.14.

**Reference spec:** `docs/superpowers/specs/2026-05-19-disc-interactome-app-design.md` Sections 2 (verify + dashboard app boundaries), 3 ("Provenance is a graph, not a string"; append-only audit rows), 7 (SBML output + five verification screens + sign-off state machine), 10 (Phase 5 row of the roadmap).

**Cross-phase dependencies (must already exist before starting Phase 5):**
- Phase 0 — `core.middleware.AutheliaRemoteUserMiddleware`, `TimestampedModel`, `core.urls`.
- Phase 1 — `networks.Network` (with `code`, `name`, `category`, `pipeline_status` fields), `corpus.Paper`, `corpus.PaperRelevance`.
- Phase 2 — `extract.ExtractionRun`, `extract.RawPPI` (used in the audit trail page).
- Phase 3 — `graph.Entity`, `graph.Edge` (with `source`, `target`, `relation_type`, `belief_score`, `status`), `graph.EdgeEvidence`, `graph.Conflict` (with `network`, `edge_a`, `edge_b`, `resolution_status`), `graph.NetworkEdgeMembership`.
- Phase 4 — `sbml.ModelVersion` (with `network`, `semver`, `frozen_at`, `s3_key`), `sbml.ExportArtifact`, the `sbml.regenerate(network_id, *, bump='major')` service callable.

---

## File Structure After Phase 5

```
/
├── apps/
│   ├── verify/                                NEW Django app
│   │   ├── __init__.py
│   │   ├── apps.py
│   │   ├── models.py                          Review, Signoff, ReviewAssignment,
│   │   │                                       Subscription, Notification
│   │   ├── services.py                        Public API: record_review,
│   │   │                                       sign_off, notify, state machine
│   │   ├── state_machine.py                   Network status transitions
│   │   ├── tasks.py                           verify.notify Celery task,
│   │   │                                       dispatch_review_assignments
│   │   ├── emails.py                          Email rendering helpers
│   │   ├── urls.py                            HTMX endpoints
│   │   ├── views.py                           POST handlers + partial renderers
│   │   ├── admin.py                           Django admin registration
│   │   ├── templates/verify/
│   │   │   ├── partials/
│   │   │   │   ├── conflict_card.html         single conflict row (HTMX target)
│   │   │   │   ├── review_history.html        append-only history list
│   │   │   │   ├── notification_dropdown.html nav-bar dropdown
│   │   │   │   └── signoff_button.html        button + state badge
│   │   │   └── emails/
│   │   │       ├── stale_subject.txt
│   │   │       ├── stale_body.txt
│   │   │       ├── signoff_subject.txt
│   │   │       ├── signoff_body.txt
│   │   │       ├── new_version_subject.txt
│   │   │       └── new_version_body.txt
│   │   ├── migrations/
│   │   │   └── __init__.py
│   │   └── tests/
│   │       ├── __init__.py
│   │       ├── conftest.py                    fixtures: user, network,
│   │       │                                  edge, conflict, modelversion
│   │       ├── test_models.py                 append-only invariant tests
│   │       ├── test_state_machine.py          status transition rules
│   │       ├── test_services.py               record_review, sign_off, notify
│   │       ├── test_views.py                  HTMX POST endpoints
│   │       ├── test_emails.py                 email rendering + send
│   │       └── test_tasks.py                  verify.notify task
│   ├── dashboard/                             NEW Django app
│   │   ├── __init__.py
│   │   ├── apps.py
│   │   ├── views.py                           grid, network_detail, queue,
│   │   │                                       audit_trail, subscriptions
│   │   ├── urls.py
│   │   ├── context_processors.py              unread_notifications_count
│   │   ├── templatetags/
│   │   │   ├── __init__.py
│   │   │   └── dashboard_extras.py            status_pill, belief_color
│   │   ├── templates/
│   │   │   ├── base.html                      site chrome, nav, CDN scripts
│   │   │   ├── dashboard/
│   │   │   │   ├── grid.html                  top-level 200-network grid
│   │   │   │   ├── network_detail.html        graph + versions split layout
│   │   │   │   ├── disagreement_queue.html    conflict list + forms
│   │   │   │   ├── audit_trail.html           per-edge provenance tree
│   │   │   │   └── subscriptions.html         user's subscription manager
│   │   │   └── partials/
│   │   │       ├── category_section.html      one of 17 categories on grid
│   │   │       ├── network_card.html          status pill + counts
│   │   │       └── cytoscape_init.html        graph init JS block
│   │   ├── migrations/
│   │   │   └── __init__.py
│   │   └── tests/
│   │       ├── __init__.py
│   │       ├── conftest.py
│   │       ├── test_grid.html_view.py         (NB: see Task 9 — filename
│   │       │                                  is test_grid_view.py)
│   │       ├── test_network_detail.py
│   │       ├── test_disagreement_queue.py
│   │       ├── test_audit_trail.py
│   │       └── test_subscriptions.py
│   └── sbml/
│       └── urls.py                            EXTEND: per-version download
│                                              endpoints if not already present
├── interactome/
│   ├── settings/
│   │   ├── base.py                            EXTEND: add 'verify', 'dashboard'
│   │   │                                       to INSTALLED_APPS; add the
│   │   │                                       dashboard context processor;
│   │   │                                       email backend defaults
│   │   ├── dev.py                             EXTEND: console email backend
│   │   └── production.py                      EXTEND: SMTP backend env vars
│   └── urls.py                                EXTEND: include verify.urls,
│                                                       dashboard.urls
└── docs/
    └── superpowers/
        └── plans/
            └── 2026-05-19-phase-5-verification-ui.md   THIS FILE
```

**Why this layout:**
- `verify` owns **state**: models, tasks, services, state machine. It exposes a small Python API (`services.py`) and a small HTML-fragment API (`urls.py` returning HTMX partials).
- `dashboard` owns **presentation**: page-level views, templates, the global `base.html` chrome. It depends on every other app's `services.py` and read-only models — never on tasks.
- Templates live with the app that *owns* the fragment. Page-level templates live in `dashboard/templates/dashboard/`. HTMX partials returned by `verify` views live in `verify/templates/verify/partials/` so the contract (URL → partial fragment) stays inside one app.
- Email templates live in `verify/templates/verify/emails/` (one subject + one body per event type, plain text — readable in any client, no HTML headaches).
- No new tests-discovery configuration needed; the Phase 0 `pytest.ini` already has `testpaths = apps`, which picks up both new apps automatically.

---

## Task 1: Scaffold the `verify` Django app

**Files:**
- Create: `apps/verify/__init__.py`
- Create: `apps/verify/apps.py`
- Create: `apps/verify/models.py`
- Create: `apps/verify/services.py`
- Create: `apps/verify/state_machine.py`
- Create: `apps/verify/tasks.py`
- Create: `apps/verify/emails.py`
- Create: `apps/verify/views.py`
- Create: `apps/verify/urls.py`
- Create: `apps/verify/admin.py`
- Create: `apps/verify/migrations/__init__.py`
- Create: `apps/verify/tests/__init__.py`
- Modify: `interactome/settings/base.py` (add `"verify"` to `INSTALLED_APPS`)
- Modify: `interactome/urls.py` (include `verify.urls`)

- [ ] **Step 1: Create `apps/verify/__init__.py`**

```python
"""verify — biologist review queue, sign-off, notifications.

Spec reference: Section 2 (verify app boundary), Section 7 (sign-off
workflow + five UI screens). All rows in this app are append-only:
state changes are never UPDATEs, every change is a new row carrying
its own timestamp and reviewer FK.
"""
```

- [ ] **Step 2: Create `apps/verify/apps.py`**

```python
"""Django AppConfig for the verify app."""
from __future__ import annotations

from django.apps import AppConfig


class VerifyConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "verify"
    verbose_name = "Verification (reviews, sign-off, notifications)"
```

- [ ] **Step 3: Create empty placeholder modules so imports don't fail**

`apps/verify/models.py`:
```python
"""verify models — Review, Signoff, ReviewAssignment, Subscription, Notification.

All five models inherit from core.TimestampedModel. The Review model is
append-only by convention enforced via services.record_review (no UPDATE
codepath exists in production code).
"""
```

`apps/verify/services.py`:
```python
"""verify services — public API for other apps."""
```

`apps/verify/state_machine.py`:
```python
"""Network pipeline_status transition rules (spec §7)."""
```

`apps/verify/tasks.py`:
```python
"""verify Celery tasks — notification dispatch."""
```

`apps/verify/emails.py`:
```python
"""Email rendering helpers."""
```

`apps/verify/views.py`:
```python
"""verify HTMX endpoints — POST handlers returning fragment HTML."""
```

`apps/verify/urls.py`:
```python
"""verify URL routes — HTMX endpoints only.

The page-level views live in the dashboard app. This module only
exposes the POST-and-swap endpoints that HTMX clicks target.
"""
from __future__ import annotations

from django.urls import path

app_name = "verify"
urlpatterns: list = []
```

`apps/verify/admin.py`:
```python
"""Django admin registration for verify models."""
```

`apps/verify/migrations/__init__.py` and `apps/verify/tests/__init__.py` are empty files.

- [ ] **Step 4: Add `"verify"` to `INSTALLED_APPS` in `interactome/settings/base.py`**

Edit the `INSTALLED_APPS` list — append `"verify"` after the existing local apps line:

```python
INSTALLED_APPS = [
    # ... existing entries unchanged ...
    "core",
    "networks",
    "corpus",
    "papers",
    "extract",
    "graph",
    "sbml",
    "verify",       # <-- ADD
]
```

- [ ] **Step 5: Include `verify.urls` in `interactome/urls.py`**

Edit `interactome/urls.py`. Add the include:

```python
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("verify/", include("verify.urls")),
    path("", include("core.urls")),
]
```

- [ ] **Step 6: Verify Django can boot**

```bash
poetry run python manage.py check
```

Expected output:
```
System check identified no issues (0 silenced).
```

- [ ] **Step 7: Commit**

```bash
git add apps/verify/ interactome/settings/base.py interactome/urls.py
git commit -m "feat(verify): scaffold verify app skeleton"
```

---

## Task 2: `Review` model — append-only audit row (TDD)

The spec (§3, §7) is explicit: "every state change is a new row, never an UPDATE." A reviewer changing their mind = a new `Review` row with the new decision. The previous row stays; the latest row wins. This task implements the model and the append-only invariant.

**Files:**
- Create: `apps/verify/tests/conftest.py`
- Create: `apps/verify/tests/test_models.py`
- Modify: `apps/verify/models.py`

- [ ] **Step 1: Create `apps/verify/tests/conftest.py`**

```python
"""Shared fixtures for the verify test suite."""
from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

User = get_user_model()


@pytest.fixture
def reviewer(db):
    return User.objects.create_user(
        username="fchemorion",
        email="francis.chemorion@upf.edu",
        first_name="Francis",
        last_name="Chemorion",
    )


@pytest.fixture
def other_reviewer(db):
    return User.objects.create_user(
        username="ana_lab",
        email="ana@upf.edu",
        first_name="Ana",
        last_name="L.",
    )


@pytest.fixture
def network(db):
    from networks.models import Network

    return Network.objects.create(
        code="nfkb_axis_mmp_adamts",
        name="NF-kB → MMP/ADAMTS catabolic output",
        category="core_signaling",
        pipeline_status="version_draft",
    )


@pytest.fixture
def entities(db):
    from graph.models import Entity

    e1 = Entity.objects.create(symbol="SIRT1", canonical_uri="https://identifiers.org/uniprot:Q96EB6")
    e2 = Entity.objects.create(symbol="NFKB1", canonical_uri="https://identifiers.org/uniprot:P19838")
    return e1, e2


@pytest.fixture
def edge(db, entities):
    from graph.models import Edge

    src, tgt = entities
    return Edge.objects.create(
        source=src,
        target=tgt,
        relation_type="inhibits",
        belief_score=0.78,
        status="candidate",
    )


@pytest.fixture
def conflict(db, network, edge, entities):
    from graph.models import Edge, Conflict

    src, tgt = entities
    edge_b = Edge.objects.create(
        source=src,
        target=tgt,
        relation_type="activates",
        belief_score=0.55,
        status="candidate",
    )
    return Conflict.objects.create(
        network=network,
        edge_a=edge,
        edge_b=edge_b,
        resolution_status="open",
    )


@pytest.fixture
def model_version(db, network):
    from sbml.models import ModelVersion

    return ModelVersion.objects.create(
        network=network,
        semver="0.3.2",
        s3_key="sbml/nfkb_axis_mmp_adamts/v0.3.2.zip",
        frozen=True,
    )
```

- [ ] **Step 2: Write the failing test in `apps/verify/tests/test_models.py`**

```python
"""Tests for verify.models — Review append-only invariant."""
from __future__ import annotations

import pytest

from verify.models import Review


def test_review_can_be_created_against_an_edge(db, reviewer, edge):
    review = Review.objects.create(
        reviewer=reviewer,
        edge=edge,
        decision="approve",
        comment="Strong evidence in five chunks.",
    )
    assert review.pk is not None
    assert review.decision == "approve"


def test_review_can_be_created_against_a_conflict(db, reviewer, conflict):
    review = Review.objects.create(
        reviewer=reviewer,
        conflict=conflict,
        decision="discuss",
        comment="Context-dependent — needs Ana to weigh in.",
    )
    assert review.pk is not None
    assert review.decision == "discuss"


def test_review_decision_must_be_in_allowed_set(db, reviewer, edge):
    review = Review(
        reviewer=reviewer,
        edge=edge,
        decision="explode",
        comment="",
    )
    with pytest.raises(Exception):
        review.full_clean()


def test_review_requires_either_edge_or_conflict_target(db, reviewer):
    review = Review(reviewer=reviewer, decision="approve", comment="")
    with pytest.raises(Exception):
        review.full_clean()


def test_review_history_is_chronological(db, reviewer, edge):
    Review.objects.create(reviewer=reviewer, edge=edge, decision="discuss", comment="thinking")
    Review.objects.create(reviewer=reviewer, edge=edge, decision="reject", comment="bad evidence")
    Review.objects.create(reviewer=reviewer, edge=edge, decision="approve", comment="re-read")
    history = list(Review.objects.filter(edge=edge).order_by("created_at"))
    assert [r.decision for r in history] == ["discuss", "reject", "approve"]


def test_latest_review_for_edge_wins(db, reviewer, edge):
    Review.objects.create(reviewer=reviewer, edge=edge, decision="approve", comment="")
    Review.objects.create(reviewer=reviewer, edge=edge, decision="reject", comment="changed my mind")
    latest = Review.objects.filter(edge=edge).order_by("-created_at").first()
    assert latest.decision == "reject"


def test_review_never_updates_in_place(db, reviewer, edge):
    """Even if a caller mutates and saves, the data model permits it but
    services.record_review never takes this path. This test documents
    that the *model* doesn't enforce immutability — services do."""
    review = Review.objects.create(reviewer=reviewer, edge=edge, decision="approve", comment="")
    original_created_at = review.created_at
    # Same reviewer changing their mind goes through services, which
    # creates a new row. The model itself remains a plain Django model.
    new_review = Review.objects.create(reviewer=reviewer, edge=edge, decision="reject", comment="")
    assert new_review.created_at >= original_created_at
    assert Review.objects.filter(edge=edge).count() == 2
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
poetry run pytest apps/verify/tests/test_models.py -v
```

Expected:
```
ImportError: cannot import name 'Review' from 'verify.models'
```

- [ ] **Step 4: Implement the `Review` model in `apps/verify/models.py`**

```python
"""verify models — Review, Signoff, ReviewAssignment, Subscription, Notification.

All five models inherit from core.TimestampedModel for created_at /
updated_at columns. The Review model is append-only by convention:
services.record_review is the only public path that creates rows, and
it never UPDATEs an existing row.
"""
from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from core.models import TimestampedModel


class ReviewDecision(models.TextChoices):
    APPROVE = "approve", "Approve"
    REJECT = "reject", "Reject"
    DISCUSS = "discuss", "Needs discussion"
    ABSTAIN = "abstain", "Abstain"


class Review(TimestampedModel):
    """An append-only audit row recording one reviewer's decision at one
    point in time on either a single Edge or a single Conflict.

    Spec §3 / §7: "every state change is a new row, never an UPDATE".
    The latest row (by created_at) for a given (reviewer, edge) or
    (reviewer, conflict) tuple is the current decision.
    """

    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reviews",
    )
    edge = models.ForeignKey(
        "graph.Edge",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="reviews",
    )
    conflict = models.ForeignKey(
        "graph.Conflict",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="reviews",
    )
    decision = models.CharField(
        max_length=16,
        choices=ReviewDecision.choices,
    )
    comment = models.TextField(blank=True, default="")

    class Meta:
        indexes = [
            models.Index(fields=["edge", "-created_at"]),
            models.Index(fields=["conflict", "-created_at"]),
            models.Index(fields=["reviewer", "-created_at"]),
        ]

    def clean(self) -> None:
        if self.edge is None and self.conflict is None:
            raise ValidationError(
                "A Review must target either an Edge or a Conflict."
            )
        if self.edge is not None and self.conflict is not None:
            raise ValidationError(
                "A Review cannot target both an Edge and a Conflict; choose one."
            )

    def __str__(self) -> str:
        target = self.edge or self.conflict
        return f"{self.reviewer.username} {self.decision} {target} @ {self.created_at:%Y-%m-%d %H:%M}"
```

- [ ] **Step 5: Create the migration**

```bash
poetry run python manage.py makemigrations verify
```

Expected output:
```
Migrations for 'verify':
  apps/verify/migrations/0001_initial.py
    + Create model Review
```

- [ ] **Step 6: Run the test to verify it passes**

```bash
poetry run pytest apps/verify/tests/test_models.py -v
```

Expected:
```
7 passed
```

- [ ] **Step 7: Commit**

```bash
git add apps/verify/models.py apps/verify/tests/ apps/verify/migrations/
git commit -m "feat(verify): add append-only Review model"
```

---

## Task 3: `Signoff`, `ReviewAssignment`, `Subscription`, `Notification` models (TDD)

**Files:**
- Modify: `apps/verify/tests/test_models.py` (append new test cases)
- Modify: `apps/verify/models.py` (append four models)

- [ ] **Step 1: Append the failing tests to `apps/verify/tests/test_models.py`**

```python
# --- Signoff -----------------------------------------------------------------

def test_signoff_pins_a_specific_model_version(db, reviewer, network, model_version):
    from verify.models import Signoff

    so = Signoff.objects.create(
        network=network,
        model_version=model_version,
        signed_by=reviewer,
        notes="Verified against PMID 28456123, 32156789.",
    )
    assert so.network == network
    assert so.model_version == model_version
    assert so.signed_by == reviewer


def test_only_one_signoff_per_model_version(db, reviewer, other_reviewer, network, model_version):
    from verify.models import Signoff

    Signoff.objects.create(network=network, model_version=model_version, signed_by=reviewer)
    with pytest.raises(Exception):
        Signoff.objects.create(network=network, model_version=model_version, signed_by=other_reviewer)


# --- ReviewAssignment --------------------------------------------------------

def test_review_assignment_links_reviewer_to_network(db, reviewer, network):
    from verify.models import ReviewAssignment

    ra = ReviewAssignment.objects.create(reviewer=reviewer, network=network, role="curator")
    assert ra.role == "curator"


def test_review_assignment_role_in_allowed_set(db, reviewer, network):
    from verify.models import ReviewAssignment

    ra = ReviewAssignment(reviewer=reviewer, network=network, role="emperor")
    with pytest.raises(Exception):
        ra.full_clean()


# --- Subscription ------------------------------------------------------------

def test_user_can_subscribe_to_network(db, reviewer, network):
    from verify.models import Subscription

    sub = Subscription.objects.create(user=reviewer, network=network)
    assert sub.user == reviewer
    assert sub.network == network


def test_user_can_subscribe_to_category(db, reviewer):
    from verify.models import Subscription

    sub = Subscription.objects.create(user=reviewer, category="core_signaling")
    assert sub.category == "core_signaling"
    assert sub.network is None


def test_subscription_requires_network_or_category(db, reviewer):
    from verify.models import Subscription

    sub = Subscription(user=reviewer)
    with pytest.raises(Exception):
        sub.full_clean()


# --- Notification ------------------------------------------------------------

def test_notification_starts_unread(db, reviewer, network):
    from verify.models import Notification

    n = Notification.objects.create(
        user=reviewer,
        network=network,
        event_type="network_stale",
        message="NF-kB axis has 12 new disagreements.",
    )
    assert n.read_at is None
    assert not n.is_read


def test_notification_mark_read(db, reviewer, network):
    from verify.models import Notification

    n = Notification.objects.create(
        user=reviewer,
        network=network,
        event_type="network_signed_off",
        message="Wnt/beta-catenin signed off as v1.2.0",
    )
    n.mark_read()
    n.refresh_from_db()
    assert n.is_read
    assert n.read_at is not None
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
poetry run pytest apps/verify/tests/test_models.py -v
```

Expected:
```
ImportError: cannot import name 'Signoff' from 'verify.models'
```

- [ ] **Step 3: Append the four new models to `apps/verify/models.py`**

```python
from django.utils import timezone


class Signoff(TimestampedModel):
    """A curator pinning a specific ModelVersion as the verified release
    for one network. One per (network, model_version) pair.

    Spec §7 sign-off state machine: a Signoff promotes the network from
    version_draft -> verified and triggers sbml.regenerate with a MAJOR
    semver bump."""

    network = models.ForeignKey(
        "networks.Network",
        on_delete=models.PROTECT,
        related_name="signoffs",
    )
    model_version = models.OneToOneField(
        "sbml.ModelVersion",
        on_delete=models.PROTECT,
        related_name="signoff",
    )
    signed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="signoffs",
    )
    notes = models.TextField(blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["model_version"],
                name="verify_signoff_unique_per_version",
            ),
        ]

    def __str__(self) -> str:
        return f"Signoff {self.network.code} v{self.model_version.semver} by {self.signed_by.username}"


class ReviewerRole(models.TextChoices):
    CURATOR = "curator", "Curator"
    REVIEWER = "reviewer", "Reviewer"
    OBSERVER = "observer", "Observer"


class ReviewAssignment(TimestampedModel):
    """Assigns a reviewer to a network with a role.

    Curators can sign off; reviewers can record per-edge decisions but
    cannot sign off; observers see notifications only."""

    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="review_assignments",
    )
    network = models.ForeignKey(
        "networks.Network",
        on_delete=models.CASCADE,
        related_name="review_assignments",
    )
    role = models.CharField(
        max_length=16,
        choices=ReviewerRole.choices,
        default=ReviewerRole.REVIEWER,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["reviewer", "network"],
                name="verify_reviewassignment_unique",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.reviewer.username} as {self.role} on {self.network.code}"


class Subscription(TimestampedModel):
    """A user subscribes to a network or a whole category for email +
    in-app notifications on state changes."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="subscriptions",
    )
    network = models.ForeignKey(
        "networks.Network",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="subscriptions",
    )
    category = models.CharField(max_length=64, blank=True, default="")
    email_enabled = models.BooleanField(default=True)
    inapp_enabled = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "network"],
                condition=models.Q(network__isnull=False),
                name="verify_subscription_unique_user_network",
            ),
            models.UniqueConstraint(
                fields=["user", "category"],
                condition=~models.Q(category=""),
                name="verify_subscription_unique_user_category",
            ),
        ]

    def clean(self) -> None:
        if self.network is None and not self.category:
            raise ValidationError(
                "A Subscription must target either a network or a category."
            )


class NotificationEvent(models.TextChoices):
    NETWORK_STALE = "network_stale", "Network became stale"
    NETWORK_DISAGREEMENTS = "network_disagreements", "New disagreements on network"
    NETWORK_SIGNED_OFF = "network_signed_off", "Network was signed off"
    NEW_VERSION = "new_version", "New version published"


class Notification(TimestampedModel):
    """In-app notification row. Email is sent in addition via
    verify.tasks.notify; this row drives the nav-bar dropdown."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    network = models.ForeignKey(
        "networks.Network",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="notifications",
    )
    event_type = models.CharField(max_length=32, choices=NotificationEvent.choices)
    message = models.TextField()
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["user", "read_at"]),
        ]

    @property
    def is_read(self) -> bool:
        return self.read_at is not None

    def mark_read(self) -> None:
        if self.read_at is None:
            self.read_at = timezone.now()
            self.save(update_fields=["read_at", "updated_at"])
```

- [ ] **Step 4: Generate and run the migration**

```bash
poetry run python manage.py makemigrations verify
poetry run python manage.py migrate
```

- [ ] **Step 5: Run the full verify test suite**

```bash
poetry run pytest apps/verify/tests/test_models.py -v
```

Expected: all tests pass (the original 7 from Task 2 plus the 11 new ones = 18 passed).

- [ ] **Step 6: Register all five models in `apps/verify/admin.py`**

```python
"""Django admin registration for verify models."""
from __future__ import annotations

from django.contrib import admin

from verify.models import (
    Notification,
    Review,
    ReviewAssignment,
    Signoff,
    Subscription,
)


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ("reviewer", "edge", "conflict", "decision", "created_at")
    list_filter = ("decision",)
    search_fields = ("reviewer__username", "comment")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Signoff)
class SignoffAdmin(admin.ModelAdmin):
    list_display = ("network", "model_version", "signed_by", "created_at")
    list_filter = ("network__category",)


@admin.register(ReviewAssignment)
class ReviewAssignmentAdmin(admin.ModelAdmin):
    list_display = ("reviewer", "network", "role")
    list_filter = ("role",)


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("user", "network", "category", "email_enabled", "inapp_enabled")


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("user", "event_type", "network", "read_at", "created_at")
    list_filter = ("event_type",)
```

- [ ] **Step 7: Commit**

```bash
git add apps/verify/models.py apps/verify/admin.py apps/verify/tests/test_models.py apps/verify/migrations/
git commit -m "feat(verify): add Signoff, ReviewAssignment, Subscription, Notification"
```

---

## Task 4: Network status state machine (TDD)

The spec (§7) defines five network statuses with strict transitions:

```
IDLE --new corpus--> STALE --regenerate--> VERSION_DRAFT --signoff--> VERIFIED --new evidence--> STALE
```

Plus an in-flight `REFRESHING` while the integration tasks are running. We encode this as a pure-Python state machine with no side effects — the side effects (saving the network, firing notifications, calling `sbml.regenerate`) live in `services.py`.

**Files:**
- Create: `apps/verify/tests/test_state_machine.py`
- Modify: `apps/verify/state_machine.py`

- [ ] **Step 1: Write the failing test in `apps/verify/tests/test_state_machine.py`**

```python
"""Tests for verify.state_machine — pure transition rules."""
from __future__ import annotations

import pytest

from verify.state_machine import (
    NetworkStatus,
    InvalidTransition,
    transition,
)


def test_idle_to_stale_on_new_corpus():
    assert transition(NetworkStatus.IDLE, "new_corpus") == NetworkStatus.STALE


def test_stale_to_refreshing_on_integration_start():
    assert transition(NetworkStatus.STALE, "integration_start") == NetworkStatus.REFRESHING


def test_refreshing_to_version_draft_on_regenerate_done():
    assert (
        transition(NetworkStatus.REFRESHING, "regenerate_done")
        == NetworkStatus.VERSION_DRAFT
    )


def test_version_draft_to_verified_on_signoff():
    assert (
        transition(NetworkStatus.VERSION_DRAFT, "signoff")
        == NetworkStatus.VERIFIED
    )


def test_verified_to_stale_on_new_evidence():
    assert (
        transition(NetworkStatus.VERIFIED, "new_corpus")
        == NetworkStatus.STALE
    )


def test_cannot_signoff_from_idle():
    with pytest.raises(InvalidTransition):
        transition(NetworkStatus.IDLE, "signoff")


def test_cannot_signoff_from_stale():
    with pytest.raises(InvalidTransition):
        transition(NetworkStatus.STALE, "signoff")


def test_unknown_event_raises():
    with pytest.raises(InvalidTransition):
        transition(NetworkStatus.VERSION_DRAFT, "magic_event")


def test_all_statuses_present_in_enum():
    """Spec §7 lists five states; the enum must match exactly."""
    expected = {"idle", "refreshing", "stale", "version_draft", "verified"}
    assert {s.value for s in NetworkStatus} == expected
```

- [ ] **Step 2: Run to verify it fails**

```bash
poetry run pytest apps/verify/tests/test_state_machine.py -v
```

Expected: `ImportError: cannot import name 'NetworkStatus' from 'verify.state_machine'`.

- [ ] **Step 3: Implement the state machine in `apps/verify/state_machine.py`**

```python
"""Network pipeline_status transition rules (spec section 7).

Pure-function state machine. Inputs: current status + event name.
Output: new status, or InvalidTransition. No I/O, no side effects.
The services layer is responsible for persistence and notifications.
"""
from __future__ import annotations

from enum import Enum


class NetworkStatus(str, Enum):
    IDLE = "idle"
    REFRESHING = "refreshing"
    STALE = "stale"
    VERSION_DRAFT = "version_draft"
    VERIFIED = "verified"


class InvalidTransition(Exception):
    """Raised when an event is not legal for the current status."""


# Adjacency map: {current_status: {event: next_status}}
_TRANSITIONS: dict[NetworkStatus, dict[str, NetworkStatus]] = {
    NetworkStatus.IDLE: {
        "new_corpus": NetworkStatus.STALE,
    },
    NetworkStatus.STALE: {
        "integration_start": NetworkStatus.REFRESHING,
        "new_corpus": NetworkStatus.STALE,   # idempotent
    },
    NetworkStatus.REFRESHING: {
        "regenerate_done": NetworkStatus.VERSION_DRAFT,
        "integration_failed": NetworkStatus.STALE,
    },
    NetworkStatus.VERSION_DRAFT: {
        "signoff": NetworkStatus.VERIFIED,
        "new_corpus": NetworkStatus.STALE,
    },
    NetworkStatus.VERIFIED: {
        "new_corpus": NetworkStatus.STALE,
    },
}


def transition(current: NetworkStatus, event: str) -> NetworkStatus:
    """Return the next status for the given event, or raise.

    Idempotent re-fires (e.g. new_corpus while already STALE) are allowed
    because the corpus-refresh task fires once per ingested paper.
    """
    if not isinstance(current, NetworkStatus):
        current = NetworkStatus(current)
    try:
        return _TRANSITIONS[current][event]
    except KeyError as exc:
        raise InvalidTransition(
            f"No transition from {current.value!r} on event {event!r}"
        ) from exc
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
poetry run pytest apps/verify/tests/test_state_machine.py -v
```

Expected:
```
9 passed
```

- [ ] **Step 5: Commit**

```bash
git add apps/verify/state_machine.py apps/verify/tests/test_state_machine.py
git commit -m "feat(verify): add network status state machine"
```

---

## Task 5: `verify.services` — the public Python API (TDD)

This is the only module other apps call into. It enforces the append-only invariant for `Review`, drives the state machine on sign-off, schedules notifications via `verify.tasks.notify`, and exposes idempotent `record_review`, `sign_off`, `mark_stale`, `subscribe`, `unsubscribe`.

**Files:**
- Create: `apps/verify/tests/test_services.py`
- Modify: `apps/verify/services.py`

- [ ] **Step 1: Write the failing test in `apps/verify/tests/test_services.py`**

```python
"""Tests for verify.services — the public API of the verify app."""
from __future__ import annotations

import pytest

from verify import services
from verify.models import Notification, Review, Signoff, Subscription
from verify.state_machine import NetworkStatus, InvalidTransition


# --- record_review -----------------------------------------------------------

def test_record_review_creates_a_review_row(db, reviewer, edge):
    services.record_review(
        reviewer=reviewer,
        target=edge,
        decision="approve",
        comment="strong evidence",
    )
    assert Review.objects.filter(edge=edge).count() == 1


def test_record_review_appends_rather_than_updates(db, reviewer, edge):
    services.record_review(reviewer=reviewer, target=edge, decision="approve", comment="")
    services.record_review(reviewer=reviewer, target=edge, decision="reject", comment="changed mind")
    assert Review.objects.filter(edge=edge).count() == 2


def test_record_review_promotes_edge_status_on_approve(db, reviewer, edge):
    services.record_review(reviewer=reviewer, target=edge, decision="approve", comment="")
    edge.refresh_from_db()
    assert edge.status == "accepted"


def test_record_review_demotes_edge_status_on_reject(db, reviewer, edge):
    services.record_review(reviewer=reviewer, target=edge, decision="reject", comment="")
    edge.refresh_from_db()
    assert edge.status == "rejected"


def test_record_review_on_conflict_keeps_a(db, reviewer, conflict):
    services.record_review(
        reviewer=reviewer,
        target=conflict,
        decision="approve",      # "approve" on a conflict = keep edge_a
        comment="keep INHIBIT",
    )
    conflict.refresh_from_db()
    assert conflict.resolution_status == "resolved_a"


def test_record_review_on_conflict_keeps_b(db, reviewer, conflict):
    services.record_review(
        reviewer=reviewer,
        target=conflict,
        decision="reject",       # "reject" of edge_a = keep edge_b
        comment="keep ACTIVATE",
    )
    conflict.refresh_from_db()
    assert conflict.resolution_status == "resolved_b"


# --- sign_off ----------------------------------------------------------------

def test_sign_off_creates_signoff_row(db, reviewer, network, model_version):
    services.sign_off(curator=reviewer, network=network, model_version=model_version, notes="ok")
    assert Signoff.objects.filter(network=network).exists()


def test_sign_off_transitions_network_to_verified(db, reviewer, network, model_version):
    network.pipeline_status = NetworkStatus.VERSION_DRAFT.value
    network.save()
    services.sign_off(curator=reviewer, network=network, model_version=model_version, notes="")
    network.refresh_from_db()
    assert network.pipeline_status == NetworkStatus.VERIFIED.value


def test_sign_off_from_idle_is_invalid(db, reviewer, network, model_version):
    network.pipeline_status = NetworkStatus.IDLE.value
    network.save()
    with pytest.raises(InvalidTransition):
        services.sign_off(curator=reviewer, network=network, model_version=model_version, notes="")


def test_sign_off_calls_sbml_regenerate_for_major_bump(
    db, reviewer, network, model_version, mocker
):
    network.pipeline_status = NetworkStatus.VERSION_DRAFT.value
    network.save()
    mock_regen = mocker.patch("sbml.services.regenerate")
    services.sign_off(curator=reviewer, network=network, model_version=model_version, notes="")
    mock_regen.assert_called_once_with(network_id=network.id, bump="major")


# --- mark_stale --------------------------------------------------------------

def test_mark_stale_from_verified(db, network):
    network.pipeline_status = NetworkStatus.VERIFIED.value
    network.save()
    services.mark_stale(network=network, reason="new evidence in PMID 99999999")
    network.refresh_from_db()
    assert network.pipeline_status == NetworkStatus.STALE.value


def test_mark_stale_is_idempotent(db, network):
    network.pipeline_status = NetworkStatus.STALE.value
    network.save()
    services.mark_stale(network=network, reason="more new evidence")
    network.refresh_from_db()
    assert network.pipeline_status == NetworkStatus.STALE.value


# --- subscriptions -----------------------------------------------------------

def test_subscribe_to_network(db, reviewer, network):
    services.subscribe(user=reviewer, network=network)
    assert Subscription.objects.filter(user=reviewer, network=network).exists()


def test_subscribe_is_idempotent(db, reviewer, network):
    services.subscribe(user=reviewer, network=network)
    services.subscribe(user=reviewer, network=network)
    assert Subscription.objects.filter(user=reviewer, network=network).count() == 1


def test_unsubscribe_removes_subscription(db, reviewer, network):
    services.subscribe(user=reviewer, network=network)
    services.unsubscribe(user=reviewer, network=network)
    assert not Subscription.objects.filter(user=reviewer, network=network).exists()


# --- notify ------------------------------------------------------------------

def test_notify_creates_inapp_notification(db, reviewer, network):
    services.subscribe(user=reviewer, network=network)
    services.notify(network=network, event_type="network_stale", message="12 new disagreements")
    assert Notification.objects.filter(user=reviewer, network=network).exists()


def test_notify_respects_inapp_disabled(db, reviewer, network):
    sub = Subscription.objects.create(user=reviewer, network=network, inapp_enabled=False)
    services.notify(network=network, event_type="network_stale", message="x")
    assert not Notification.objects.filter(user=reviewer).exists()


def test_notify_sends_email_when_enabled(db, reviewer, network, mailoutbox):
    services.subscribe(user=reviewer, network=network)
    services.notify(network=network, event_type="network_signed_off", message="signed off as v1.0.0")
    assert len(mailoutbox) == 1
    assert reviewer.email in mailoutbox[0].to


def test_notify_category_subscribers(db, reviewer, network):
    Subscription.objects.create(user=reviewer, category="core_signaling")
    services.notify(network=network, event_type="new_version", message="v0.3.3 published")
    assert Notification.objects.filter(user=reviewer).exists()
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
poetry run pytest apps/verify/tests/test_services.py -v
```

Expected: a stack of `AttributeError: module 'verify.services' has no attribute 'record_review'`.

- [ ] **Step 3: Implement `apps/verify/services.py`**

```python
"""verify services — public API for other apps.

Conventions:
- Every function is idempotent where it makes sense (subscribe, mark_stale).
- record_review never UPDATEs an existing Review row; the latest row wins.
- All cross-app calls go through OTHER apps' services modules
  (sbml.services.regenerate), never their models or tasks directly.
"""
from __future__ import annotations

from typing import Optional

from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string

from graph.models import Conflict, Edge
from networks.models import Network
from sbml.models import ModelVersion
from verify.models import (
    Notification,
    Review,
    ReviewDecision,
    Signoff,
    Subscription,
)
from verify.state_machine import InvalidTransition, NetworkStatus, transition

User = get_user_model()


# --- Reviews -----------------------------------------------------------------

@transaction.atomic
def record_review(
    *,
    reviewer,
    target,
    decision: str,
    comment: str = "",
) -> Review:
    """Append a Review row. Promotes Edge/Conflict downstream state.

    Decision semantics:
      - target is Edge:
          approve  -> edge.status = "accepted"
          reject   -> edge.status = "rejected"
          discuss  -> edge.status stays "candidate"
          abstain  -> edge.status stays "candidate"
      - target is Conflict:
          approve  -> keep edge_a (resolution_status = "resolved_a")
          reject   -> keep edge_b (resolution_status = "resolved_b")
          discuss  -> resolution_status = "context_dependent"
          abstain  -> resolution_status stays "open"
    """
    if decision not in ReviewDecision.values:
        raise ValueError(f"Unknown decision: {decision!r}")

    if isinstance(target, Edge):
        review = Review.objects.create(
            reviewer=reviewer, edge=target, decision=decision, comment=comment
        )
        if decision == ReviewDecision.APPROVE:
            target.status = "accepted"
            target.save(update_fields=["status", "updated_at"])
        elif decision == ReviewDecision.REJECT:
            target.status = "rejected"
            target.save(update_fields=["status", "updated_at"])
        return review

    if isinstance(target, Conflict):
        review = Review.objects.create(
            reviewer=reviewer, conflict=target, decision=decision, comment=comment
        )
        new_status = {
            ReviewDecision.APPROVE: "resolved_a",
            ReviewDecision.REJECT: "resolved_b",
            ReviewDecision.DISCUSS: "context_dependent",
            ReviewDecision.ABSTAIN: "open",
        }[decision]
        target.resolution_status = new_status
        target.save(update_fields=["resolution_status", "updated_at"])
        return review

    raise TypeError(f"Review target must be an Edge or Conflict, got {type(target)!r}")


# --- Sign-off ----------------------------------------------------------------

@transaction.atomic
def sign_off(
    *,
    curator,
    network: Network,
    model_version: ModelVersion,
    notes: str = "",
) -> Signoff:
    """Pin a ModelVersion as the verified release. Transitions the network
    to VERIFIED, fires sbml.regenerate(bump='major'), notifies subscribers."""
    new_status = transition(NetworkStatus(network.pipeline_status), "signoff")

    signoff = Signoff.objects.create(
        network=network,
        model_version=model_version,
        signed_by=curator,
        notes=notes,
    )

    network.pipeline_status = new_status.value
    network.save(update_fields=["pipeline_status", "updated_at"])

    # Defer the import to break a circular reference; sbml.services may
    # transitively re-import verify.
    from sbml import services as sbml_services
    sbml_services.regenerate(network_id=network.id, bump="major")

    notify(
        network=network,
        event_type="network_signed_off",
        message=f"{network.name} signed off as v{model_version.semver} by {curator.username}.",
    )
    return signoff


# --- Stale-marking -----------------------------------------------------------

@transaction.atomic
def mark_stale(*, network: Network, reason: str) -> None:
    """Idempotently transition a network to STALE on new evidence."""
    current = NetworkStatus(network.pipeline_status)
    if current == NetworkStatus.STALE:
        return  # idempotent no-op

    try:
        new_status = transition(current, "new_corpus")
    except InvalidTransition:
        return  # REFRESHING in progress — leave alone

    network.pipeline_status = new_status.value
    network.save(update_fields=["pipeline_status", "updated_at"])

    notify(
        network=network,
        event_type="network_stale",
        message=f"{network.name} is now stale: {reason}",
    )


# --- Subscriptions -----------------------------------------------------------

def subscribe(*, user, network: Optional[Network] = None, category: str = "") -> Subscription:
    if network is None and not category:
        raise ValueError("subscribe() requires network or category")
    sub, _ = Subscription.objects.get_or_create(
        user=user, network=network, category=category,
    )
    return sub


def unsubscribe(*, user, network: Optional[Network] = None, category: str = "") -> None:
    Subscription.objects.filter(
        user=user, network=network, category=category,
    ).delete()


# --- Notifications -----------------------------------------------------------

def notify(*, network: Network, event_type: str, message: str) -> None:
    """Fan out a notification to every subscriber of this network or its
    category. Creates one Notification row per (subscriber, channel) and
    sends one email per subscriber with email_enabled=True.

    Sync wrapper around the verify.tasks.notify Celery task: in tests
    we run it inline (CELERY_TASK_ALWAYS_EAGER=True), in production
    it's deferred to the worker_io queue.
    """
    subs = (
        Subscription.objects.filter(network=network)
        | Subscription.objects.filter(category=network.category)
    ).select_related("user").distinct()

    for sub in subs:
        if sub.inapp_enabled:
            Notification.objects.create(
                user=sub.user,
                network=network,
                event_type=event_type,
                message=message,
            )
        if sub.email_enabled and sub.user.email:
            subject = render_to_string(
                f"verify/emails/{event_type.replace('network_', '')}_subject.txt"
                if event_type.startswith("network_")
                else f"verify/emails/{event_type}_subject.txt",
                {"network": network},
            ).strip()
            body = render_to_string(
                f"verify/emails/{event_type.replace('network_', '')}_body.txt"
                if event_type.startswith("network_")
                else f"verify/emails/{event_type}_body.txt",
                {"network": network, "message": message, "user": sub.user},
            )
            send_mail(
                subject=subject,
                message=body,
                from_email=None,    # use DEFAULT_FROM_EMAIL
                recipient_list=[sub.user.email],
                fail_silently=False,
            )
```

- [ ] **Step 4: Create the email template files**

`apps/verify/templates/verify/emails/stale_subject.txt`:
```
[IVD Atlas] {{ network.name }} has new disagreements
```

`apps/verify/templates/verify/emails/stale_body.txt`:
```
Hello {{ user.first_name|default:user.username }},

{{ message }}

Review the disagreements at:
  https://interactome.simbiosys.sb.upf.edu/networks/{{ network.code }}/disagreements/

-- IVD Regulatory Network Atlas
```

`apps/verify/templates/verify/emails/disagreements_subject.txt`:
```
[IVD Atlas] {{ network.name }} has new disagreements
```

`apps/verify/templates/verify/emails/disagreements_body.txt`:
```
Hello {{ user.first_name|default:user.username }},

{{ message }}

Review the disagreements at:
  https://interactome.simbiosys.sb.upf.edu/networks/{{ network.code }}/disagreements/

-- IVD Regulatory Network Atlas
```

`apps/verify/templates/verify/emails/signed_off_subject.txt`:
```
[IVD Atlas] {{ network.name }} has been signed off
```

`apps/verify/templates/verify/emails/signed_off_body.txt`:
```
Hello {{ user.first_name|default:user.username }},

{{ message }}

The verified version is now downloadable at:
  https://interactome.simbiosys.sb.upf.edu/networks/{{ network.code }}/

-- IVD Regulatory Network Atlas
```

`apps/verify/templates/verify/emails/new_version_subject.txt`:
```
[IVD Atlas] New version of {{ network.name }}
```

`apps/verify/templates/verify/emails/new_version_body.txt`:
```
Hello {{ user.first_name|default:user.username }},

{{ message }}

View it at:
  https://interactome.simbiosys.sb.upf.edu/networks/{{ network.code }}/

-- IVD Regulatory Network Atlas
```

- [ ] **Step 5: Run the service test suite**

```bash
poetry run pytest apps/verify/tests/test_services.py -v
```

Expected: `19 passed`. If any fail because of import order issues, check that `sbml.services.regenerate` exists from Phase 4. If not, this plan assumes it exists; create a stub in `sbml/services.py`:
```python
def regenerate(*, network_id: int, bump: str = "patch") -> None:
    """Phase 4 owns the real implementation."""
    pass
```

- [ ] **Step 6: Commit**

```bash
git add apps/verify/services.py apps/verify/templates/ apps/verify/tests/test_services.py
git commit -m "feat(verify): add services API for review, signoff, notify"
```

---

## Task 6: `verify.tasks.notify` Celery task + `dispatch_review_assignments` Beat task (TDD)

Per spec §6 Beat schedule, `verify.dispatch_review_assignments` runs hourly to ensure every reviewer has been notified about their open queue.

**Files:**
- Create: `apps/verify/tests/test_tasks.py`
- Modify: `apps/verify/tasks.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for verify.tasks."""
from __future__ import annotations

import pytest

from verify import services
from verify.models import Notification, ReviewAssignment


def test_notify_task_runs_eagerly(db, settings, reviewer, network):
    from verify.tasks import notify as notify_task

    settings.CELERY_TASK_ALWAYS_EAGER = True
    services.subscribe(user=reviewer, network=network)
    notify_task.delay(network_id=network.id, event_type="network_stale", message="hello")
    assert Notification.objects.filter(user=reviewer).exists()


def test_dispatch_review_assignments_sends_one_per_curator(db, settings, reviewer, network, mocker):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    network.pipeline_status = "version_draft"
    network.save()
    ReviewAssignment.objects.create(reviewer=reviewer, network=network, role="curator")

    from verify.tasks import dispatch_review_assignments

    spy = mocker.spy(services, "notify")
    dispatch_review_assignments.delay()
    assert spy.call_count >= 1


def test_dispatch_skips_idle_networks(db, settings, reviewer, network, mocker):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    network.pipeline_status = "idle"
    network.save()
    ReviewAssignment.objects.create(reviewer=reviewer, network=network, role="curator")
    spy = mocker.spy(services, "notify")
    from verify.tasks import dispatch_review_assignments
    dispatch_review_assignments.delay()
    assert spy.call_count == 0
```

- [ ] **Step 2: Run to verify it fails**

```bash
poetry run pytest apps/verify/tests/test_tasks.py -v
```

Expected: `ImportError: cannot import name 'notify' from 'verify.tasks'`.

- [ ] **Step 3: Implement `apps/verify/tasks.py`**

```python
"""verify Celery tasks — notification dispatch."""
from __future__ import annotations

from celery import shared_task

from networks.models import Network
from verify import services
from verify.models import ReviewAssignment


@shared_task(name="verify.notify", queue="q.io")
def notify(*, network_id: int, event_type: str, message: str) -> None:
    """Async wrapper around verify.services.notify for queue routing."""
    network = Network.objects.get(id=network_id)
    services.notify(network=network, event_type=event_type, message=message)


@shared_task(name="verify.dispatch_review_assignments", queue="q.io")
def dispatch_review_assignments() -> int:
    """Hourly: notify every curator about their open draft networks.

    Spec section 6 Beat schedule: every 1 hour. Skips IDLE networks
    (nothing to review). Returns the number of notifications fired.
    """
    drafts = Network.objects.filter(
        pipeline_status__in=["version_draft", "stale"]
    )
    count = 0
    for network in drafts:
        curators = ReviewAssignment.objects.filter(
            network=network, role="curator"
        ).select_related("reviewer")
        for ra in curators:
            services.notify(
                network=network,
                event_type="network_disagreements"
                if network.pipeline_status == "stale"
                else "new_version",
                message=(
                    f"Reminder: {network.name} is awaiting your review "
                    f"(status: {network.pipeline_status})."
                ),
            )
            count += 1
    return count
```

- [ ] **Step 4: Add the Beat schedule entry**

Edit `interactome/settings/base.py` and append to the `CELERY_BEAT_SCHEDULE` dict (creating it if it doesn't exist):

```python
CELERY_BEAT_SCHEDULE = {
    # ... entries from previous phases ...
    "verify.dispatch_review_assignments": {
        "task": "verify.dispatch_review_assignments",
        "schedule": 60.0 * 60.0,   # every 1 hour
    },
}
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
poetry run pytest apps/verify/tests/test_tasks.py -v
```

Expected:
```
3 passed
```

- [ ] **Step 6: Commit**

```bash
git add apps/verify/tasks.py interactome/settings/base.py apps/verify/tests/test_tasks.py
git commit -m "feat(verify): add notify and dispatch_review_assignments tasks"
```

---

## Task 7: Email rendering helpers + dev/production backends (TDD)

**Files:**
- Create: `apps/verify/tests/test_emails.py`
- Modify: `apps/verify/emails.py`
- Modify: `interactome/settings/base.py` (email defaults)
- Modify: `interactome/settings/production.py` (SMTP env vars)

- [ ] **Step 1: Write the failing test**

```python
"""Tests for verify.emails — rendering + SMTP integration."""
from __future__ import annotations

import pytest

from verify.emails import render_event_email


def test_render_stale_email_subject(network):
    subject, body = render_event_email(
        event_type="network_stale",
        network=network,
        message="12 new disagreements",
        user=None,
    )
    assert network.name in subject
    assert "disagreement" in body.lower()


def test_render_signed_off_email_subject(network):
    subject, body = render_event_email(
        event_type="network_signed_off",
        network=network,
        message="signed off as v1.0.0",
        user=None,
    )
    assert "signed off" in subject.lower()


def test_render_new_version_email(network):
    subject, body = render_event_email(
        event_type="new_version",
        network=network,
        message="v0.3.3 published",
        user=None,
    )
    assert "new version" in subject.lower() or "New version" in subject
```

- [ ] **Step 2: Run to verify it fails**

```bash
poetry run pytest apps/verify/tests/test_emails.py -v
```

Expected: `ImportError: cannot import name 'render_event_email' from 'verify.emails'`.

- [ ] **Step 3: Implement `apps/verify/emails.py`**

```python
"""Email rendering helpers.

Centralises the template-name -> (subject, body) mapping so that
services.notify can call one function instead of repeating render_to_string.
"""
from __future__ import annotations

from typing import Optional

from django.template.loader import render_to_string


_SUBJECT_TEMPLATES = {
    "network_stale": "verify/emails/stale_subject.txt",
    "network_disagreements": "verify/emails/disagreements_subject.txt",
    "network_signed_off": "verify/emails/signed_off_subject.txt",
    "new_version": "verify/emails/new_version_subject.txt",
}

_BODY_TEMPLATES = {
    "network_stale": "verify/emails/stale_body.txt",
    "network_disagreements": "verify/emails/disagreements_body.txt",
    "network_signed_off": "verify/emails/signed_off_body.txt",
    "new_version": "verify/emails/new_version_body.txt",
}


def render_event_email(
    *,
    event_type: str,
    network,
    message: str,
    user: Optional[object],
) -> tuple[str, str]:
    """Return (subject, body) for an event."""
    if event_type not in _SUBJECT_TEMPLATES:
        raise ValueError(f"Unknown event_type: {event_type!r}")
    ctx = {"network": network, "message": message, "user": user}
    subject = render_to_string(_SUBJECT_TEMPLATES[event_type], ctx).strip()
    body = render_to_string(_BODY_TEMPLATES[event_type], ctx)
    return subject, body
```

- [ ] **Step 4: Refactor `services.notify` to use the helper**

Edit `apps/verify/services.py` and replace the inline `render_to_string` block inside `notify()` with:

```python
        if sub.email_enabled and sub.user.email:
            from verify.emails import render_event_email
            subject, body = render_event_email(
                event_type=event_type,
                network=network,
                message=message,
                user=sub.user,
            )
            send_mail(
                subject=subject,
                message=body,
                from_email=None,
                recipient_list=[sub.user.email],
                fail_silently=False,
            )
```

- [ ] **Step 5: Add email backend defaults**

In `interactome/settings/base.py`, append:

```python
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = os.environ.get(
    "DJANGO_DEFAULT_FROM_EMAIL",
    "no-reply@interactome.simbiosys.sb.upf.edu",
)
```

In `interactome/settings/production.py`, append:

```python
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.environ.get("EMAIL_HOST", "smtp.upf.edu")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "true").lower() == "true"
```

Add the four new env vars to `.env.example` (append):

```bash
# === Email (SMTP) ===
DJANGO_DEFAULT_FROM_EMAIL=no-reply@interactome.simbiosys.sb.upf.edu
EMAIL_HOST=smtp.upf.edu
EMAIL_PORT=587
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
EMAIL_USE_TLS=true
```

- [ ] **Step 6: Run the test to verify it passes**

```bash
poetry run pytest apps/verify/tests/test_emails.py apps/verify/tests/test_services.py -v
```

Expected: all tests still pass.

- [ ] **Step 7: Commit**

```bash
git add apps/verify/emails.py apps/verify/services.py apps/verify/tests/test_emails.py interactome/settings/ .env.example
git commit -m "feat(verify): add email rendering helpers and SMTP backend config"
```

---

## Task 8: Scaffold the `dashboard` Django app

**Files:**
- Create: `apps/dashboard/__init__.py`
- Create: `apps/dashboard/apps.py`
- Create: `apps/dashboard/views.py`
- Create: `apps/dashboard/urls.py`
- Create: `apps/dashboard/context_processors.py`
- Create: `apps/dashboard/templatetags/__init__.py`
- Create: `apps/dashboard/templatetags/dashboard_extras.py`
- Create: `apps/dashboard/migrations/__init__.py`
- Create: `apps/dashboard/tests/__init__.py`
- Create: `apps/dashboard/templates/base.html`
- Modify: `interactome/settings/base.py` (add `"dashboard"`, context processor)
- Modify: `interactome/urls.py`

- [ ] **Step 1: Create `apps/dashboard/__init__.py`**

```python
"""dashboard — read-only views and templates over every other app.

Spec section 2: dashboard depends on everything else, owns no models.
Spec section 7: this app renders the five UI screens.
"""
```

- [ ] **Step 2: Create `apps/dashboard/apps.py`**

```python
"""Django AppConfig for the dashboard app."""
from __future__ import annotations

from django.apps import AppConfig


class DashboardConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "dashboard"
    verbose_name = "Dashboard (UI)"
```

- [ ] **Step 3: Create empty placeholder modules**

`apps/dashboard/views.py`:
```python
"""dashboard views — page-level controllers."""
```

`apps/dashboard/urls.py`:
```python
"""dashboard URL routes."""
from __future__ import annotations

from django.urls import path

app_name = "dashboard"
urlpatterns: list = []
```

`apps/dashboard/context_processors.py`:
```python
"""dashboard context processors — injected into every template."""
from __future__ import annotations

from django.http import HttpRequest


def unread_notifications_count(request: HttpRequest) -> dict:
    if not request.user.is_authenticated:
        return {"unread_notifications_count": 0}
    from verify.models import Notification

    count = Notification.objects.filter(user=request.user, read_at__isnull=True).count()
    return {"unread_notifications_count": count}
```

`apps/dashboard/templatetags/__init__.py` is empty.

`apps/dashboard/templatetags/dashboard_extras.py`:
```python
"""Custom template tags + filters for dashboard rendering."""
from __future__ import annotations

from django import template

register = template.Library()


_STATUS_PILL_CLASS = {
    "idle": "bg-secondary",
    "refreshing": "bg-info",
    "stale": "bg-warning text-dark",
    "version_draft": "bg-primary",
    "verified": "bg-success",
}


@register.filter
def status_pill_class(status: str) -> str:
    return _STATUS_PILL_CLASS.get(status, "bg-secondary")


@register.filter
def belief_color(belief: float) -> str:
    """Map a 0..1 belief score to a hex colour for graph edges.

    Low belief -> light grey. High belief -> deep blue.
    """
    try:
        b = float(belief)
    except (TypeError, ValueError):
        return "#bbbbbb"
    if b < 0.3:
        return "#cccccc"
    if b < 0.5:
        return "#90b6d4"
    if b < 0.7:
        return "#4a89bd"
    if b < 0.9:
        return "#1c5d92"
    return "#0b3a64"
```

`apps/dashboard/migrations/__init__.py` and `apps/dashboard/tests/__init__.py` are empty files.

- [ ] **Step 4: Create `apps/dashboard/templates/base.html`**

```html
{% load dashboard_extras %}
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% block title %}IVD Regulatory Network Atlas{% endblock %}</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css">
  <link rel="stylesheet" href="https://cdn.datatables.net/2.1.8/css/dataTables.bootstrap5.min.css">
  <script src="https://unpkg.com/htmx.org@2.0.3" defer></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/cytoscape/3.30.2/cytoscape.min.js" defer></script>
  <script src="https://code.jquery.com/jquery-3.7.1.min.js" defer></script>
  <script src="https://cdn.datatables.net/2.1.8/js/dataTables.min.js" defer></script>
  <script src="https://cdn.datatables.net/2.1.8/js/dataTables.bootstrap5.min.js" defer></script>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    #cy { width: 100%; height: 600px; border: 1px solid #dee2e6; border-radius: 4px; }
    .status-pill { font-size: 0.75rem; padding: 0.25em 0.6em; border-radius: 9999px; }
    .category-section { margin-bottom: 2rem; }
    .network-card { transition: background-color 0.15s; cursor: pointer; }
    .network-card:hover { background-color: #f8f9fa; }
  </style>
</head>
<body>
  <nav class="navbar navbar-expand-lg navbar-dark bg-dark">
    <div class="container-fluid">
      <a class="navbar-brand" href="{% url 'dashboard:grid' %}">IVD Atlas</a>
      <ul class="navbar-nav me-auto">
        <li class="nav-item"><a class="nav-link" href="{% url 'dashboard:grid' %}">Networks</a></li>
        <li class="nav-item"><a class="nav-link" href="{% url 'dashboard:subscriptions' %}">Subscriptions</a></li>
      </ul>
      <ul class="navbar-nav">
        <li class="nav-item dropdown">
          <a class="nav-link dropdown-toggle position-relative" href="#" data-bs-toggle="dropdown"
             hx-get="{% url 'verify:notifications_dropdown' %}"
             hx-trigger="click"
             hx-target="#notif-dropdown-body">
            Notifications
            {% if unread_notifications_count %}
              <span class="badge bg-danger rounded-pill">{{ unread_notifications_count }}</span>
            {% endif %}
          </a>
          <ul class="dropdown-menu dropdown-menu-end" id="notif-dropdown-body" style="min-width: 360px;">
            <li class="dropdown-item text-muted">Loading...</li>
          </ul>
        </li>
        <li class="nav-item">
          <span class="navbar-text ms-3">{{ request.user.username }}</span>
        </li>
      </ul>
    </div>
  </nav>
  <main class="container-fluid py-4">
    {% block content %}{% endblock %}
  </main>
  {% block extra_js %}{% endblock %}
</body>
</html>
```

- [ ] **Step 5: Wire `"dashboard"` and the context processor into settings**

Edit `interactome/settings/base.py`:

1. Add `"dashboard"` to `INSTALLED_APPS` after `"verify"`.
2. Add the context processor to the `TEMPLATES[0]["OPTIONS"]["context_processors"]` list:

```python
"context_processors": [
    "django.template.context_processors.debug",
    "django.template.context_processors.request",
    "django.contrib.auth.context_processors.auth",
    "django.contrib.messages.context_processors.messages",
    "dashboard.context_processors.unread_notifications_count",   # ADD
],
```

- [ ] **Step 6: Include `dashboard.urls` and `verify.urls` in `interactome/urls.py`**

```python
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("verify/", include("verify.urls")),
    path("", include("dashboard.urls")),
    path("", include("core.urls")),
]
```

- [ ] **Step 7: Verify Django can boot**

```bash
poetry run python manage.py check
```

Expected: `System check identified no issues (0 silenced).`

(The template references `dashboard:grid` and `dashboard:subscriptions` and `verify:notifications_dropdown` which don't exist yet — but `check` doesn't resolve URL names, so it still passes.)

- [ ] **Step 8: Commit**

```bash
git add apps/dashboard/ interactome/settings/base.py interactome/urls.py
git commit -m "feat(dashboard): scaffold dashboard app with base template"
```

---

## Task 9: Top-level grid dashboard view (TDD)

Implements the first ASCII mockup in spec §7: 200 networks across 17 categories, status pills, corpus counts, disagreement counts.

**Files:**
- Create: `apps/dashboard/tests/test_grid_view.py`
- Create: `apps/dashboard/tests/conftest.py`
- Modify: `apps/dashboard/views.py`
- Modify: `apps/dashboard/urls.py`
- Create: `apps/dashboard/templates/dashboard/grid.html`
- Create: `apps/dashboard/templates/partials/category_section.html`
- Create: `apps/dashboard/templates/partials/network_card.html`

- [ ] **Step 1: Create `apps/dashboard/tests/conftest.py`**

```python
"""Shared fixtures for dashboard tests."""
from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

User = get_user_model()


@pytest.fixture
def user(db):
    return User.objects.create_user(username="fchemorion", email="fc@upf.edu")


@pytest.fixture
def authed_client(user) -> Client:
    return Client(HTTP_REMOTE_USER=user.username, HTTP_REMOTE_EMAIL=user.email)


@pytest.fixture
def networks(db):
    from networks.models import Network

    return [
        Network.objects.create(
            code="nfkb_axis_mmp_adamts",
            name="NF-kB → MMP/ADAMTS",
            category="core_signaling",
            pipeline_status="stale",
        ),
        Network.objects.create(
            code="wnt_beta_catenin",
            name="Wnt / beta-catenin",
            category="core_signaling",
            pipeline_status="verified",
        ),
        Network.objects.create(
            code="mir_29_axis",
            name="miR-29 axis",
            category="noncoding_rna",
            pipeline_status="version_draft",
        ),
    ]
```

- [ ] **Step 2: Write the failing test in `apps/dashboard/tests/test_grid_view.py`**

```python
"""Tests for the top-level dashboard grid view."""
from __future__ import annotations

import pytest


def test_grid_view_returns_200(db, authed_client, networks):
    response = authed_client.get("/")
    assert response.status_code == 200


def test_grid_view_lists_every_network(db, authed_client, networks):
    response = authed_client.get("/")
    body = response.content.decode()
    for n in networks:
        assert n.name in body


def test_grid_view_groups_by_category(db, authed_client, networks):
    response = authed_client.get("/")
    body = response.content.decode()
    assert "core_signaling" in body.lower() or "Core" in body
    assert "noncoding_rna" in body.lower() or "Non-coding" in body or "Non-Coding" in body


def test_grid_view_renders_status_pills(db, authed_client, networks):
    response = authed_client.get("/")
    body = response.content.decode()
    assert "stale" in body
    assert "verified" in body
    assert "version_draft" in body


def test_grid_view_shows_disagreement_counts(db, authed_client, networks):
    """If a network has open Conflicts, the count appears next to its status."""
    from graph.models import Conflict, Edge, Entity

    e1 = Entity.objects.create(symbol="A", canonical_uri="https://identifiers.org/uniprot:A")
    e2 = Entity.objects.create(symbol="B", canonical_uri="https://identifiers.org/uniprot:B")
    edge_a = Edge.objects.create(source=e1, target=e2, relation_type="inhibits", belief_score=0.7, status="candidate")
    edge_b = Edge.objects.create(source=e1, target=e2, relation_type="activates", belief_score=0.6, status="candidate")
    Conflict.objects.create(network=networks[0], edge_a=edge_a, edge_b=edge_b, resolution_status="open")

    response = authed_client.get("/")
    body = response.content.decode()
    # The count "1" should appear adjacent to "NF-kB" somewhere in the page
    assert networks[0].name in body
    assert "1 disagreement" in body or "1 conflict" in body or ">1<" in body
```

- [ ] **Step 3: Run to verify it fails**

```bash
poetry run pytest apps/dashboard/tests/test_grid_view.py -v
```

Expected: 404 (no URL routed yet).

- [ ] **Step 4: Implement the view in `apps/dashboard/views.py`**

```python
"""dashboard views — page-level controllers."""
from __future__ import annotations

from collections import defaultdict

from django.db.models import Count, Q
from django.http import HttpRequest
from django.shortcuts import render

from corpus.models import Paper
from graph.models import Conflict
from networks.models import Network


_CATEGORY_LABELS = {
    "core_signaling": "I. Core Signaling Pathways",
    "transcription_factor": "II. Transcription Factor Networks",
    "epigenetic": "III. Epigenetic Regulatory Networks",
    "noncoding_rna": "IV. Non-Coding RNA Networks",
    "ecm": "V. ECM / Matrix Remodeling",
    "growth_factor": "VI. Growth Factor / Cytokine",
    "metabolic": "VII. Metabolic Regulatory",
    "mechanobiology": "VIII. Mechanobiology",
    "cell_type": "IX. Cell Type-Specific",
    "neurovascular": "X. Neurovascular",
    "cell_fate": "XI. Cell Fate / Differentiation",
    "inter_tissue": "XII. Inter-Tissue / Systemic Crosstalk",
    "gwas": "XIII. GWAS / Genetic Regulatory",
    "disease_specific": "XIV. Disease-Specific",
    "therapeutic": "XV. Therapeutic / Regenerative",
    "proteostasis": "XVI. Proteostasis / UPR",
    "multiomics": "XVII. Multi-Omics Integration",
}


def grid(request: HttpRequest):
    """Top-level dashboard — every network at a glance."""
    networks = (
        Network.objects
        .annotate(
            open_conflicts=Count(
                "conflicts", filter=Q(conflicts__resolution_status="open")
            ),
        )
        .order_by("category", "name")
    )

    grouped: dict[str, list] = defaultdict(list)
    for n in networks:
        grouped[n.category].append(n)

    categories = [
        {
            "key": key,
            "label": _CATEGORY_LABELS.get(key, key),
            "networks": grouped.get(key, []),
        }
        for key in _CATEGORY_LABELS
        if grouped.get(key)
    ]

    total_papers = Paper.objects.count()
    recent_papers = Paper.objects.filter(
        created_at__gte=__yesterday()
    ).count()
    total_disagreements = Conflict.objects.filter(resolution_status="open").count()

    return render(request, "dashboard/grid.html", {
        "categories": categories,
        "total_networks": networks.count(),
        "total_papers": total_papers,
        "recent_papers": recent_papers,
        "total_disagreements": total_disagreements,
    })


def __yesterday():
    from datetime import timedelta
    from django.utils import timezone
    return timezone.now() - timedelta(hours=24)
```

- [ ] **Step 5: Wire the URL in `apps/dashboard/urls.py`**

```python
"""dashboard URL routes."""
from __future__ import annotations

from django.urls import path

from dashboard import views

app_name = "dashboard"
urlpatterns = [
    path("", views.grid, name="grid"),
]
```

- [ ] **Step 6: Create `apps/dashboard/templates/dashboard/grid.html`**

```html
{% extends "base.html" %}
{% load dashboard_extras %}
{% block title %}IVD Atlas - Dashboard{% endblock %}
{% block content %}
<div class="d-flex justify-content-between align-items-baseline mb-4">
  <h1 class="h3 mb-0">{{ total_networks }} Networks</h1>
  <div class="text-muted small">
    Active corpus <strong>{{ total_papers }}</strong> papers
    <span class="mx-2">&middot;</span>
    PubMed <strong>+{{ recent_papers }}</strong> last 24h
    <span class="mx-2">&middot;</span>
    <strong>{{ total_disagreements }}</strong> open disagreements
  </div>
</div>

{% for category in categories %}
  {% include "partials/category_section.html" with category=category %}
{% endfor %}
{% endblock %}
```

- [ ] **Step 7: Create `apps/dashboard/templates/partials/category_section.html`**

```html
{% load dashboard_extras %}
<section class="category-section">
  <h2 class="h5 text-muted border-bottom pb-2 mb-3">
    {{ category.label }}
    <span class="text-secondary fs-6">({{ category.networks|length }})</span>
  </h2>
  <div class="row g-2">
    {% for n in category.networks %}
      {% include "partials/network_card.html" with network=n %}
    {% endfor %}
  </div>
</section>
```

- [ ] **Step 8: Create `apps/dashboard/templates/partials/network_card.html`**

```html
{% load dashboard_extras %}
<div class="col-md-6 col-lg-4">
  <a href="{% url 'dashboard:network_detail' code=network.code %}"
     class="text-decoration-none text-dark">
    <div class="network-card card border-light h-100">
      <div class="card-body py-2 px-3">
        <div class="d-flex justify-content-between align-items-center">
          <span class="fw-semibold">{{ network.name }}</span>
          <span class="status-pill {{ network.pipeline_status|status_pill_class }} text-white">
            {{ network.pipeline_status }}
          </span>
        </div>
        {% if network.open_conflicts %}
          <small class="text-warning">
            {{ network.open_conflicts }} disagreement{{ network.open_conflicts|pluralize }}
          </small>
        {% endif %}
      </div>
    </div>
  </a>
</div>
```

- [ ] **Step 9: Run the test to verify it passes**

```bash
poetry run pytest apps/dashboard/tests/test_grid_view.py -v
```

Expected: `5 passed`. If `dashboard:network_detail` is unresolved (it doesn't exist yet), the template will raise `NoReverseMatch`. Add a placeholder URL pattern temporarily:

```python
# in apps/dashboard/urls.py
urlpatterns = [
    path("", views.grid, name="grid"),
    path("networks/<str:code>/", views.grid, name="network_detail"),  # placeholder, replaced in Task 10
    path("subscriptions/", views.grid, name="subscriptions"),         # placeholder, replaced in Task 13
]
```

Re-run the test; expect 5 passed.

- [ ] **Step 10: Commit**

```bash
git add apps/dashboard/views.py apps/dashboard/urls.py apps/dashboard/templates/ apps/dashboard/tests/
git commit -m "feat(dashboard): add top-level network grid view"
```

---

## Task 10: Per-network drill-down with Cytoscape.js graph (TDD)

Implements the second ASCII mockup in spec §7: split layout, Cytoscape graph on the left, versions list + download buttons on the right.

**Files:**
- Create: `apps/dashboard/tests/test_network_detail.py`
- Modify: `apps/dashboard/views.py`
- Modify: `apps/dashboard/urls.py`
- Create: `apps/dashboard/templates/dashboard/network_detail.html`
- Create: `apps/dashboard/templates/partials/cytoscape_init.html`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for the per-network drill-down view."""
from __future__ import annotations

import json


def test_network_detail_returns_200(db, authed_client, networks):
    response = authed_client.get(f"/networks/{networks[0].code}/")
    assert response.status_code == 200


def test_network_detail_renders_cytoscape_container(db, authed_client, networks):
    response = authed_client.get(f"/networks/{networks[0].code}/")
    assert b'id="cy"' in response.content


def test_network_detail_embeds_graph_data_as_json(db, authed_client, networks):
    from graph.models import Edge, Entity, NetworkEdgeMembership

    e1 = Entity.objects.create(symbol="SIRT1", canonical_uri="https://identifiers.org/uniprot:Q96EB6")
    e2 = Entity.objects.create(symbol="NFKB1", canonical_uri="https://identifiers.org/uniprot:P19838")
    edge = Edge.objects.create(
        source=e1, target=e2, relation_type="inhibits",
        belief_score=0.78, status="accepted",
    )
    NetworkEdgeMembership.objects.create(network=networks[0], edge=edge, relevance=0.9)

    response = authed_client.get(f"/networks/{networks[0].code}/")
    body = response.content.decode()
    assert "SIRT1" in body
    assert "NFKB1" in body
    assert "inhibits" in body


def test_network_detail_lists_versions(db, authed_client, networks):
    from sbml.models import ModelVersion

    ModelVersion.objects.create(
        network=networks[0], semver="0.3.2",
        s3_key="sbml/x.zip", frozen=True,
    )
    ModelVersion.objects.create(
        network=networks[0], semver="0.3.1",
        s3_key="sbml/y.zip", frozen=True,
    )
    response = authed_client.get(f"/networks/{networks[0].code}/")
    body = response.content.decode()
    assert "0.3.2" in body
    assert "0.3.1" in body


def test_network_detail_404_for_unknown_code(db, authed_client):
    response = authed_client.get("/networks/does_not_exist/")
    assert response.status_code == 404
```

- [ ] **Step 2: Run to verify it fails**

```bash
poetry run pytest apps/dashboard/tests/test_network_detail.py -v
```

Expected: failures on graph data assertions (the placeholder view returns the grid).

- [ ] **Step 3: Implement `network_detail` in `apps/dashboard/views.py`**

Append to `apps/dashboard/views.py`:

```python
import json

from django.shortcuts import get_object_or_404


def network_detail(request: HttpRequest, code: str):
    """Cytoscape graph + versions panel."""
    network = get_object_or_404(Network, code=code)

    memberships = (
        network.edge_memberships
        .select_related("edge__source", "edge__target")
        .filter(edge__status__in=["candidate", "accepted"])
    )

    nodes: dict[int, dict] = {}
    edges_data: list[dict] = []
    for m in memberships:
        e = m.edge
        for ent in (e.source, e.target):
            if ent.id not in nodes:
                nodes[ent.id] = {
                    "data": {
                        "id": f"n{ent.id}",
                        "label": ent.symbol,
                        "uri": ent.canonical_uri,
                    }
                }
        edges_data.append({
            "data": {
                "id": f"e{e.id}",
                "source": f"n{e.source_id}",
                "target": f"n{e.target_id}",
                "relation": e.relation_type,
                "belief": e.belief_score,
                "status": e.status,
            }
        })

    cyto_elements = list(nodes.values()) + edges_data

    versions = network.versions.order_by("-created_at")
    open_conflicts = network.conflicts.filter(resolution_status="open").count()

    return render(request, "dashboard/network_detail.html", {
        "network": network,
        "cyto_elements_json": json.dumps(cyto_elements),
        "versions": versions,
        "open_conflicts": open_conflicts,
    })
```

- [ ] **Step 4: Replace the placeholder URL in `apps/dashboard/urls.py`**

```python
"""dashboard URL routes."""
from __future__ import annotations

from django.urls import path

from dashboard import views

app_name = "dashboard"
urlpatterns = [
    path("", views.grid, name="grid"),
    path("networks/<str:code>/", views.network_detail, name="network_detail"),
    path("subscriptions/", views.grid, name="subscriptions"),   # placeholder, replaced in Task 13
]
```

- [ ] **Step 5: Create `apps/dashboard/templates/dashboard/network_detail.html`**

```html
{% extends "base.html" %}
{% load dashboard_extras %}
{% block title %}{{ network.name }} - IVD Atlas{% endblock %}
{% block content %}
<div class="d-flex justify-content-between align-items-baseline mb-3">
  <div>
    <a href="{% url 'dashboard:grid' %}" class="text-decoration-none">&larr; All networks</a>
    <h1 class="h4 d-inline-block ms-3 mb-0">{{ network.name }}</h1>
    <span class="status-pill ms-2 {{ network.pipeline_status|status_pill_class }} text-white">
      {{ network.pipeline_status }}
    </span>
  </div>
  <div>
    {% if open_conflicts %}
      <a class="btn btn-warning btn-sm"
         href="{% url 'dashboard:disagreement_queue' code=network.code %}">
        {{ open_conflicts }} disagreement{{ open_conflicts|pluralize }} to resolve
      </a>
    {% endif %}
  </div>
</div>

<div class="row g-3">
  <div class="col-lg-8">
    <div class="card">
      <div class="card-header py-2">Graph</div>
      <div class="card-body p-0"><div id="cy"></div></div>
    </div>
  </div>
  <div class="col-lg-4">
    <div class="card">
      <div class="card-header py-2">Versions</div>
      <ul class="list-group list-group-flush">
        {% for v in versions %}
          <li class="list-group-item d-flex justify-content-between align-items-center">
            <div>
              <strong>v{{ v.semver }}</strong>
              <small class="text-muted d-block">{{ v.created_at|date:"Y-m-d" }}</small>
            </div>
            <div class="btn-group btn-group-sm">
              <a class="btn btn-outline-secondary"
                 href="{% url 'sbml:download_sbml' network_code=network.code semver=v.semver %}"
                 title="SBML-qual">SBML</a>
              <a class="btn btn-outline-secondary"
                 href="{% url 'sbml:download_edges' network_code=network.code semver=v.semver %}"
                 title="edges.csv">edges</a>
              <a class="btn btn-outline-secondary"
                 href="{% url 'sbml:download_evidence' network_code=network.code semver=v.semver %}"
                 title="evidence.csv">evidence</a>
              <a class="btn btn-outline-primary"
                 href="{% url 'sbml:download_zip' network_code=network.code semver=v.semver %}"
                 title="bundle .zip">zip</a>
            </div>
          </li>
        {% empty %}
          <li class="list-group-item text-muted">No versions yet.</li>
        {% endfor %}
      </ul>
    </div>

    {% if network.pipeline_status == "version_draft" and versions %}
      {% include "verify/partials/signoff_button.html" with network=network model_version=versions.0 %}
    {% endif %}
  </div>
</div>

{% include "partials/cytoscape_init.html" with elements_json=cyto_elements_json %}
{% endblock %}
```

- [ ] **Step 6: Create `apps/dashboard/templates/partials/cytoscape_init.html`**

```html
{% block extra_js %}
<script>
document.addEventListener("DOMContentLoaded", function () {
  if (typeof cytoscape === "undefined") {
    console.error("cytoscape failed to load from CDN");
    return;
  }
  var relationColors = {
    activates:     "#2ca02c",
    inhibits:      "#d62728",
    binds:         "#8c564b",
    phosphorylates: "#ff7f0e",
    dephosphorylates: "#bcbd22",
    transcribes:   "#1f77b4",
    represses:     "#e377c2"
  };
  var elements = {{ elements_json|safe }};
  var cy = cytoscape({
    container: document.getElementById("cy"),
    elements: elements,
    layout: { name: "cose", animate: false, idealEdgeLength: 90, nodeOverlap: 12 },
    style: [
      {
        selector: "node",
        style: {
          label: "data(label)",
          "background-color": "#0d6efd",
          "color": "#212529",
          "text-valign": "center",
          "text-halign": "center",
          "font-size": 10,
          "width": "mapData(degree, 1, 20, 24, 56)",
          "height": "mapData(degree, 1, 20, 24, 56)"
        }
      },
      {
        selector: "edge",
        style: {
          "curve-style": "bezier",
          "target-arrow-shape": "triangle",
          "width": "mapData(belief, 0, 1, 1, 5)",
          "line-color": function (ele) {
            return relationColors[ele.data("relation")] || "#888";
          },
          "target-arrow-color": function (ele) {
            return relationColors[ele.data("relation")] || "#888";
          },
          "opacity": "mapData(belief, 0, 1, 0.3, 0.95)"
        }
      },
      {
        selector: "edge[status = 'rejected']",
        style: { "line-style": "dashed", "opacity": 0.25 }
      }
    ]
  });
  cy.nodes().forEach(function (n) { n.data("degree", n.degree()); });
});
</script>
{% endblock %}
```

- [ ] **Step 7: Confirm the `sbml` app exposes the four download URL names**

The template references `sbml:download_sbml`, `sbml:download_edges`, `sbml:download_evidence`, `sbml:download_zip`. These should already exist from Phase 4. If they don't, add the names to `apps/sbml/urls.py`:

```python
from django.urls import path
from sbml import views

app_name = "sbml"
urlpatterns = [
    path("networks/<str:network_code>/v/<str:semver>/sbml.xml", views.download_sbml, name="download_sbml"),
    path("networks/<str:network_code>/v/<str:semver>/edges.csv", views.download_edges, name="download_edges"),
    path("networks/<str:network_code>/v/<str:semver>/evidence.csv", views.download_evidence, name="download_evidence"),
    path("networks/<str:network_code>/v/<str:semver>/download", views.download_zip, name="download_zip"),
]
```

Verify `sbml.urls` is included in `interactome/urls.py`. If not, add:
```python
path("sbml/", include("sbml.urls")),
```

- [ ] **Step 8: Run the test to verify it passes**

```bash
poetry run pytest apps/dashboard/tests/test_network_detail.py -v
```

Expected: `5 passed`.

- [ ] **Step 9: Commit**

```bash
git add apps/dashboard/views.py apps/dashboard/urls.py apps/dashboard/templates/ apps/dashboard/tests/test_network_detail.py
git commit -m "feat(dashboard): per-network drill-down with Cytoscape.js graph"
```

---

## Task 11: Disagreement queue view + HTMX resolution form (TDD)

Implements the third ASCII mockup in spec §7: side-by-side evidence display, resolution form with five options.

**Files:**
- Create: `apps/dashboard/tests/test_disagreement_queue.py`
- Create: `apps/verify/tests/test_views.py`
- Modify: `apps/dashboard/views.py`
- Modify: `apps/verify/views.py`
- Modify: `apps/dashboard/urls.py`
- Modify: `apps/verify/urls.py`
- Create: `apps/dashboard/templates/dashboard/disagreement_queue.html`
- Create: `apps/verify/templates/verify/partials/conflict_card.html`

- [ ] **Step 1: Write the failing dashboard test in `apps/dashboard/tests/test_disagreement_queue.py`**

```python
"""Tests for the disagreement queue page."""
from __future__ import annotations


def _make_conflict(network):
    from graph.models import Conflict, Edge, Entity

    e1 = Entity.objects.create(symbol="SIRT1", canonical_uri="https://identifiers.org/uniprot:Q96EB6")
    e2 = Entity.objects.create(symbol="NFKB1", canonical_uri="https://identifiers.org/uniprot:P19838")
    edge_a = Edge.objects.create(source=e1, target=e2, relation_type="inhibits", belief_score=0.78, status="conflicted")
    edge_b = Edge.objects.create(source=e1, target=e2, relation_type="activates", belief_score=0.55, status="conflicted")
    return Conflict.objects.create(network=network, edge_a=edge_a, edge_b=edge_b, resolution_status="open")


def test_queue_view_returns_200(db, authed_client, networks):
    _make_conflict(networks[0])
    response = authed_client.get(f"/networks/{networks[0].code}/disagreements/")
    assert response.status_code == 200


def test_queue_view_lists_open_conflicts_only(db, authed_client, networks):
    open_c = _make_conflict(networks[0])
    closed_c = _make_conflict(networks[0])
    closed_c.resolution_status = "resolved_a"
    closed_c.save()
    response = authed_client.get(f"/networks/{networks[0].code}/disagreements/")
    body = response.content.decode()
    assert f'id="conflict-{open_c.id}"' in body
    assert f'id="conflict-{closed_c.id}"' not in body


def test_queue_view_shows_both_relations(db, authed_client, networks):
    _make_conflict(networks[0])
    response = authed_client.get(f"/networks/{networks[0].code}/disagreements/")
    body = response.content.decode()
    assert "inhibits" in body
    assert "activates" in body


def test_queue_view_renders_resolution_form(db, authed_client, networks):
    c = _make_conflict(networks[0])
    response = authed_client.get(f"/networks/{networks[0].code}/disagreements/")
    body = response.content.decode()
    assert "hx-post" in body
    assert f"/verify/conflicts/{c.id}/resolve/" in body
```

- [ ] **Step 2: Write the failing HTMX endpoint test in `apps/verify/tests/test_views.py`**

```python
"""Tests for verify HTMX endpoints."""
from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

User = get_user_model()


@pytest.fixture
def authed_client(db, reviewer) -> Client:
    return Client(HTTP_REMOTE_USER=reviewer.username, HTTP_REMOTE_EMAIL=reviewer.email)


def test_resolve_conflict_keeps_a(db, authed_client, conflict):
    response = authed_client.post(
        f"/verify/conflicts/{conflict.id}/resolve/",
        data={"decision": "approve", "comment": "keep A"},
    )
    assert response.status_code == 200
    conflict.refresh_from_db()
    assert conflict.resolution_status == "resolved_a"


def test_resolve_conflict_keeps_b(db, authed_client, conflict):
    response = authed_client.post(
        f"/verify/conflicts/{conflict.id}/resolve/",
        data={"decision": "reject", "comment": "keep B"},
    )
    assert response.status_code == 200
    conflict.refresh_from_db()
    assert conflict.resolution_status == "resolved_b"


def test_resolve_conflict_context_dependent(db, authed_client, conflict):
    response = authed_client.post(
        f"/verify/conflicts/{conflict.id}/resolve/",
        data={"decision": "discuss", "comment": "context-dependent split"},
    )
    assert response.status_code == 200
    conflict.refresh_from_db()
    assert conflict.resolution_status == "context_dependent"


def test_resolve_conflict_returns_partial_html(db, authed_client, conflict):
    response = authed_client.post(
        f"/verify/conflicts/{conflict.id}/resolve/",
        data={"decision": "approve", "comment": ""},
    )
    body = response.content.decode()
    # Returns a fragment, not a full page
    assert "<html" not in body.lower()
    assert "resolved" in body.lower()


def test_resolve_conflict_404_for_unknown(db, authed_client):
    response = authed_client.post(
        "/verify/conflicts/99999/resolve/",
        data={"decision": "approve"},
    )
    assert response.status_code == 404
```

- [ ] **Step 3: Run the tests to verify they fail**

```bash
poetry run pytest apps/dashboard/tests/test_disagreement_queue.py apps/verify/tests/test_views.py -v
```

Expected: 404s and import errors — the routes and views don't exist yet.

- [ ] **Step 4: Implement the `disagreement_queue` view in `apps/dashboard/views.py`**

Append:

```python
def disagreement_queue(request: HttpRequest, code: str):
    network = get_object_or_404(Network, code=code)
    conflicts = (
        network.conflicts
        .filter(resolution_status="open")
        .select_related(
            "edge_a__source", "edge_a__target",
            "edge_b__source", "edge_b__target",
        )
        .order_by("-created_at")
    )
    return render(request, "dashboard/disagreement_queue.html", {
        "network": network,
        "conflicts": conflicts,
    })
```

Wire the URL in `apps/dashboard/urls.py`:

```python
urlpatterns = [
    path("", views.grid, name="grid"),
    path("networks/<str:code>/", views.network_detail, name="network_detail"),
    path("networks/<str:code>/disagreements/", views.disagreement_queue, name="disagreement_queue"),
    path("subscriptions/", views.grid, name="subscriptions"),   # placeholder, replaced in Task 13
]
```

- [ ] **Step 5: Implement the HTMX endpoint in `apps/verify/views.py`**

```python
"""verify HTMX endpoints — POST handlers returning fragment HTML."""
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from graph.models import Conflict, Edge
from networks.models import Network
from sbml.models import ModelVersion
from verify import services
from verify.models import Notification


@require_POST
def resolve_conflict(request: HttpRequest, conflict_id: int) -> HttpResponse:
    conflict = get_object_or_404(Conflict, id=conflict_id)
    decision = request.POST.get("decision", "")
    comment = request.POST.get("comment", "")
    services.record_review(
        reviewer=request.user,
        target=conflict,
        decision=decision,
        comment=comment,
    )
    conflict.refresh_from_db()
    return render(request, "verify/partials/conflict_card.html", {
        "conflict": conflict,
        "just_resolved": True,
    })


@require_POST
def review_edge(request: HttpRequest, edge_id: int) -> HttpResponse:
    edge = get_object_or_404(Edge, id=edge_id)
    decision = request.POST.get("decision", "")
    comment = request.POST.get("comment", "")
    services.record_review(
        reviewer=request.user,
        target=edge,
        decision=decision,
        comment=comment,
    )
    edge.refresh_from_db()
    return render(request, "verify/partials/review_history.html", {
        "target": edge,
        "reviews": edge.reviews.order_by("-created_at"),
    })


@require_POST
def sign_off(request: HttpRequest, network_code: str, semver: str) -> HttpResponse:
    network = get_object_or_404(Network, code=network_code)
    model_version = get_object_or_404(ModelVersion, network=network, semver=semver)
    notes = request.POST.get("notes", "")
    services.sign_off(
        curator=request.user,
        network=network,
        model_version=model_version,
        notes=notes,
    )
    network.refresh_from_db()
    return render(request, "verify/partials/signoff_button.html", {
        "network": network,
        "model_version": model_version,
    })


def notifications_dropdown(request: HttpRequest) -> HttpResponse:
    if not request.user.is_authenticated:
        return HttpResponse("")
    notifs = (
        Notification.objects
        .filter(user=request.user)
        .order_by("-created_at")[:20]
    )
    return render(request, "verify/partials/notification_dropdown.html", {
        "notifications": notifs,
    })


@require_POST
def mark_notification_read(request: HttpRequest, notification_id: int) -> HttpResponse:
    notif = get_object_or_404(Notification, id=notification_id, user=request.user)
    notif.mark_read()
    return HttpResponse("")
```

- [ ] **Step 6: Wire the verify URLs in `apps/verify/urls.py`**

```python
"""verify URL routes — HTMX endpoints only."""
from __future__ import annotations

from django.urls import path

from verify import views

app_name = "verify"
urlpatterns = [
    path("conflicts/<int:conflict_id>/resolve/", views.resolve_conflict, name="resolve_conflict"),
    path("edges/<int:edge_id>/review/", views.review_edge, name="review_edge"),
    path("networks/<str:network_code>/sign-off/<str:semver>/", views.sign_off, name="sign_off"),
    path("notifications/", views.notifications_dropdown, name="notifications_dropdown"),
    path("notifications/<int:notification_id>/read/", views.mark_notification_read, name="mark_notification_read"),
]
```

- [ ] **Step 7: Create `apps/dashboard/templates/dashboard/disagreement_queue.html`**

```html
{% extends "base.html" %}
{% load dashboard_extras %}
{% block title %}Disagreements - {{ network.name }}{% endblock %}
{% block content %}
<div class="mb-3">
  <a href="{% url 'dashboard:network_detail' code=network.code %}" class="text-decoration-none">
    &larr; {{ network.name }}
  </a>
  <h1 class="h4 mt-2">Open disagreements ({{ conflicts|length }})</h1>
</div>

<div id="conflict-list">
  {% for conflict in conflicts %}
    {% include "verify/partials/conflict_card.html" with conflict=conflict %}
  {% empty %}
    <p class="text-muted">No open disagreements. All edges have been resolved.</p>
  {% endfor %}
</div>
{% endblock %}
```

- [ ] **Step 8: Create `apps/verify/templates/verify/partials/conflict_card.html`**

```html
<div id="conflict-{{ conflict.id }}" class="card mb-3 {% if just_resolved %}border-success{% endif %}">
  <div class="card-body">
    {% if just_resolved %}
      <div class="alert alert-success py-2 small mb-3">
        Resolved: <strong>{{ conflict.resolution_status }}</strong>
      </div>
    {% else %}
      <h2 class="h6 mb-3">
        &#9888; {{ conflict.edge_a.source.symbol }} &rarr; {{ conflict.edge_a.target.symbol }}
      </h2>

      <div class="row g-3 mb-3">
        <div class="col-md-6">
          <div class="border rounded p-2 h-100">
            <div class="fw-semibold text-danger">A: {{ conflict.edge_a.relation_type|upper }}</div>
            <div class="small text-muted">belief: {{ conflict.edge_a.belief_score|floatformat:2 }}</div>
            {% for ev in conflict.edge_a.evidence.all|slice:":2" %}
              <div class="mt-2 small">
                <a href="https://pubmed.ncbi.nlm.nih.gov/{{ ev.raw_ppi.chunk.section.paper.pmid }}/"
                   target="_blank">PMID {{ ev.raw_ppi.chunk.section.paper.pmid }}</a>
                <em class="text-secondary">&ldquo;{{ ev.raw_ppi.evidence_span_text|truncatechars:140 }}&rdquo;</em>
              </div>
            {% endfor %}
          </div>
        </div>
        <div class="col-md-6">
          <div class="border rounded p-2 h-100">
            <div class="fw-semibold text-success">B: {{ conflict.edge_b.relation_type|upper }}</div>
            <div class="small text-muted">belief: {{ conflict.edge_b.belief_score|floatformat:2 }}</div>
            {% for ev in conflict.edge_b.evidence.all|slice:":2" %}
              <div class="mt-2 small">
                <a href="https://pubmed.ncbi.nlm.nih.gov/{{ ev.raw_ppi.chunk.section.paper.pmid }}/"
                   target="_blank">PMID {{ ev.raw_ppi.chunk.section.paper.pmid }}</a>
                <em class="text-secondary">&ldquo;{{ ev.raw_ppi.evidence_span_text|truncatechars:140 }}&rdquo;</em>
              </div>
            {% endfor %}
          </div>
        </div>
      </div>

      <form hx-post="{% url 'verify:resolve_conflict' conflict_id=conflict.id %}"
            hx-target="#conflict-{{ conflict.id }}"
            hx-swap="outerHTML"
            class="d-flex flex-wrap align-items-center gap-2">
        {% csrf_token %}
        <div class="btn-group" role="group" aria-label="resolution">
          <input type="radio" class="btn-check" name="decision" id="d-a-{{ conflict.id }}" value="approve" required>
          <label class="btn btn-outline-danger btn-sm" for="d-a-{{ conflict.id }}">Keep A (INHIBIT)</label>
          <input type="radio" class="btn-check" name="decision" id="d-b-{{ conflict.id }}" value="reject" required>
          <label class="btn btn-outline-success btn-sm" for="d-b-{{ conflict.id }}">Keep B (ACTIVATE)</label>
          <input type="radio" class="btn-check" name="decision" id="d-c-{{ conflict.id }}" value="discuss" required>
          <label class="btn btn-outline-warning btn-sm" for="d-c-{{ conflict.id }}">Context-dependent</label>
          <input type="radio" class="btn-check" name="decision" id="d-d-{{ conflict.id }}" value="abstain" required>
          <label class="btn btn-outline-secondary btn-sm" for="d-d-{{ conflict.id }}">Abstain</label>
        </div>
        <input type="text" name="comment" class="form-control form-control-sm flex-grow-1"
               placeholder="Optional comment" maxlength="500">
        <button type="submit" class="btn btn-primary btn-sm">Approve &amp; continue &rarr;</button>
      </form>
    {% endif %}
  </div>
</div>
```

- [ ] **Step 9: Create the supporting partials**

`apps/verify/templates/verify/partials/review_history.html`:

```html
<div id="review-history-{{ target.id }}" class="mt-3">
  <h3 class="h6">Review history</h3>
  <ul class="list-group">
    {% for r in reviews %}
      <li class="list-group-item d-flex justify-content-between small">
        <span><strong>{{ r.reviewer.username }}</strong> {{ r.decision }} &mdash; {{ r.comment }}</span>
        <span class="text-muted">{{ r.created_at|date:"Y-m-d H:i" }}</span>
      </li>
    {% empty %}
      <li class="list-group-item text-muted small">No reviews yet.</li>
    {% endfor %}
  </ul>
</div>
```

`apps/verify/templates/verify/partials/signoff_button.html`:

```html
<div id="signoff-block-{{ network.code }}" class="mt-3">
  {% if network.pipeline_status == "verified" %}
    <div class="alert alert-success py-2 small mb-0">
      Signed off as <strong>v{{ model_version.semver }}</strong>.
    </div>
  {% else %}
    <form hx-post="{% url 'verify:sign_off' network_code=network.code semver=model_version.semver %}"
          hx-target="#signoff-block-{{ network.code }}"
          hx-swap="outerHTML"
          hx-confirm="Sign off on v{{ model_version.semver }}? This cuts a MAJOR semver bump.">
      {% csrf_token %}
      <input type="text" name="notes" class="form-control form-control-sm mb-2" placeholder="Sign-off notes (optional)">
      <button type="submit" class="btn btn-success btn-sm w-100">Sign off on v{{ model_version.semver }}</button>
    </form>
  {% endif %}
</div>
```

`apps/verify/templates/verify/partials/notification_dropdown.html`:

```html
{% for n in notifications %}
  <li>
    <a class="dropdown-item small {% if not n.is_read %}fw-bold{% endif %}"
       href="{% if n.network %}{% url 'dashboard:network_detail' code=n.network.code %}{% else %}#{% endif %}"
       hx-post="{% url 'verify:mark_notification_read' notification_id=n.id %}"
       hx-trigger="click"
       hx-swap="none">
      <div>{{ n.message|truncatechars:80 }}</div>
      <small class="text-muted">{{ n.created_at|timesince }} ago</small>
    </a>
  </li>
{% empty %}
  <li class="dropdown-item text-muted small">No notifications.</li>
{% endfor %}
```

- [ ] **Step 10: Run the tests to verify they pass**

```bash
poetry run pytest apps/dashboard/tests/test_disagreement_queue.py apps/verify/tests/test_views.py -v
```

Expected: `4 + 5 = 9 passed`.

- [ ] **Step 11: Commit**

```bash
git add apps/dashboard/views.py apps/dashboard/urls.py apps/dashboard/templates/ apps/verify/views.py apps/verify/urls.py apps/verify/templates/ apps/dashboard/tests/test_disagreement_queue.py apps/verify/tests/test_views.py
git commit -m "feat(dashboard,verify): add disagreement queue and HTMX resolution flow"
```

---

## Task 12: Audit trail page — full provenance tree per edge (TDD)

Implements spec §3: "Provenance is a graph, not a string. Every Edge has many EdgeEvidence rows → many RawPPIs → each from one ExtractionRun over one Chunk of one Paper. The biologist UI renders the full provenance tree for any edge."

**Files:**
- Create: `apps/dashboard/tests/test_audit_trail.py`
- Modify: `apps/dashboard/views.py`
- Modify: `apps/dashboard/urls.py`
- Create: `apps/dashboard/templates/dashboard/audit_trail.html`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for the per-edge audit trail page."""
from __future__ import annotations

import pytest


@pytest.fixture
def edge_with_full_provenance(db, networks):
    from corpus.models import Paper
    from extract.models import ExtractionRun, RawPPI
    from graph.models import Edge, EdgeEvidence, Entity
    from papers.models import Chunk, Section

    paper = Paper.objects.create(
        pmid="28456123",
        title="SIRT1 deacetylates p65",
        abstract="In NP cells, SIRT1 inhibits NFKB1 via deacetylation.",
        full_text_status="abstract_only",
    )
    section = Section.objects.create(paper=paper, doco_type="Results", title="Results")
    chunk = Chunk.objects.create(section=section, ordinal=0, text="SIRT1 deacetylated p65 (NFKB1)...")
    run = ExtractionRun.objects.create(chunk=chunk, model_name="qwen3:8b", status="done")
    e1 = Entity.objects.create(symbol="SIRT1", canonical_uri="https://identifiers.org/uniprot:Q96EB6")
    e2 = Entity.objects.create(symbol="NFKB1", canonical_uri="https://identifiers.org/uniprot:P19838")
    edge = Edge.objects.create(source=e1, target=e2, relation_type="inhibits", belief_score=0.85, status="accepted")
    raw = RawPPI.objects.create(
        extraction_run=run,
        chunk=chunk,
        subject_text="SIRT1",
        object_text="p65",
        relation="inhibits",
        evidence_span_text="SIRT1 deacetylated p65",
        confidence=0.92,
    )
    EdgeEvidence.objects.create(edge=edge, raw_ppi=raw)
    return edge


def test_audit_trail_returns_200(db, authed_client, edge_with_full_provenance):
    response = authed_client.get(f"/edges/{edge_with_full_provenance.id}/audit/")
    assert response.status_code == 200


def test_audit_trail_shows_pmid(db, authed_client, edge_with_full_provenance):
    response = authed_client.get(f"/edges/{edge_with_full_provenance.id}/audit/")
    body = response.content.decode()
    assert "28456123" in body


def test_audit_trail_shows_model_name(db, authed_client, edge_with_full_provenance):
    response = authed_client.get(f"/edges/{edge_with_full_provenance.id}/audit/")
    body = response.content.decode()
    assert "qwen3" in body


def test_audit_trail_shows_evidence_span(db, authed_client, edge_with_full_provenance):
    response = authed_client.get(f"/edges/{edge_with_full_provenance.id}/audit/")
    body = response.content.decode()
    assert "deacetylated" in body


def test_audit_trail_shows_review_history(db, authed_client, edge_with_full_provenance, user):
    from verify import services

    services.record_review(reviewer=user, target=edge_with_full_provenance, decision="approve", comment="solid")
    response = authed_client.get(f"/edges/{edge_with_full_provenance.id}/audit/")
    body = response.content.decode()
    assert "approve" in body
    assert "solid" in body
```

- [ ] **Step 2: Run to verify it fails**

```bash
poetry run pytest apps/dashboard/tests/test_audit_trail.py -v
```

Expected: 404.

- [ ] **Step 3: Implement the view**

Append to `apps/dashboard/views.py`:

```python
def audit_trail(request: HttpRequest, edge_id: int):
    from graph.models import Edge

    edge = get_object_or_404(
        Edge.objects.select_related("source", "target"), id=edge_id
    )

    evidence_rows = (
        edge.evidence
        .select_related(
            "raw_ppi__extraction_run",
            "raw_ppi__chunk__section__paper",
        )
        .order_by("raw_ppi__extraction_run__created_at")
    )

    reviews = edge.reviews.select_related("reviewer").order_by("-created_at")

    return render(request, "dashboard/audit_trail.html", {
        "edge": edge,
        "evidence_rows": evidence_rows,
        "reviews": reviews,
    })
```

Wire the URL in `apps/dashboard/urls.py`:

```python
urlpatterns = [
    path("", views.grid, name="grid"),
    path("networks/<str:code>/", views.network_detail, name="network_detail"),
    path("networks/<str:code>/disagreements/", views.disagreement_queue, name="disagreement_queue"),
    path("edges/<int:edge_id>/audit/", views.audit_trail, name="audit_trail"),
    path("subscriptions/", views.grid, name="subscriptions"),  # placeholder, replaced in Task 13
]
```

- [ ] **Step 4: Create `apps/dashboard/templates/dashboard/audit_trail.html`**

```html
{% extends "base.html" %}
{% block title %}Audit trail - edge {{ edge.id }}{% endblock %}
{% block content %}
<div class="mb-4">
  <a href="javascript:history.back()" class="text-decoration-none">&larr; Back</a>
  <h1 class="h4 mt-2">
    Audit trail: {{ edge.source.symbol }}
    <span class="text-muted">{{ edge.relation_type }}</span>
    {{ edge.target.symbol }}
  </h1>
  <div class="small text-muted">
    belief <strong>{{ edge.belief_score|floatformat:2 }}</strong>
    &middot; status <strong>{{ edge.status }}</strong>
    &middot; {{ evidence_rows|length }} evidence row{{ evidence_rows|length|pluralize }}
  </div>
</div>

<section class="mb-4">
  <h2 class="h5">Provenance tree</h2>
  <p class="small text-muted">
    Paper &rarr; Chunk &rarr; Extraction run &rarr; Raw PPI &rarr; this edge.
  </p>
  <table id="evidence-table" class="table table-sm table-striped table-bordered" style="width: 100%;">
    <thead>
      <tr>
        <th>PMID</th>
        <th>Paper title</th>
        <th>Section</th>
        <th>Model</th>
        <th>Confidence</th>
        <th>Evidence span</th>
        <th>Extracted at</th>
      </tr>
    </thead>
    <tbody>
      {% for ev in evidence_rows %}
        {% with paper=ev.raw_ppi.chunk.section.paper section=ev.raw_ppi.chunk.section run=ev.raw_ppi.extraction_run %}
          <tr>
            <td>
              <a href="https://pubmed.ncbi.nlm.nih.gov/{{ paper.pmid }}/" target="_blank">
                {{ paper.pmid }}
              </a>
            </td>
            <td>{{ paper.title|truncatechars:80 }}</td>
            <td>{{ section.doco_type }}</td>
            <td>{{ run.model_name }}</td>
            <td>{{ ev.raw_ppi.confidence|floatformat:2 }}</td>
            <td><em>&ldquo;{{ ev.raw_ppi.evidence_span_text|truncatechars:140 }}&rdquo;</em></td>
            <td class="small text-muted">{{ run.created_at|date:"Y-m-d H:i" }}</td>
          </tr>
        {% endwith %}
      {% endfor %}
    </tbody>
  </table>
</section>

<section>
  <h2 class="h5">Review history (append-only)</h2>
  <ul class="list-group">
    {% for r in reviews %}
      <li class="list-group-item d-flex justify-content-between">
        <span>
          <strong>{{ r.reviewer.username }}</strong>
          &mdash; <span class="badge bg-secondary">{{ r.decision }}</span>
          {% if r.comment %}<em class="text-secondary">"{{ r.comment }}"</em>{% endif %}
        </span>
        <span class="small text-muted">{{ r.created_at|date:"Y-m-d H:i:s" }}</span>
      </li>
    {% empty %}
      <li class="list-group-item text-muted">No reviews yet.</li>
    {% endfor %}
  </ul>
</section>
{% endblock %}

{% block extra_js %}
<script>
document.addEventListener("DOMContentLoaded", function () {
  if (window.jQuery && window.jQuery.fn.DataTable) {
    jQuery("#evidence-table").DataTable({ pageLength: 25, order: [[6, "desc"]] });
  }
});
</script>
{% endblock %}
```

- [ ] **Step 5: Run the test to verify it passes**

```bash
poetry run pytest apps/dashboard/tests/test_audit_trail.py -v
```

Expected: `5 passed`.

- [ ] **Step 6: Commit**

```bash
git add apps/dashboard/views.py apps/dashboard/urls.py apps/dashboard/templates/dashboard/audit_trail.html apps/dashboard/tests/test_audit_trail.py
git commit -m "feat(dashboard): add per-edge audit trail page"
```

---

## Task 13: Subscription manager + notification dropdown integration (TDD)

**Files:**
- Create: `apps/dashboard/tests/test_subscriptions.py`
- Modify: `apps/dashboard/views.py`
- Modify: `apps/dashboard/urls.py`
- Create: `apps/dashboard/templates/dashboard/subscriptions.html`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for the per-user subscription manager."""
from __future__ import annotations


def test_subscriptions_view_returns_200(db, authed_client, networks):
    response = authed_client.get("/subscriptions/")
    assert response.status_code == 200


def test_subscriptions_view_lists_every_network(db, authed_client, networks):
    response = authed_client.get("/subscriptions/")
    body = response.content.decode()
    for n in networks:
        assert n.name in body


def test_subscribe_post_creates_subscription(db, authed_client, networks, user):
    from verify.models import Subscription

    response = authed_client.post(f"/subscriptions/networks/{networks[0].code}/subscribe/")
    assert response.status_code == 200
    assert Subscription.objects.filter(user=user, network=networks[0]).exists()


def test_unsubscribe_post_removes_subscription(db, authed_client, networks, user):
    from verify.models import Subscription

    Subscription.objects.create(user=user, network=networks[0])
    response = authed_client.post(f"/subscriptions/networks/{networks[0].code}/unsubscribe/")
    assert response.status_code == 200
    assert not Subscription.objects.filter(user=user, network=networks[0]).exists()


def test_subscriptions_page_marks_subscribed_networks(db, authed_client, networks, user):
    from verify.models import Subscription

    Subscription.objects.create(user=user, network=networks[0])
    response = authed_client.get("/subscriptions/")
    body = response.content.decode()
    # The subscribe form for the subscribed network shows Unsubscribe
    assert "Unsubscribe" in body
```

- [ ] **Step 2: Run to verify it fails**

```bash
poetry run pytest apps/dashboard/tests/test_subscriptions.py -v
```

Expected: failures because the placeholder URL was reused.

- [ ] **Step 3: Implement the views**

Append to `apps/dashboard/views.py`:

```python
from django.views.decorators.http import require_POST as _require_POST


def subscriptions(request: HttpRequest):
    if not request.user.is_authenticated:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("Login required")

    from verify.models import Subscription

    networks = Network.objects.order_by("category", "name")
    subscribed_ids = set(
        Subscription.objects
        .filter(user=request.user, network__isnull=False)
        .values_list("network_id", flat=True)
    )
    return render(request, "dashboard/subscriptions.html", {
        "networks": networks,
        "subscribed_ids": subscribed_ids,
    })


@_require_POST
def subscribe_network(request: HttpRequest, code: str):
    from verify import services
    network = get_object_or_404(Network, code=code)
    services.subscribe(user=request.user, network=network)
    return render(request, "dashboard/subscriptions.html", _subscriptions_ctx(request))


@_require_POST
def unsubscribe_network(request: HttpRequest, code: str):
    from verify import services
    network = get_object_or_404(Network, code=code)
    services.unsubscribe(user=request.user, network=network)
    return render(request, "dashboard/subscriptions.html", _subscriptions_ctx(request))


def _subscriptions_ctx(request):
    from verify.models import Subscription
    return {
        "networks": Network.objects.order_by("category", "name"),
        "subscribed_ids": set(
            Subscription.objects
            .filter(user=request.user, network__isnull=False)
            .values_list("network_id", flat=True)
        ),
    }
```

- [ ] **Step 4: Replace the placeholder subscriptions URL in `apps/dashboard/urls.py`**

```python
urlpatterns = [
    path("", views.grid, name="grid"),
    path("networks/<str:code>/", views.network_detail, name="network_detail"),
    path("networks/<str:code>/disagreements/", views.disagreement_queue, name="disagreement_queue"),
    path("edges/<int:edge_id>/audit/", views.audit_trail, name="audit_trail"),
    path("subscriptions/", views.subscriptions, name="subscriptions"),
    path("subscriptions/networks/<str:code>/subscribe/", views.subscribe_network, name="subscribe_network"),
    path("subscriptions/networks/<str:code>/unsubscribe/", views.unsubscribe_network, name="unsubscribe_network"),
]
```

- [ ] **Step 5: Create `apps/dashboard/templates/dashboard/subscriptions.html`**

```html
{% extends "base.html" %}
{% block title %}Subscriptions{% endblock %}
{% block content %}
<h1 class="h4 mb-3">Your notifications</h1>
<p class="text-muted small">
  Subscribe to networks to receive email and in-app notifications when they
  become stale, accumulate disagreements, or are signed off.
</p>
<table class="table table-sm">
  <thead>
    <tr><th>Network</th><th>Category</th><th>Status</th><th class="text-end">Subscription</th></tr>
  </thead>
  <tbody>
    {% for n in networks %}
      <tr>
        <td><a href="{% url 'dashboard:network_detail' code=n.code %}">{{ n.name }}</a></td>
        <td class="small text-muted">{{ n.category }}</td>
        <td><span class="badge bg-secondary">{{ n.pipeline_status }}</span></td>
        <td class="text-end">
          {% if n.id in subscribed_ids %}
            <form method="post" action="{% url 'dashboard:unsubscribe_network' code=n.code %}" class="d-inline">
              {% csrf_token %}
              <button type="submit" class="btn btn-outline-secondary btn-sm">Unsubscribe</button>
            </form>
          {% else %}
            <form method="post" action="{% url 'dashboard:subscribe_network' code=n.code %}" class="d-inline">
              {% csrf_token %}
              <button type="submit" class="btn btn-outline-primary btn-sm">Subscribe</button>
            </form>
          {% endif %}
        </td>
      </tr>
    {% endfor %}
  </tbody>
</table>
{% endblock %}
```

- [ ] **Step 6: Run the test to verify it passes**

```bash
poetry run pytest apps/dashboard/tests/test_subscriptions.py -v
```

Expected: `5 passed`.

- [ ] **Step 7: Commit**

```bash
git add apps/dashboard/views.py apps/dashboard/urls.py apps/dashboard/templates/dashboard/subscriptions.html apps/dashboard/tests/test_subscriptions.py
git commit -m "feat(dashboard): add subscription manager"
```

---

## Task 14: Per-edge review endpoint and inline approve/reject buttons (TDD)

Allow biologists to approve/reject individual edges directly on the network detail page (in addition to resolving conflicts).

**Files:**
- Modify: `apps/verify/tests/test_views.py` (append)
- Modify: `apps/dashboard/templates/dashboard/network_detail.html` (add a side panel listing candidate edges)

- [ ] **Step 1: Append the failing test**

```python
def test_review_edge_approve_promotes_status(db, authed_client, edge):
    response = authed_client.post(
        f"/verify/edges/{edge.id}/review/",
        data={"decision": "approve", "comment": "solid evidence"},
    )
    assert response.status_code == 200
    edge.refresh_from_db()
    assert edge.status == "accepted"


def test_review_edge_reject_demotes_status(db, authed_client, edge):
    response = authed_client.post(
        f"/verify/edges/{edge.id}/review/",
        data={"decision": "reject", "comment": ""},
    )
    edge.refresh_from_db()
    assert edge.status == "rejected"


def test_review_edge_returns_history_partial(db, authed_client, edge):
    response = authed_client.post(
        f"/verify/edges/{edge.id}/review/",
        data={"decision": "approve", "comment": "x"},
    )
    body = response.content.decode()
    assert "review-history" in body or "Review history" in body
```

- [ ] **Step 2: Run to verify (these may already pass thanks to Task 11's view)**

```bash
poetry run pytest apps/verify/tests/test_views.py -v -k review_edge
```

Expected: `3 passed`. If they fail, debug; the `review_edge` view was added in Task 11 Step 5.

- [ ] **Step 3: Augment `network_detail.html` with a candidate-edges sidebar**

Edit `apps/dashboard/templates/dashboard/network_detail.html` and add a new card below the Versions card (inside the same `col-lg-4` column):

```html
<div class="card mt-3">
  <div class="card-header py-2">Candidate edges</div>
  <ul class="list-group list-group-flush" id="candidate-edges-{{ network.code }}">
    {% for m in network.edge_memberships.all|slice:":50" %}
      {% with e=m.edge %}
        {% if e.status == "candidate" %}
          <li class="list-group-item small d-flex justify-content-between align-items-center">
            <div>
              <a href="{% url 'dashboard:audit_trail' edge_id=e.id %}">
                {{ e.source.symbol }} <em>{{ e.relation_type }}</em> {{ e.target.symbol }}
              </a>
              <span class="text-muted">({{ e.belief_score|floatformat:2 }})</span>
            </div>
            <form hx-post="{% url 'verify:review_edge' edge_id=e.id %}"
                  hx-target="#review-history-{{ e.id }}"
                  hx-swap="outerHTML"
                  class="d-flex gap-1">
              {% csrf_token %}
              <button type="submit" name="decision" value="approve" class="btn btn-success btn-sm" title="approve">&check;</button>
              <button type="submit" name="decision" value="reject"  class="btn btn-danger btn-sm" title="reject">&times;</button>
            </form>
          </li>
          <li class="list-group-item p-0">
            <div id="review-history-{{ e.id }}"></div>
          </li>
        {% endif %}
      {% endwith %}
    {% endfor %}
  </ul>
</div>
```

- [ ] **Step 4: Re-run the network_detail tests to ensure the template still renders**

```bash
poetry run pytest apps/dashboard/tests/test_network_detail.py apps/verify/tests/test_views.py -v
```

Expected: all previous tests still pass.

- [ ] **Step 5: Commit**

```bash
git add apps/dashboard/templates/dashboard/network_detail.html apps/verify/tests/test_views.py
git commit -m "feat(dashboard): add inline approve/reject buttons for candidate edges"
```

---

## Task 15: Sign-off workflow end-to-end test (TDD)

A single integration test that exercises the full workflow: grid &rarr; detail &rarr; resolve all conflicts &rarr; sign off &rarr; status flips to verified &rarr; sbml.regenerate called &rarr; subscribers notified.

**Files:**
- Create: `apps/verify/tests/test_signoff_workflow.py`

- [ ] **Step 1: Write the integration test**

```python
"""End-to-end sign-off workflow test."""
from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

User = get_user_model()


@pytest.fixture
def curator(db):
    return User.objects.create_user(username="curator", email="curator@upf.edu")


@pytest.fixture
def subscriber(db):
    return User.objects.create_user(username="sub", email="sub@upf.edu")


def test_full_signoff_workflow(db, settings, curator, subscriber, mocker, mailoutbox):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    from networks.models import Network
    from sbml.models import ModelVersion
    from verify import services
    from verify.models import ReviewAssignment, Subscription

    network = Network.objects.create(
        code="nfkb_axis_mmp_adamts",
        name="NF-kB axis",
        category="core_signaling",
        pipeline_status="version_draft",
    )
    ReviewAssignment.objects.create(reviewer=curator, network=network, role="curator")
    Subscription.objects.create(user=subscriber, network=network, email_enabled=True, inapp_enabled=True)
    mv = ModelVersion.objects.create(
        network=network, semver="0.3.2", s3_key="x.zip", frozen=True,
    )

    mock_regen = mocker.patch("sbml.services.regenerate")

    client = Client(HTTP_REMOTE_USER=curator.username, HTTP_REMOTE_EMAIL=curator.email)
    response = client.post(f"/verify/networks/{network.code}/sign-off/{mv.semver}/", data={"notes": "ok"})
    assert response.status_code == 200

    network.refresh_from_db()
    assert network.pipeline_status == "verified"
    mock_regen.assert_called_once_with(network_id=network.id, bump="major")

    # subscriber received email + inapp
    assert any(subscriber.email in m.to for m in mailoutbox)
    assert subscriber.notifications.filter(network=network).exists()


def test_invalid_signoff_from_idle_returns_400(db, curator, mocker):
    from networks.models import Network
    from sbml.models import ModelVersion

    network = Network.objects.create(
        code="x", name="X", category="core_signaling", pipeline_status="idle",
    )
    mv = ModelVersion.objects.create(network=network, semver="0.1.0", s3_key="x.zip", frozen=True)

    client = Client(HTTP_REMOTE_USER=curator.username, HTTP_REMOTE_EMAIL=curator.email)
    with pytest.raises(Exception):
        client.post(f"/verify/networks/{network.code}/sign-off/{mv.semver}/", data={"notes": ""})
```

- [ ] **Step 2: Run the integration test**

```bash
poetry run pytest apps/verify/tests/test_signoff_workflow.py -v
```

Expected: `1 passed, 1 passed` (the second test catches the `InvalidTransition` propagated from the view).

If the second test fails because Django swallows the exception and returns 500 instead of bubbling it up, that is acceptable in production but the test must match. Either:
- (a) Wrap `sign_off` view to catch `InvalidTransition` and return a 400 response, then change the test to assert `response.status_code == 400`; or
- (b) Configure the test client with `raise_request_exception=True` (the default in pytest-django ≥ 4.6).

The plan recommends option (a) for a better user experience:

In `apps/verify/views.py`, change the `sign_off` view:

```python
from django.http import HttpResponseBadRequest
from verify.state_machine import InvalidTransition

@require_POST
def sign_off(request: HttpRequest, network_code: str, semver: str) -> HttpResponse:
    network = get_object_or_404(Network, code=network_code)
    model_version = get_object_or_404(ModelVersion, network=network, semver=semver)
    notes = request.POST.get("notes", "")
    try:
        services.sign_off(
            curator=request.user,
            network=network,
            model_version=model_version,
            notes=notes,
        )
    except InvalidTransition as exc:
        return HttpResponseBadRequest(f"Invalid transition: {exc}")
    network.refresh_from_db()
    return render(request, "verify/partials/signoff_button.html", {
        "network": network,
        "model_version": model_version,
    })
```

And change the second test:

```python
def test_invalid_signoff_from_idle_returns_400(...):
    ...
    response = client.post(f"/verify/networks/{network.code}/sign-off/{mv.semver}/", data={"notes": ""})
    assert response.status_code == 400
```

Re-run; expect `2 passed`.

- [ ] **Step 3: Commit**

```bash
git add apps/verify/tests/test_signoff_workflow.py apps/verify/views.py
git commit -m "test(verify): add end-to-end sign-off workflow test"
```

---

## Task 16: `mark_stale` hook from `graph` and `corpus` apps

When new edges arrive (graph integration) or new evidence lands on existing edges (corpus refresh), the affected networks should auto-transition to STALE. Phase 5 wires the hooks; the actual triggering happens in code owned by Phase 1 (`corpus`) and Phase 3 (`graph`).

**Files:**
- Modify: `apps/graph/services.py` (or the equivalent integration entry point) — add a call to `verify.services.mark_stale` after `NetworkEdgeMembership` insertion.
- Create: `apps/verify/tests/test_mark_stale_hook.py`

- [ ] **Step 1: Add the hook test in `apps/verify/tests/test_mark_stale_hook.py`**

```python
"""Verify that integration triggers the mark_stale transition."""
from __future__ import annotations

import pytest


def test_mark_stale_transitions_idle_to_stale(db, network):
    from verify import services

    network.pipeline_status = "idle"
    network.save()
    services.mark_stale(network=network, reason="new evidence")
    network.refresh_from_db()
    assert network.pipeline_status == "stale"


def test_mark_stale_transitions_verified_to_stale(db, network):
    from verify import services

    network.pipeline_status = "verified"
    network.save()
    services.mark_stale(network=network, reason="new evidence")
    network.refresh_from_db()
    assert network.pipeline_status == "stale"


def test_mark_stale_is_noop_when_already_stale(db, network):
    from verify import services

    network.pipeline_status = "stale"
    network.save()
    services.mark_stale(network=network, reason="x")
    network.refresh_from_db()
    assert network.pipeline_status == "stale"


def test_mark_stale_does_not_disturb_refreshing(db, network):
    from verify import services

    network.pipeline_status = "refreshing"
    network.save()
    services.mark_stale(network=network, reason="x")
    network.refresh_from_db()
    assert network.pipeline_status == "refreshing"
```

- [ ] **Step 2: Run the test**

```bash
poetry run pytest apps/verify/tests/test_mark_stale_hook.py -v
```

Expected: `4 passed` — `mark_stale` was already implemented in Task 5.

- [ ] **Step 3: Add the actual hook call site in `graph/services.py`**

Locate (or create) the function in Phase 3's `graph.services` that finishes integrating a batch of `RawPPI`s into edges and updates `NetworkEdgeMembership`. After the membership rows are saved, call:

```python
from verify import services as verify_services
# ... existing membership update logic ...
for network in affected_networks:
    verify_services.mark_stale(network=network, reason=f"{len(new_edges)} new edges")
```

If Phase 3 hasn't been written yet, leave a `TODO(phase-5-wiring)` comment with the import path. This task's deliverable is the verified `mark_stale` API, which Phase 3 calls.

- [ ] **Step 4: Commit**

```bash
git add apps/verify/tests/test_mark_stale_hook.py
# Plus apps/graph/services.py if any change was made
git commit -m "feat(verify): verify mark_stale hook contract"
```

---

## Task 17: CSRF + Authelia compatibility check (TDD)

HTMX POSTs include the CSRF token via the `{% csrf_token %}` template tag, but the `AutheliaRemoteUserMiddleware` runs *after* `CsrfViewMiddleware`. Confirm that HTMX-driven POSTs work end-to-end with both middlewares in the path.

**Files:**
- Create: `apps/verify/tests/test_csrf_integration.py`

- [ ] **Step 1: Write the test**

```python
"""Confirm HTMX POSTs round-trip through CSRF + Authelia middleware."""
from __future__ import annotations

from django.test import Client


def test_csrf_token_present_in_resolve_form(db, conflict):
    client = Client(HTTP_REMOTE_USER="fchemorion", enforce_csrf_checks=True)
    response = client.get(f"/networks/{conflict.network.code}/disagreements/")
    # CSRF token must be embedded in the rendered HTML
    assert "csrfmiddlewaretoken" in response.content.decode()


def test_post_without_csrf_token_is_rejected(db, conflict):
    client = Client(HTTP_REMOTE_USER="fchemorion", enforce_csrf_checks=True)
    response = client.post(
        f"/verify/conflicts/{conflict.id}/resolve/",
        data={"decision": "approve", "comment": ""},
    )
    assert response.status_code == 403


def test_post_with_csrf_token_succeeds(db, conflict):
    client = Client(HTTP_REMOTE_USER="fchemorion", enforce_csrf_checks=True)
    # First GET the page to receive the CSRF cookie
    client.get(f"/networks/{conflict.network.code}/disagreements/")
    csrf_token = client.cookies["csrftoken"].value
    response = client.post(
        f"/verify/conflicts/{conflict.id}/resolve/",
        data={"decision": "approve", "comment": ""},
        HTTP_X_CSRFTOKEN=csrf_token,
    )
    assert response.status_code == 200
```

- [ ] **Step 2: Run the test**

```bash
poetry run pytest apps/verify/tests/test_csrf_integration.py -v
```

Expected: `3 passed`. If the first test fails, ensure the `disagreement_queue.html` template contains `{% csrf_token %}` inside the resolution form (Task 11 Step 8 does include it).

- [ ] **Step 3: Document the HTMX + CSRF pattern in the base template**

Edit `apps/dashboard/templates/base.html` and add inside `<head>` (so HTMX picks the token up from cookies if the form is dynamically inserted later):

```html
<meta name="htmx-config" content='{"includeIndicatorStyles": true, "useTemplateFragments": true}'>
<script>
// HTMX sends X-CSRFToken header on every POST/PUT/DELETE by reading the
// csrftoken cookie that Django sets. This keeps inline forms (which use
// {% csrf_token %}) working AND any dynamic htmx requests without form
// payloads.
document.addEventListener("htmx:configRequest", function (evt) {
  var token = document.cookie.split("; ").find(function (r) { return r.startsWith("csrftoken="); });
  if (token) {
    evt.detail.headers["X-CSRFToken"] = token.split("=")[1];
  }
});
</script>
```

- [ ] **Step 4: Commit**

```bash
git add apps/verify/tests/test_csrf_integration.py apps/dashboard/templates/base.html
git commit -m "test(verify): confirm HTMX + CSRF + Authelia round-trip"
```

---

## Task 18: Update Beat schedule + worker queue list in compose

**Files:**
- Modify: `docker-compose.yml` (no new worker — verify.notify shares q.io)
- Modify: `interactome/settings/base.py` (confirm beat schedule includes the verify entry from Task 6)

- [ ] **Step 1: Confirm the Beat schedule entry from Task 6 is present**

Open `interactome/settings/base.py` and confirm:

```python
CELERY_BEAT_SCHEDULE = {
    # ... entries from previous phases ...
    "verify.dispatch_review_assignments": {
        "task": "verify.dispatch_review_assignments",
        "schedule": 60.0 * 60.0,   # every 1 hour
    },
}
```

If it's not there, add it now.

- [ ] **Step 2: Confirm `worker_io` handles the `q.io` queue (it should, from Phase 0)**

In `docker-compose.yml`, confirm `worker_io` runs:

```yaml
worker_io:
  command: celery -A interactome worker -Q q.io -c 8 -n io@%h -l info
```

`verify.notify` and `verify.dispatch_review_assignments` both have `queue="q.io"` (set in Task 6 Step 3), so no new worker is needed.

- [ ] **Step 3: Validate compose syntax**

```bash
docker-compose config -q
```

Expected: silent success.

- [ ] **Step 4: Commit (only if anything changed)**

```bash
git status
# if changes:
git add interactome/settings/base.py docker-compose.yml
git commit -m "build: confirm verify queue routing in compose"
```

---

## Task 19: Lint, type-check, and run the full test suite

- [ ] **Step 1: Run ruff**

```bash
poetry run ruff check .
poetry run ruff format --check .
```

Expected: `All checks passed!` for both. Fix any reported issues inline; do not silence rules.

- [ ] **Step 2: Run mypy**

```bash
poetry run mypy apps interactome
```

Expected: `Success: no issues found`. If `mypy` complains about HTMX-related type annotations in views, add the minimal annotations or `# type: ignore[<rule>]` comments at the precise line.

- [ ] **Step 3: Run the full test suite**

```bash
poetry run pytest -v
```

Expected: every test from Phase 0 through Phase 5 passes. Phase 5 contributes approximately:
- `test_models.py` &mdash; 18 tests
- `test_state_machine.py` &mdash; 9 tests
- `test_services.py` &mdash; 19 tests
- `test_emails.py` &mdash; 3 tests
- `test_tasks.py` &mdash; 3 tests
- `test_views.py` &mdash; 5 + 3 = 8 tests
- `test_signoff_workflow.py` &mdash; 2 tests
- `test_mark_stale_hook.py` &mdash; 4 tests
- `test_csrf_integration.py` &mdash; 3 tests
- `test_grid_view.py` &mdash; 5 tests
- `test_network_detail.py` &mdash; 5 tests
- `test_disagreement_queue.py` &mdash; 4 tests
- `test_audit_trail.py` &mdash; 5 tests
- `test_subscriptions.py` &mdash; 5 tests

Phase 5 total: ~93 new tests.

- [ ] **Step 4: Commit any fixes**

```bash
git status
# if any auto-fix commits needed:
git add <files>
git commit -m "style: fix ruff/mypy issues in Phase 5 code"
```

---

## Task 20: End-to-end stack verification (manual)

This is the integration smoke-test: bring up the full stack and click through the verification UI as a real biologist would.

- [ ] **Step 1: Bring the stack up**

```bash
docker-compose up -d
sleep 30
docker-compose ps
```

All 16 services from spec §9 should be `Up` or `Up (healthy)`.

- [ ] **Step 2: Migrate**

```bash
docker-compose exec web python manage.py migrate --noinput
```

- [ ] **Step 3: Seed minimal fixture data**

```bash
docker-compose exec web python manage.py shell <<'PY'
from networks.models import Network
from graph.models import Entity, Edge, NetworkEdgeMembership, Conflict
from sbml.models import ModelVersion

n = Network.objects.create(
    code="nfkb_axis_mmp_adamts",
    name="NF-kB → MMP/ADAMTS catabolic output",
    category="core_signaling",
    pipeline_status="version_draft",
)
e1 = Entity.objects.create(symbol="SIRT1", canonical_uri="https://identifiers.org/uniprot:Q96EB6")
e2 = Entity.objects.create(symbol="NFKB1", canonical_uri="https://identifiers.org/uniprot:P19838")
edge_a = Edge.objects.create(source=e1, target=e2, relation_type="inhibits", belief_score=0.78, status="conflicted")
edge_b = Edge.objects.create(source=e1, target=e2, relation_type="activates", belief_score=0.55, status="conflicted")
NetworkEdgeMembership.objects.create(network=n, edge=edge_a, relevance=0.9)
NetworkEdgeMembership.objects.create(network=n, edge=edge_b, relevance=0.9)
Conflict.objects.create(network=n, edge_a=edge_a, edge_b=edge_b, resolution_status="open")
ModelVersion.objects.create(network=n, semver="0.3.2", s3_key="sbml/x.zip", frozen=True)
print("seeded")
PY
```

- [ ] **Step 4: Hit the grid via Caddy**

```bash
curl -sk -H 'Remote-User: fchemorion' \
        -H 'Remote-Email: francis.chemorion@upf.edu' \
        -H 'Remote-Groups: simbiosys-lab' \
        https://localhost/ | head -200
```

Expected: HTML response with `<title>IVD Atlas - Dashboard</title>` and the seeded network name.

- [ ] **Step 5: Visit the per-network detail page in a browser**

Open `https://localhost/networks/nfkb_axis_mmp_adamts/` (accept the self-signed cert warning). Manually verify:

1. The Cytoscape graph renders with two nodes (SIRT1, NFKB1) and two edges (one red, one green).
2. The Versions panel lists v0.3.2 with four download buttons.
3. A button "1 disagreement to resolve" appears at the top right.

- [ ] **Step 6: Resolve the disagreement**

Click "1 disagreement to resolve" &rarr; the queue page renders with both evidence panes side by side. Pick "Keep A (INHIBIT)" and submit. The card should swap in-place to a green "Resolved: resolved_a" badge without a page reload.

- [ ] **Step 7: Sign off**

Return to the network detail page. The signoff button should appear (since status was `version_draft`). Click it, enter notes, confirm. Status pill flips to `verified`. Open the worker logs:

```bash
docker-compose logs --tail 30 worker_io
```

Expected: a `verify.notify` task ran; if a subscription existed, email was attempted (in dev, printed to the web container's stdout via the console email backend).

- [ ] **Step 8: Verify the audit trail page**

Navigate to `https://localhost/edges/<edge-id>/audit/` (right-click the edge in Cytoscape doesn't currently link there; use the candidate-edges sidebar). The DataTable should list every `EdgeEvidence` row with PMID, model name, evidence span, and the review history should show the recent approve action.

- [ ] **Step 9: Bring the stack down**

```bash
docker-compose down
```

- [ ] **Step 10: Commit any small fixes discovered during manual testing**

```bash
git status
git add <files>
git commit -m "fix: address issues found in Phase 5 stack verification"
```

---

## Task 21: Phase 5 close-out

- [ ] **Step 1: Run the full local CI suite one more time**

```bash
poetry run ruff check .
poetry run ruff format --check .
poetry run mypy apps interactome
poetry run pytest -v
```

All four commands must return exit code 0.

- [ ] **Step 2: Push to origin and verify GitHub Actions CI is green**

```bash
git push origin main
```

Open the Actions tab. The latest workflow run must be green within ~3 minutes.

- [ ] **Step 3: Tag the Phase 5 release**

```bash
git tag -a phase-5-complete -m "Phase 5 (Verification UI) complete

Working features:
- 200-network grid dashboard grouped by 17 categories with status pills
- Per-network Cytoscape.js graph + versions panel + download buttons
- Disagreement queue with side-by-side evidence and HTMX resolution form
- Append-only Review model; latest-row-wins per (reviewer, target) tuple
- Network status state machine: idle/refreshing/stale/version_draft/verified
- Signoff model triggers sbml.regenerate(bump='major') and notifies subscribers
- Subscription model (per-user, per-network or per-category)
- Email notifications via Django EmailBackend (console in dev, SMTP in prod)
- Notification model + nav-bar dropdown widget
- Audit trail page rendering full Paper -> Chunk -> ExtractionRun -> RawPPI tree
- ~93 new tests passing; ruff + mypy + pytest all green; GitHub Actions green

Next: Phase 6 (Continuous monitoring) -- see
docs/superpowers/plans/ for the next implementation plan."
git push origin phase-5-complete
```

- [ ] **Step 4: Phase 5 done. Hand off for biologist onboarding.**

The Phase 5 deliverable is ready for the lab to:

1. Log in at `https://interactome.simbiosys.sb.upf.edu/` via Authelia SSO.
2. See all 200+ networks at a glance with disagreement counts.
3. Drill into any network, view its current graph, download SBML + CSV.
4. Walk the disagreement queue, resolve conflicts via the HTMX form.
5. Subscribe to networks of interest; receive email + in-app notifications.
6. Sign off on a network, bumping it to MAJOR v1.0.0 immutable.

Once a first biologist has signed off on at least one network end-to-end (NF-kB axis is the planned pilot), Phase 6 implementation can begin.

---

## Phase 5 Self-Review

**Spec coverage check** (against `docs/superpowers/specs/2026-05-19-disc-interactome-app-design.md`):

- Section 2 (Django apps) &mdash; `verify` and `dashboard` apps created with the responsibilities listed. `verify` owns `Review`, `Signoff`, `ReviewAssignment`, plus `Subscription` and `Notification`. `dashboard` owns no models.
- Section 3 (data model) &mdash; `Review` rows are append-only via the `services.record_review` codepath. The audit-trail page renders the spec's "provenance is a graph" tree: Paper -> Section -> Chunk -> ExtractionRun -> RawPPI -> EdgeEvidence -> Edge.
- Section 7 (SBML output + verification UI) &mdash; all five ASCII screens implemented:
  - Grid dashboard with 17 category sections (Task 9)
  - Per-network drill-down with Cytoscape.js graph + versions panel (Task 10)
  - Disagreement queue with side-by-side evidence + 4 resolution options (Task 11)
  - Per-edge audit trail page with DataTables (Task 12)
  - Subscription manager (Task 13)
- Section 7 sign-off workflow &mdash; `idle -> stale -> version_draft -> verified -> stale` state machine in `verify/state_machine.py`, exercised end-to-end in `test_signoff_workflow.py`. Sign-off triggers `sbml.services.regenerate(bump='major')` per the spec's MAJOR-version-on-curator-action rule.
- Section 7 stack &mdash; HTMX 2.0, Cytoscape.js 3.30, DataTables.js 2.1 all loaded via CDN. No SPA, no JS bundler. Each click is POST -> Django view -> DB write -> `hx-swap` partial. Confirmed verbatim in `base.html`.
- Section 6 Beat schedule &mdash; added `verify.dispatch_review_assignments` at the spec's "every 1 hour" cadence.
- Section 9 (deployment) &mdash; SMTP env vars added to `.env.example` and `production.py`; console backend in dev. No new compose services needed; `verify.notify` shares the existing `q.io` queue.

**Cross-phase contract:**

- Reads from Phase 1 (`corpus.Paper`), Phase 2 (`extract.ExtractionRun`, `extract.RawPPI`), Phase 3 (`graph.Entity`, `graph.Edge`, `graph.EdgeEvidence`, `graph.Conflict`, `graph.NetworkEdgeMembership`), Phase 4 (`sbml.ModelVersion`, `sbml.services.regenerate`).
- Exposes downstream: `verify.services.notify`, `verify.services.subscribe`, `verify.services.mark_stale`, `verify.services.record_review`, `verify.services.sign_off`.
- The `mark_stale(network, reason)` API is the integration point Phase 3's `graph.normalize_and_integrate` must call after every edge-change batch, and Phase 1's `corpus.refresh_pubmed` must call when new evidence lands on a verified network's edges (Task 16).

**Placeholder scan:** No "TBD"/"TODO"/"implement later" strings in production code. One `TODO(phase-5-wiring)` comment is permitted in `graph/services.py` if Phase 3 hasn't shipped yet, since Task 16 explicitly documents that the hook *callsite* is a Phase 3 deliverable while the *contract* (the `mark_stale` API) is Phase 5.

**Type consistency:** `Review`, `Signoff`, `ReviewAssignment`, `Subscription`, `Notification` model names are identical across every test, view, template, and service module. `NetworkStatus` enum values match Django model `pipeline_status` choices exactly. `ReviewDecision.choices` is the single source of truth for the four allowed decisions; views and tests reference it by name.

**Append-only invariant verified:** `test_review_history_is_chronological` and `test_record_review_appends_rather_than_updates` both prove that recording the same reviewer's changed mind creates a new row. The `services.record_review` codepath never UPDATEs an existing `Review`.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-19-phase-5-verification-ui.md`. Two execution options:**

**1. Subagent-Driven (recommended)** &mdash; Dispatch a fresh subagent per task, review between tasks. The 21 tasks here are individually small (one model, one view, one template each) and each ends in a commit; this phase benefits from per-task review since the UI/UX iteration loop is what's hardest about Phase 5.

**2. Inline Execution** &mdash; Execute tasks in this session using `executing-plans`, batch execution with checkpoints at Tasks 7 (verify domain complete), 13 (dashboard pages complete), and 21 (close-out).

**Which approach?**
