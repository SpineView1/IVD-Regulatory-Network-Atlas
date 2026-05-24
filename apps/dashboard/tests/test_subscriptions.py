"""Tests for Task 13 — Subscription manager view.

Tests:
- GET /subscriptions/ returns 200 and lists subscriptions
- Template dashboard/subscriptions.html is used
- HTMX POST to toggle email_enabled persists the update
- HTMX POST to toggle inapp_enabled persists the update
- HTMX POST to unsubscribe removes the subscription row
- update_subscription service persists toggle flags on existing rows
- PermissionDenied on toggle for non-owned subscription

Authentication note: the Authelia middleware always reads HTTP_REMOTE_USER or
falls back to AUTHELIA_DEV_FAKE_USER="fchemorion". Tests that care about
ownership create subscriptions owned by the middleware-injected user (fchemorion)
and use HTTP_REMOTE_USER="fchemorion" for the owning client.  The "other user"
uses a different REMOTE_USER value so it gets a different DB user row.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from networks.models import Network
from verify.models import Subscription

User = get_user_model()

# The username the middleware will inject when no HTTP_REMOTE_USER is set
# (from AUTHELIA_DEV_FAKE_USER = "fchemorion" in dev settings).
_DEFAULT_REMOTE_USER = "fchemorion"
_OTHER_REMOTE_USER = "reviewer_beta"


@pytest.fixture
def client():
    """Client whose requests will be handled by the middleware as 'fchemorion'."""
    return Client(HTTP_REMOTE_USER=_DEFAULT_REMOTE_USER)


@pytest.fixture
def owner_user(db):
    """The User row that the middleware will create/get for _DEFAULT_REMOTE_USER."""
    return User.objects.get_or_create(username=_DEFAULT_REMOTE_USER)[0]


@pytest.fixture
def other_user(db):
    """A different user, accessed via a different REMOTE_USER."""
    return User.objects.get_or_create(username=_OTHER_REMOTE_USER)[0]


@pytest.fixture
def network(db):
    return Network.objects.create(code="nfkb_axis", category="I", title="NF-κB Axis")


@pytest.fixture
def subscription(db, owner_user, network):
    """Subscription owned by the default middleware user (fchemorion)."""
    return Subscription.objects.create(
        user=owner_user,
        network=network,
        email_enabled=True,
        inapp_enabled=True,
    )


@pytest.fixture
def other_client():
    """Client authenticated as the other user."""
    return Client(HTTP_REMOTE_USER=_OTHER_REMOTE_USER)


class TestSubscriptionsView:
    """Tests for GET /subscriptions/ (dashboard:subscriptions)."""

    def test_subscriptions_returns_200(self, client, db):
        resp = client.get("/subscriptions/")
        assert resp.status_code == 200

    def test_subscriptions_uses_correct_template(self, client, db):
        resp = client.get("/subscriptions/")
        template_names = [t.name for t in resp.templates]
        assert "dashboard/subscriptions.html" in template_names

    def test_subscriptions_shows_existing_subscription(self, client, db, subscription):
        """The page shows subscriptions belonging to the logged-in user."""
        resp = client.get("/subscriptions/")
        body = resp.content.decode()
        assert "nfkb_axis" in body or "NF-κB Axis" in body

    def test_subscriptions_empty_for_user_with_none(self, client, db):
        resp = client.get("/subscriptions/")
        assert resp.status_code == 200


class TestUpdateSubscriptionService:
    """Tests for verify.services.update_subscription (new update path)."""

    def test_update_subscription_toggles_email_enabled_to_false(self, db, owner_user, network):
        sub = Subscription.objects.create(
            user=owner_user, network=network, email_enabled=True, inapp_enabled=True
        )
        from verify.services import update_subscription

        update_subscription(
            user=owner_user, subscription_id=sub.pk, email_enabled=False, inapp_enabled=True
        )
        sub.refresh_from_db()
        assert sub.email_enabled is False
        assert sub.inapp_enabled is True

    def test_update_subscription_toggles_inapp_enabled_to_false(self, db, owner_user, network):
        sub = Subscription.objects.create(
            user=owner_user, network=network, email_enabled=True, inapp_enabled=True
        )
        from verify.services import update_subscription

        update_subscription(
            user=owner_user, subscription_id=sub.pk, email_enabled=True, inapp_enabled=False
        )
        sub.refresh_from_db()
        assert sub.email_enabled is True
        assert sub.inapp_enabled is False

    def test_update_subscription_raises_for_wrong_user(self, db, owner_user, other_user, network):
        sub = Subscription.objects.create(
            user=owner_user, network=network, email_enabled=True, inapp_enabled=True
        )
        from django.core.exceptions import PermissionDenied

        from verify.services import update_subscription

        with pytest.raises(PermissionDenied):
            update_subscription(
                user=other_user,
                subscription_id=sub.pk,
                email_enabled=False,
                inapp_enabled=False,
            )

    def test_update_subscription_raises_for_nonexistent_id(self, db, owner_user):
        from django.http import Http404

        from verify.services import update_subscription

        with pytest.raises(Http404):
            update_subscription(
                user=owner_user,
                subscription_id=99999,
                email_enabled=False,
                inapp_enabled=False,
            )


class TestSubscriptionToggleHTMX:
    """Tests for HTMX POST /verify/subscriptions/<pk>/toggle/ endpoint."""

    def test_toggle_email_off_persists(self, client, db, subscription):
        resp = client.post(
            f"/verify/subscriptions/{subscription.pk}/toggle/",
            data={"email_enabled": "false", "inapp_enabled": "true"},
            HTTP_HX_REQUEST="true",
        )
        assert resp.status_code == 200
        subscription.refresh_from_db()
        assert subscription.email_enabled is False
        assert subscription.inapp_enabled is True

    def test_toggle_inapp_off_persists(self, client, db, subscription):
        resp = client.post(
            f"/verify/subscriptions/{subscription.pk}/toggle/",
            data={"email_enabled": "true", "inapp_enabled": "false"},
            HTTP_HX_REQUEST="true",
        )
        assert resp.status_code == 200
        subscription.refresh_from_db()
        assert subscription.inapp_enabled is False

    def test_toggle_returns_subscription_row_partial(self, client, db, subscription):
        """Response must be the subscription_row.html partial (not full page)."""
        resp = client.post(
            f"/verify/subscriptions/{subscription.pk}/toggle/",
            data={"email_enabled": "false", "inapp_enabled": "true"},
            HTTP_HX_REQUEST="true",
        )
        body = resp.content.decode()
        assert "<!doctype" not in body.lower()

    def test_toggle_403_for_other_user(self, db, other_client, subscription):
        """Another user trying to toggle a subscription they don't own → 403."""
        resp = other_client.post(
            f"/verify/subscriptions/{subscription.pk}/toggle/",
            data={"email_enabled": "false", "inapp_enabled": "false"},
            HTTP_HX_REQUEST="true",
        )
        assert resp.status_code == 403


class TestSubscriptionUnsubscribeHTMX:
    """Tests for HTMX POST /verify/subscriptions/<pk>/delete/ endpoint."""

    def test_unsubscribe_removes_row(self, client, db, subscription):
        pk = subscription.pk
        resp = client.post(
            f"/verify/subscriptions/{pk}/delete/",
            HTTP_HX_REQUEST="true",
        )
        assert resp.status_code == 200
        assert not Subscription.objects.filter(pk=pk).exists()

    def test_unsubscribe_403_for_other_user(self, db, other_client, subscription):
        resp = other_client.post(
            f"/verify/subscriptions/{subscription.pk}/delete/",
            HTTP_HX_REQUEST="true",
        )
        assert resp.status_code == 403
