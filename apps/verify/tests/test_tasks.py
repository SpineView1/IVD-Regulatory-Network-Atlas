"""Tests for verify.tasks — email sender + reviewer-reminder Beat task."""
from __future__ import annotations

from django.contrib.auth import get_user_model

from verify.models import Notification, NotificationEvent, ReviewAssignment
from verify.tasks import dispatch_review_assignments, notify


def test_notify_sends_email_for_notification(db, reviewer, network, mailoutbox):
    notif = Notification.objects.create(
        user=reviewer,
        network=network,
        event_type=NotificationEvent.NEW_VERSION,
        message="v1.2.3 ready",
    )
    result = notify(notification_id=notif.pk)
    assert result == "sent"
    assert len(mailoutbox) == 1
    assert reviewer.email in mailoutbox[0].to


def test_notify_email_only_form(db, reviewer, network, mailoutbox):
    result = notify(
        user_id=reviewer.pk,
        network_id=network.pk,
        event_type="network_stale",
        message="stale now",
    )
    assert result == "sent"
    assert len(mailoutbox) == 1
    assert network.title in mailoutbox[0].subject


def test_notify_skips_user_without_email(db, network, mailoutbox):
    user = get_user_model().objects.create_user(username="noemail")
    result = notify(
        user_id=user.pk,
        network_id=network.pk,
        event_type="new_version",
        message="x",
    )
    assert result == "skipped"
    assert len(mailoutbox) == 0


def test_dispatch_review_assignments_notifies_curators(db, reviewer, network):
    network.pipeline_status = "version_draft"
    network.save()
    ReviewAssignment.objects.create(reviewer=reviewer, network=network, role="curator")

    count = dispatch_review_assignments()

    assert count == 1
    assert Notification.objects.filter(user=reviewer, network=network).exists()


def test_dispatch_skips_idle_networks(db, reviewer, network):
    network.pipeline_status = "idle"
    network.save()
    ReviewAssignment.objects.create(reviewer=reviewer, network=network, role="curator")

    count = dispatch_review_assignments()

    assert count == 0
    assert not Notification.objects.filter(user=reviewer).exists()
