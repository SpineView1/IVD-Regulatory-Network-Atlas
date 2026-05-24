"""End-to-end sign-off workflow test (Task 15).

Exercises the full service-layer flow:
  network in version_draft
  → sign_off called (mock sbml.tasks.regenerate.delay)
  → Signoff row created
  → network.pipeline_status == "verified"
  → sbml.tasks.regenerate.delay called with triggered_by_curator=True
  → subscribers get Notification rows

Also covers the HTMX sign-off view endpoint:
  POST /verify/networks/<code>/sign-off/<semver>/
  → 200 on success (returns signoff_button partial)
  → 400 when transition is invalid (network not in version_draft)

The sbml.tasks.regenerate.delay is always mocked so no MinIO/Celery
dependency is needed in the test container.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

User = get_user_model()


@pytest.fixture
def curator(db):
    return User.objects.create_user(username="curator_test", email="curator@upf.edu")


@pytest.fixture
def subscriber(db):
    return User.objects.create_user(username="subscriber_test", email="subscriber@upf.edu")


@pytest.fixture
def draft_network(db):
    from networks.models import Network

    return Network.objects.create(
        code="nfkb_signoff_e2e",
        title="NF-kB signoff e2e",
        category="II",
        pipeline_status="version_draft",
    )


@pytest.fixture
def frozen_mv(db, draft_network):
    from sbml.models import ModelVersion

    mv = ModelVersion.objects.create(
        network=draft_network,
        semver="1.0.0",
        zip_s3_key="sbml/nfkb_signoff_e2e/v1.0.0.zip",
        n_species=5,
        n_reactions=4,
        n_edges=4,
    )
    mv.freeze()
    return mv


# ---------------------------------------------------------------------------
# Service-layer e2e test (no HTTP)
# ---------------------------------------------------------------------------


def test_signoff_service_end_to_end(
    db, monkeypatch, curator, subscriber, draft_network, frozen_mv
):
    """Full service flow: sign_off → Signoff row + network verified + regen enqueued + subscriber notified."""
    from verify.models import Notification, NotificationEvent, Signoff
    from verify.services import sign_off, subscribe

    calls: list[dict] = []

    def fake_delay(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        return type("Result", (), {"id": "fake-task"})()

    monkeypatch.setattr("sbml.tasks.regenerate.delay", fake_delay)

    subscribe(user=subscriber, network=draft_network)

    so = sign_off(
        network=draft_network,
        model_version=frozen_mv,
        signed_by=curator,
        notes="Looks good",
    )

    # 1. Signoff row was created
    assert so.pk is not None
    assert Signoff.objects.filter(network=draft_network, model_version=frozen_mv).exists()

    # 2. Network transitioned to verified
    draft_network.refresh_from_db()
    assert draft_network.pipeline_status == "verified"

    # 3. sbml.tasks.regenerate.delay was called with triggered_by_curator=True
    assert calls, "sbml.tasks.regenerate.delay was not called"
    assert calls[0]["kwargs"].get("triggered_by_curator") is True

    # 4. Subscriber notified with NETWORK_SIGNED_OFF
    notifs = Notification.objects.filter(
        user=subscriber,
        event_type=NotificationEvent.NETWORK_SIGNED_OFF,
    )
    assert notifs.exists()


def test_signoff_service_rejects_non_version_draft(
    db, monkeypatch, curator, draft_network, frozen_mv
):
    """sign_off raises InvalidTransition when network is not in version_draft."""
    from verify.services import sign_off
    from verify.state_machine import InvalidTransition

    monkeypatch.setattr(
        "sbml.tasks.regenerate.delay",
        lambda *a, **kw: None,
    )

    draft_network.pipeline_status = "stale"
    draft_network.save()

    with pytest.raises(InvalidTransition):
        sign_off(network=draft_network, model_version=frozen_mv, signed_by=curator)


# ---------------------------------------------------------------------------
# HTMX view endpoint tests
# ---------------------------------------------------------------------------


def test_signoff_view_returns_200_and_transitions_network(
    db, monkeypatch, settings, curator, draft_network, frozen_mv
):
    """POST to the sign-off endpoint succeeds: 200, network=verified."""
    from django.test import Client

    monkeypatch.setattr(
        "sbml.tasks.regenerate.delay",
        lambda *a, **kw: type("R", (), {"id": "t"})(),
    )

    # Disable fake-user fallback so the Remote-User header drives auth
    settings.AUTHELIA_DEV_FAKE_USER = None

    client = Client()
    response = client.post(
        f"/verify/networks/{draft_network.code}/sign-off/{frozen_mv.semver}/",
        data={"notes": "LGTM"},
        HTTP_REMOTE_USER=curator.username,
        HTTP_REMOTE_EMAIL=curator.email,
    )
    assert response.status_code == 200, response.content

    draft_network.refresh_from_db()
    assert draft_network.pipeline_status == "verified"


def test_signoff_view_returns_400_for_invalid_state(
    db, monkeypatch, settings, curator, draft_network, frozen_mv
):
    """POST to sign-off on an idle network returns 400 (not 500)."""
    from django.test import Client

    monkeypatch.setattr(
        "sbml.tasks.regenerate.delay",
        lambda *a, **kw: type("R", (), {"id": "t"})(),
    )

    settings.AUTHELIA_DEV_FAKE_USER = None
    draft_network.pipeline_status = "idle"
    draft_network.save()

    client = Client()
    response = client.post(
        f"/verify/networks/{draft_network.code}/sign-off/{frozen_mv.semver}/",
        data={"notes": ""},
        HTTP_REMOTE_USER=curator.username,
        HTTP_REMOTE_EMAIL=curator.email,
    )
    assert response.status_code == 400


def test_signoff_view_requires_login(db, settings, draft_network, frozen_mv):
    """Unauthenticated POST (no Remote-User header, no fake user) is rejected."""
    from django.test import Client

    # Disable fake-user fallback so no user is injected
    settings.AUTHELIA_DEV_FAKE_USER = None

    client = Client()
    response = client.post(
        f"/verify/networks/{draft_network.code}/sign-off/{frozen_mv.semver}/",
        data={"notes": ""},
    )
    # login_required redirects to /accounts/login/
    assert response.status_code in (302, 403)
