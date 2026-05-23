"""Tests for verify.models — append-only Review invariant + Signoff + others."""
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
    from django.core.exceptions import ValidationError

    review = Review(
        reviewer=reviewer,
        edge=edge,
        decision="explode",
        comment="",
    )
    with pytest.raises(ValidationError):
        review.full_clean()


def test_review_requires_either_edge_or_conflict_target(db, reviewer):
    from django.core.exceptions import ValidationError

    review = Review(reviewer=reviewer, decision="approve", comment="")
    with pytest.raises(ValidationError):
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
    assert latest is not None
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
    from django.db import IntegrityError

    from verify.models import Signoff

    Signoff.objects.create(network=network, model_version=model_version, signed_by=reviewer)
    with pytest.raises(IntegrityError):
        Signoff.objects.create(network=network, model_version=model_version, signed_by=other_reviewer)


# --- ReviewAssignment --------------------------------------------------------

def test_review_assignment_links_reviewer_to_network(db, reviewer, network):
    from verify.models import ReviewAssignment

    ra = ReviewAssignment.objects.create(reviewer=reviewer, network=network, role="curator")
    assert ra.role == "curator"


def test_review_assignment_role_in_allowed_set(db, reviewer, network):
    from django.core.exceptions import ValidationError

    from verify.models import ReviewAssignment

    ra = ReviewAssignment(reviewer=reviewer, network=network, role="emperor")
    with pytest.raises(ValidationError):
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
    from django.core.exceptions import ValidationError

    from verify.models import Subscription

    sub = Subscription(user=reviewer)
    with pytest.raises(ValidationError):
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
