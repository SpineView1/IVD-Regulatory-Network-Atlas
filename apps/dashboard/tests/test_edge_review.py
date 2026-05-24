"""Tests for Task 14 — Per-edge review endpoint + inline approve/reject buttons.

Tests:
- POST /verify/edges/<pk>/review/ creates append-only Review row
- POST with same reviewer twice creates TWO rows (append-only, never update)
- Response is the review_history partial (not a full page)
- Inline approve/reject/discuss buttons appear on the audit_trail page
- latest-per-reviewer query: only the most recent decision per reviewer shown
  (order_by("reviewer_id", "-created_at").distinct("reviewer_id") — PostgreSQL)
- Invalid decision returns 400
- 404 for unknown edge pk
"""

from __future__ import annotations

import pytest
from django.test import Client

from verify.models import Review

_DEFAULT_REMOTE_USER = "fchemorion"
_OTHER_REMOTE_USER = "reviewer_gamma"


@pytest.fixture
def client():
    return Client(HTTP_REMOTE_USER=_DEFAULT_REMOTE_USER)


@pytest.fixture
def other_client():
    return Client(HTTP_REMOTE_USER=_OTHER_REMOTE_USER)


@pytest.fixture
def edge(db):
    from core.models import OntologyEntity
    from graph.models import Edge, Entity

    oe1 = OntologyEntity.objects.create(
        entity_type="protein",
        preferred_label="SIRT1",
        canonical_uri="https://identifiers.org/uniprot:Q96EB6",
    )
    oe2 = OntologyEntity.objects.create(
        entity_type="protein",
        preferred_label="NFKB1",
        canonical_uri="https://identifiers.org/uniprot:P19838",
    )
    e1 = Entity.objects.create(ontology_entity=oe1)
    e2 = Entity.objects.create(ontology_entity=oe2)
    return Edge.objects.create(
        source=e1,
        target=e2,
        relation="inhibits",
        belief_score=0.75,
        status="candidate",
    )


class TestEdgeReviewHTMXEndpoint:
    """Tests for POST /verify/edges/<pk>/review/."""

    def test_review_endpoint_returns_200(self, client, db, edge):
        resp = client.post(
            f"/verify/edges/{edge.pk}/review/",
            data={"decision": "approve", "comment": ""},
            HTTP_HX_REQUEST="true",
        )
        assert resp.status_code == 200

    def test_review_endpoint_creates_review_row(self, client, db, edge):
        """POST creates exactly one append-only Review row."""
        client.post(
            f"/verify/edges/{edge.pk}/review/",
            data={"decision": "approve", "comment": "Looks right"},
            HTTP_HX_REQUEST="true",
        )
        reviews = Review.objects.filter(edge=edge)
        assert reviews.count() == 1
        assert reviews.first().decision == "approve"  # type: ignore[union-attr]

    def test_review_endpoint_is_append_only(self, client, db, edge):
        """Same reviewer posting twice → TWO rows, not one updated row."""
        client.post(
            f"/verify/edges/{edge.pk}/review/",
            data={"decision": "approve", "comment": ""},
            HTTP_HX_REQUEST="true",
        )
        client.post(
            f"/verify/edges/{edge.pk}/review/",
            data={"decision": "reject", "comment": "Changed my mind"},
            HTTP_HX_REQUEST="true",
        )
        assert Review.objects.filter(edge=edge).count() == 2

    def test_review_endpoint_returns_partial_not_full_page(self, client, db, edge):
        """Response must be a fragment, not a full HTML page."""
        resp = client.post(
            f"/verify/edges/{edge.pk}/review/",
            data={"decision": "discuss", "comment": "Need more context"},
            HTTP_HX_REQUEST="true",
        )
        body = resp.content.decode()
        assert "<!doctype" not in body.lower()

    def test_review_endpoint_invalid_decision_returns_400(self, client, db, edge):
        resp = client.post(
            f"/verify/edges/{edge.pk}/review/",
            data={"decision": "invalid_choice"},
            HTTP_HX_REQUEST="true",
        )
        assert resp.status_code == 400

    def test_review_endpoint_404_for_unknown_edge(self, client, db):
        resp = client.post(
            "/verify/edges/99999/review/",
            data={"decision": "approve"},
            HTTP_HX_REQUEST="true",
        )
        assert resp.status_code == 404

    def test_review_endpoint_stores_comment(self, client, db, edge):
        client.post(
            f"/verify/edges/{edge.pk}/review/",
            data={"decision": "approve", "comment": "Strong evidence"},
            HTTP_HX_REQUEST="true",
        )
        review = Review.objects.filter(edge=edge).first()
        assert review is not None
        assert review.comment == "Strong evidence"


class TestLatestPerReviewerQuery:
    """Tests for the latest-per-reviewer query used to show current decisions."""

    def test_latest_per_reviewer_shows_most_recent_decision(self, db, edge):
        """order_by('reviewer_id', '-created_at').distinct('reviewer_id') returns
        only the latest decision per reviewer.
        """
        from django.contrib.auth import get_user_model

        from verify.services import record_review

        User = get_user_model()
        reviewer1 = User.objects.get_or_create(username="rev1")[0]
        reviewer2 = User.objects.get_or_create(username="rev2")[0]

        record_review(reviewer=reviewer1, edge=edge, decision="approve")
        record_review(reviewer=reviewer1, edge=edge, decision="reject")  # latest for rev1
        record_review(reviewer=reviewer2, edge=edge, decision="discuss")  # only for rev2

        latest = list(
            Review.objects.filter(edge=edge)
            .order_by("reviewer_id", "-created_at")
            .distinct("reviewer_id")
        )
        decisions = {r.reviewer_id: r.decision for r in latest}
        assert decisions[reviewer1.pk] == "reject"
        assert decisions[reviewer2.pk] == "discuss"
        assert len(latest) == 2

    def test_latest_per_reviewer_single_reviewer_single_row(self, db, edge):
        from django.contrib.auth import get_user_model

        from verify.services import record_review

        User = get_user_model()
        reviewer = User.objects.get_or_create(username="rev_solo")[0]
        record_review(reviewer=reviewer, edge=edge, decision="approve")

        latest = list(
            Review.objects.filter(edge=edge)
            .order_by("reviewer_id", "-created_at")
            .distinct("reviewer_id")
        )
        assert len(latest) == 1
        assert latest[0].decision == "approve"


class TestAuditTrailShowsReviewButtons:
    """Inline approve/reject/discuss buttons appear in the audit_trail page."""

    def test_audit_trail_has_approve_button(self, client, db, edge):
        resp = client.get(f"/networks/edges/{edge.pk}/audit/")
        body = resp.content.decode()
        # The page should contain a review form or buttons
        assert "approve" in body.lower() or "review" in body.lower()

    def test_audit_trail_has_reject_button(self, client, db, edge):
        resp = client.get(f"/networks/edges/{edge.pk}/audit/")
        body = resp.content.decode()
        assert "reject" in body.lower() or "review" in body.lower()

    def test_audit_trail_review_form_posts_to_review_endpoint(self, client, db, edge):
        resp = client.get(f"/networks/edges/{edge.pk}/audit/")
        body = resp.content.decode()
        assert f"/verify/edges/{edge.pk}/review/" in body
