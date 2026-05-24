"""TDD: Phase 7 covering index for verify review-queue hot path.

Tests assert that the index created by migration
0002_reviewassignment_status_index exists after migrate runs, and
that the review-queue query shape still returns correct results.

The hot path is ReviewAssignment.objects.filter(
    role='curator', network__pipeline_status__in=[...])
which is the pending-sign-off reminder query in verify.tasks.

EXPLAIN ANALYZE timings against production data are to be captured at
deploy time — not fabricated here.
"""
from __future__ import annotations

import pytest
from django.db import connection


@pytest.mark.django_db
def test_covering_index_verify_reviewassignment_network_role_exists() -> None:
    """verify_reviewassignment_network_role_idx must exist after migration."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT indexname
            FROM pg_indexes
            WHERE tablename = 'verify_reviewassignment'
              AND indexname = 'verify_reviewassignment_network_role_idx'
            """
        )
        row = cursor.fetchone()
    assert row is not None, (
        "Index verify_reviewassignment_network_role_idx not found — "
        "migration 0002_reviewassignment_status_index may not have run."
    )


@pytest.mark.django_db
def test_review_queue_query_returns_pending_curators(db) -> None:
    """The review-queue pending-reminders query returns curators on draft networks."""
    from django.contrib.auth import get_user_model

    from networks.models import Network
    from verify.models import ReviewAssignment, ReviewerRole

    User = get_user_model()

    curator = User.objects.create_user(username="curator_test", password="x")
    reviewer = User.objects.create_user(username="reviewer_test", password="x")

    draft_network = Network.objects.create(
        code="idx_test_draft", title="Draft network", pipeline_status="version_draft"
    )
    verified_network = Network.objects.create(
        code="idx_test_verified", title="Verified network", pipeline_status="verified"
    )

    ReviewAssignment.objects.create(
        reviewer=curator, network=draft_network, role=ReviewerRole.CURATOR
    )
    ReviewAssignment.objects.create(
        reviewer=reviewer, network=draft_network, role=ReviewerRole.REVIEWER
    )
    ReviewAssignment.objects.create(
        reviewer=curator, network=verified_network, role=ReviewerRole.CURATOR
    )

    # Hot query from verify.tasks.remind_pending_signoffs
    pending = list(
        ReviewAssignment.objects.filter(
            role="curator",
            network__pipeline_status__in=["version_draft", "stale"],
        ).select_related("reviewer", "network")
    )

    assert len(pending) == 1
    assert pending[0].reviewer.username == "curator_test"
    assert pending[0].network.code == "idx_test_draft"
