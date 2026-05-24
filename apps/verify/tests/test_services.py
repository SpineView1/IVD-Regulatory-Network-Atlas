"""Tests for verify.services — record_review, sign_off, notify_subscribers,
subscribe, mark_stale.

TDD: tests are written first. Red → Green → Refactor.

Fixtures from conftest.py: reviewer, other_reviewer, network, edge, conflict,
model_version.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

# ---------------------------------------------------------------------------
# record_review
# ---------------------------------------------------------------------------


def test_record_review_creates_new_row(db, reviewer, edge):
    from verify.models import Review
    from verify.services import record_review

    review = record_review(reviewer=reviewer, edge=edge, decision="approve", comment="Solid.")
    assert review.pk is not None
    assert Review.objects.filter(edge=edge, reviewer=reviewer).count() == 1


def test_record_review_is_append_only(db, reviewer, edge):
    """A changed decision must create a NEW row, never update the first."""
    from verify.models import Review
    from verify.services import record_review

    first = record_review(reviewer=reviewer, edge=edge, decision="approve", comment="ok")
    second = record_review(reviewer=reviewer, edge=edge, decision="reject", comment="changed mind")
    assert second.pk != first.pk
    assert Review.objects.filter(edge=edge, reviewer=reviewer).count() == 2


def test_record_review_latest_decision_wins(db, reviewer, edge):
    """The latest row by created_at is the current decision."""
    from verify.services import record_review

    record_review(reviewer=reviewer, edge=edge, decision="discuss", comment="first")
    second = record_review(reviewer=reviewer, edge=edge, decision="approve", comment="final")
    from verify.models import Review

    latest = Review.objects.filter(edge=edge, reviewer=reviewer).order_by("-created_at").first()
    assert latest is not None
    assert latest.pk == second.pk
    assert latest.decision == "approve"


def test_record_review_against_conflict(db, reviewer, conflict):
    from verify.models import Review
    from verify.services import record_review

    review = record_review(
        reviewer=reviewer,
        conflict=conflict,
        decision="discuss",
        comment="Need curator input.",
    )
    assert review.pk is not None
    assert Review.objects.filter(conflict=conflict, reviewer=reviewer).count() == 1


def test_record_review_requires_edge_or_conflict(db, reviewer):
    from verify.services import record_review

    with pytest.raises(ValidationError):
        record_review(reviewer=reviewer, decision="approve", comment="")


def test_record_review_invalid_decision_raises(db, reviewer, edge):
    from verify.services import record_review

    with pytest.raises(ValidationError):
        record_review(reviewer=reviewer, edge=edge, decision="explode", comment="")


# ---------------------------------------------------------------------------
# subscribe
# ---------------------------------------------------------------------------


def test_subscribe_to_network(db, reviewer, network):
    from verify.models import Subscription
    from verify.services import subscribe

    sub = subscribe(user=reviewer, network=network)
    assert sub.pk is not None
    assert Subscription.objects.filter(user=reviewer, network=network).exists()


def test_subscribe_to_category(db, reviewer):
    from verify.models import Subscription
    from verify.services import subscribe

    sub = subscribe(user=reviewer, category="core_signaling")
    assert sub.pk is not None
    assert Subscription.objects.filter(user=reviewer, category="core_signaling").exists()


def test_subscribe_idempotent_for_network(db, reviewer, network):
    """Calling subscribe twice for the same network returns the same row."""
    from verify.models import Subscription
    from verify.services import subscribe

    s1 = subscribe(user=reviewer, network=network)
    s2 = subscribe(user=reviewer, network=network)
    assert s1.pk == s2.pk
    assert Subscription.objects.filter(user=reviewer, network=network).count() == 1


def test_subscribe_requires_network_or_category(db, reviewer):
    from verify.services import subscribe

    with pytest.raises(ValidationError):
        subscribe(user=reviewer)


# ---------------------------------------------------------------------------
# notify_subscribers
# ---------------------------------------------------------------------------


def test_notify_subscribers_creates_notification_rows(db, reviewer, network, model_version):
    """notify_subscribers enqueues per-subscriber Notification rows."""
    from verify.models import Notification, NotificationEvent
    from verify.services import notify_subscribers, subscribe

    subscribe(user=reviewer, network=network)
    notify_subscribers(network=network, model_version=model_version)

    notifs = Notification.objects.filter(user=reviewer, network=network)
    assert notifs.exists()
    assert notifs.filter(event_type=NotificationEvent.NEW_VERSION).exists()


def test_notify_subscribers_category_subscriber_also_notified(
    db, reviewer, other_reviewer, network, model_version
):
    """A category subscriber gets notified when any network in that category changes."""
    from verify.models import Notification
    from verify.services import notify_subscribers, subscribe

    # network.category is 'II' per conftest
    subscribe(user=other_reviewer, category=network.category)
    notify_subscribers(network=network, model_version=model_version)

    assert Notification.objects.filter(user=other_reviewer, network=network).exists()


def test_notify_subscribers_respects_inapp_disabled(db, reviewer, network, model_version):
    """Users with inapp_enabled=False get no Notification row."""
    from verify.models import Notification, Subscription
    from verify.services import notify_subscribers

    Subscription.objects.create(
        user=reviewer, network=network, inapp_enabled=False, email_enabled=False
    )
    notify_subscribers(network=network, model_version=model_version)
    assert not Notification.objects.filter(user=reviewer, network=network).exists()


def test_notify_subscribers_no_subscribers_is_noop(db, network, model_version):
    """With no subscribers, notify_subscribers must not raise."""
    from verify.services import notify_subscribers

    # Should complete without error
    notify_subscribers(network=network, model_version=model_version)


# ---------------------------------------------------------------------------
# mark_stale
# ---------------------------------------------------------------------------


def test_mark_stale_transitions_verified_network(db, network):
    """mark_stale moves a verified network to stale."""
    from verify.services import mark_stale

    network.pipeline_status = "verified"
    network.save()
    mark_stale(network=network, reason="New corpus data arrived.")
    network.refresh_from_db()
    assert network.pipeline_status == "stale"


def test_mark_stale_notifies_subscribers(db, reviewer, network):
    """mark_stale creates Notification rows for subscribers."""
    from verify.models import Notification, NotificationEvent
    from verify.services import mark_stale, subscribe

    network.pipeline_status = "verified"
    network.save()
    subscribe(user=reviewer, network=network)
    mark_stale(network=network, reason="New corpus data arrived.")
    notifs = Notification.objects.filter(user=reviewer, event_type=NotificationEvent.NETWORK_STALE)
    assert notifs.exists()


def test_mark_stale_already_stale_is_noop(db, network):
    """mark_stale on an already-stale network is idempotent (no error)."""
    from verify.services import mark_stale

    network.pipeline_status = "stale"
    network.save()
    # Should not raise InvalidTransition; stale→stale is allowed by state machine
    mark_stale(network=network, reason="Redundant call.")
    network.refresh_from_db()
    assert network.pipeline_status == "stale"


def test_mark_stale_already_stale_creates_no_notification(db, reviewer, network):
    """mark_stale on an already-stale network must NOT dispatch notifications.

    Calling mark_stale repeatedly on a stale network (e.g. every time a new
    corpus batch re-touches it) would otherwise spam every subscriber.  The fix:
    only notify on a GENUINE transition INTO stale (previous != stale).
    """
    from verify.models import Notification
    from verify.services import mark_stale, subscribe

    network.pipeline_status = "stale"
    network.save()
    subscribe(user=reviewer, network=network)

    mark_stale(network=network, reason="Redundant call.")

    assert not Notification.objects.filter(user=reviewer).exists(), (
        "mark_stale on already-stale network must not create Notification rows"
    )


def test_mark_stale_verified_to_stale_creates_notification(db, reviewer, network):
    """mark_stale on a verified network DOES dispatch a notification (genuine transition)."""
    from verify.models import Notification, NotificationEvent
    from verify.services import mark_stale, subscribe

    network.pipeline_status = "verified"
    network.save()
    subscribe(user=reviewer, network=network)

    mark_stale(network=network, reason="New corpus data arrived.")

    notifs = Notification.objects.filter(user=reviewer, event_type=NotificationEvent.NETWORK_STALE)
    assert notifs.exists(), (
        "mark_stale on a verified network must create a NETWORK_STALE Notification"
    )


# ---------------------------------------------------------------------------
# sign_off
# ---------------------------------------------------------------------------


def test_sign_off_creates_signoff_row(db, reviewer, network, model_version, monkeypatch):
    """sign_off creates a Signoff and transitions network to verified."""
    from verify.models import Signoff
    from verify.services import sign_off

    # monkeypatch the sbml regenerate task to avoid MinIO/Celery in unit test
    monkeypatch.setattr(
        "sbml.tasks.regenerate.delay",
        lambda *a, **kw: type("Result", (), {"id": "fake-task-id"})(),
    )

    so = sign_off(network=network, model_version=model_version, signed_by=reviewer, notes="LGTM")
    assert so.pk is not None
    assert Signoff.objects.filter(network=network, model_version=model_version).exists()


def test_sign_off_transitions_network_to_verified(
    db, reviewer, network, model_version, monkeypatch
):
    monkeypatch.setattr(
        "sbml.tasks.regenerate.delay",
        lambda *a, **kw: type("Result", (), {"id": "fake-task-id"})(),
    )
    from verify.services import sign_off

    sign_off(network=network, model_version=model_version, signed_by=reviewer)
    network.refresh_from_db()
    assert network.pipeline_status == "verified"


def test_sign_off_calls_curator_major_regenerate(db, reviewer, network, model_version, monkeypatch):
    """sign_off must enqueue sbml.regenerate with triggered_by_curator=True."""
    calls: list[dict] = []

    def fake_delay(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        return type("Result", (), {"id": "fake"})()

    monkeypatch.setattr("sbml.tasks.regenerate.delay", fake_delay)
    from verify.services import sign_off

    sign_off(network=network, model_version=model_version, signed_by=reviewer)
    assert calls, "sbml.tasks.regenerate.delay was not called"
    assert calls[0]["kwargs"].get("triggered_by_curator") is True


def test_sign_off_notifies_subscribers(
    db, reviewer, other_reviewer, network, model_version, monkeypatch
):
    """sign_off notifies subscribers with NETWORK_SIGNED_OFF event."""
    monkeypatch.setattr(
        "sbml.tasks.regenerate.delay",
        lambda *a, **kw: type("Result", (), {"id": "fake-task-id"})(),
    )
    from verify.models import Notification, NotificationEvent
    from verify.services import sign_off, subscribe

    subscribe(user=other_reviewer, network=network)
    sign_off(network=network, model_version=model_version, signed_by=reviewer)

    notifs = Notification.objects.filter(
        user=other_reviewer, event_type=NotificationEvent.NETWORK_SIGNED_OFF
    )
    assert notifs.exists()


def test_sign_off_cannot_sign_off_non_version_draft(
    db, reviewer, network, model_version, monkeypatch
):
    """sign_off raises InvalidTransition when network is not in version_draft."""
    monkeypatch.setattr(
        "sbml.tasks.regenerate.delay",
        lambda *a, **kw: type("Result", (), {"id": "fake-task-id"})(),
    )
    from verify.services import sign_off
    from verify.state_machine import InvalidTransition

    network.pipeline_status = "stale"
    network.save()
    with pytest.raises(InvalidTransition):
        sign_off(network=network, model_version=model_version, signed_by=reviewer)
