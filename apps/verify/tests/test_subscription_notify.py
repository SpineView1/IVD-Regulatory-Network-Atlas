"""Tests for verify.tasks — subscription stale + disagreement-digest notifications.

Task 10: Subscription notifications.
- stale-on-transition: verify mark_stale already fires _dispatch_notifications
  when going into stale for the first time; this test adds coverage for the
  distinct notify_for_state_transition helper and the daily digest.
- daily digest: collect open disagreements in subscribed networks for the last
  24 h and send ONE email per subscriber.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core import mail

from networks.models import Network
from verify.models import Notification, NotificationEvent, Subscription
from verify.services import mark_stale, subscribe

User = get_user_model()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def alice(db):
    return User.objects.create_user(username="alice_sub", email="alice@upf.edu")


@pytest.fixture
def subscribed_network(db):
    return Network.objects.create(
        code="nfkb_sub_test",
        title="NF-kB Subscription Test",
        category="II",
        pipeline_status="verified",
    )


@pytest.fixture
def alice_subscription(db, alice, subscribed_network):
    return subscribe(user=alice, network=subscribed_network)


# ---------------------------------------------------------------------------
# mark_stale → _dispatch_notifications → Notification created
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_mark_stale_creates_notification_for_subscriber(
    alice,
    subscribed_network,
    alice_subscription,
    settings,
):
    """When mark_stale transitions a network to stale, subscribers get a Notification."""
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

    with patch("verify.tasks.notify.delay"):
        mark_stale(network=subscribed_network, reason="new evidence arrived")

    subscribed_network.refresh_from_db()
    assert subscribed_network.pipeline_status == "stale"

    notif = Notification.objects.filter(
        user=alice, network=subscribed_network, event_type=NotificationEvent.NETWORK_STALE
    ).first()
    assert notif is not None, "Notification must be created for stale transition"
    assert "new evidence arrived" in notif.message or "stale" in notif.message.lower()


@pytest.mark.django_db
def test_mark_stale_idempotent_does_not_double_notify(
    alice,
    subscribed_network,
    alice_subscription,
):
    """Stale → stale (re-fire) must NOT create a second Notification."""
    with patch("verify.tasks.notify.delay"):
        mark_stale(network=subscribed_network)
        # Set to stale manually and fire again — should not create second notification
        subscribed_network.refresh_from_db()
        assert subscribed_network.pipeline_status == "stale"
        mark_stale(network=subscribed_network)  # idempotent, no new notification

    count = Notification.objects.filter(
        user=alice, network=subscribed_network, event_type=NotificationEvent.NETWORK_STALE
    ).count()
    assert count == 1, "No second notification on idempotent stale→stale re-fire"


# ---------------------------------------------------------------------------
# notify_subscribers_daily_digest task
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_daily_digest_creates_notification_for_conflicts(settings):
    """Digest creates one Notification for a subscriber with recent open conflicts."""
    from core.models import OntologyEntity
    from graph.models import Conflict, Edge, NetworkEdgeMembership
    from verify.tasks import notify_subscribers_daily_digest

    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

    bob = User.objects.create_user(username="bob_digest", email="bob@upf.edu")
    net = Network.objects.create(
        code="nfkb_digest_test", title="NF-kB Digest Test", category="I", pipeline_status="stale"
    )
    subscribe(user=bob, network=net)

    # Create two entities and edges for a conflict
    oe1 = OntologyEntity.objects.create(entity_type="protein", preferred_label="IL1B_digest")
    oe2 = OntologyEntity.objects.create(entity_type="protein", preferred_label="NFKB1_digest")
    from graph.models import Entity

    e1 = Entity.objects.create(ontology_entity=oe1)
    e2 = Entity.objects.create(ontology_entity=oe2)
    edge_a = Edge.objects.create(
        source=e1, target=e2, relation="activates", belief_score=0.7, status="conflicted"
    )
    edge_b = Edge.objects.create(
        source=e1, target=e2, relation="inhibits", belief_score=0.6, status="conflicted"
    )
    NetworkEdgeMembership.objects.create(network=net, edge=edge_a, relevance=0.9)
    Conflict.objects.create(
        edge_a=edge_a,
        edge_b=edge_b,
        conflict_type="inter_paper",
        resolution_status="open",
    )

    result = notify_subscribers_daily_digest()

    assert result["sent"] >= 1
    # A Notification must have been created for bob
    assert Notification.objects.filter(user=bob, network=net).exists()


@pytest.mark.django_db
def test_daily_digest_skips_when_no_recent_conflicts(settings):
    """Digest creates NO Notification when there are no recent open conflicts."""
    from verify.tasks import notify_subscribers_daily_digest

    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

    quiet = User.objects.create_user(username="quiet_digest", email="quiet@upf.edu")
    net = Network.objects.create(
        code="silent_digest_net", title="Silent Digest", category="I", pipeline_status="idle"
    )
    subscribe(user=quiet, network=net)

    result = notify_subscribers_daily_digest()

    assert result["sent"] == 0
    assert not Notification.objects.filter(user=quiet).exists()


@pytest.mark.django_db
def test_daily_digest_one_email_per_subscriber_across_multiple_networks(settings):
    """Digest aggregates across networks — sends only ONE email per subscriber."""
    from core.models import OntologyEntity
    from graph.models import Conflict, Edge, NetworkEdgeMembership
    from verify.tasks import notify_subscribers_daily_digest

    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

    multi_user = User.objects.create_user(username="multi_net_digest", email="multi@upf.edu")
    net1 = Network.objects.create(
        code="multi_net_1", title="Multi Net 1", category="I", pipeline_status="stale"
    )
    net2 = Network.objects.create(
        code="multi_net_2", title="Multi Net 2", category="II", pipeline_status="stale"
    )
    subscribe(user=multi_user, network=net1)
    subscribe(user=multi_user, network=net2)

    # Create conflicts in both networks
    oe1 = OntologyEntity.objects.create(entity_type="protein", preferred_label="AAA_multi")
    oe2 = OntologyEntity.objects.create(entity_type="protein", preferred_label="BBB_multi")
    from graph.models import Entity

    e1 = Entity.objects.create(ontology_entity=oe1)
    e2 = Entity.objects.create(ontology_entity=oe2)

    for net in (net1, net2):
        ea = Edge.objects.create(
            source=e1,
            target=e2,
            relation="activates" if net == net1 else "regulates",
            belief_score=0.7,
            status="conflicted",
        )
        eb = Edge.objects.create(
            source=e1,
            target=e2,
            relation="inhibits" if net == net1 else "represses",
            belief_score=0.5,
            status="conflicted",
        )
        NetworkEdgeMembership.objects.create(network=net, edge=ea, relevance=0.9)
        Conflict.objects.create(
            edge_a=ea,
            edge_b=eb,
            conflict_type="inter_paper",
            resolution_status="open",
        )

    mail.outbox.clear()
    result = notify_subscribers_daily_digest()

    # One digest per subscriber (not one per network-subscription pair)
    emails_to_multi = [m for m in mail.outbox if "multi@upf.edu" in m.to]
    assert len(emails_to_multi) == 1, "Must send exactly ONE digest email per subscriber"
    assert result["sent"] >= 1


@pytest.mark.django_db
def test_daily_digest_skips_users_without_email():
    """Digest skips in-app-only subscribers who have no email address."""
    from core.models import OntologyEntity
    from graph.models import Conflict, Edge, NetworkEdgeMembership
    from verify.tasks import notify_subscribers_daily_digest

    no_email_user = User.objects.create_user(username="no_email_digest")
    net = Network.objects.create(
        code="no_email_digest_net", title="No Email Net", category="I", pipeline_status="stale"
    )
    Subscription.objects.create(user=no_email_user, network=net, email_enabled=False)

    oe1 = OntologyEntity.objects.create(entity_type="protein", preferred_label="NE1_digest")
    oe2 = OntologyEntity.objects.create(entity_type="protein", preferred_label="NE2_digest")
    from graph.models import Entity

    e1 = Entity.objects.create(ontology_entity=oe1)
    e2 = Entity.objects.create(ontology_entity=oe2)
    ea = Edge.objects.create(
        source=e1, target=e2, relation="activates", belief_score=0.7, status="conflicted"
    )
    eb = Edge.objects.create(
        source=e1, target=e2, relation="inhibits", belief_score=0.5, status="conflicted"
    )
    NetworkEdgeMembership.objects.create(network=net, edge=ea, relevance=0.9)
    Conflict.objects.create(
        edge_a=ea, edge_b=eb, conflict_type="inter_paper", resolution_status="open"
    )

    mail.outbox.clear()
    result = notify_subscribers_daily_digest()

    assert result["sent"] == 0
    emails_to_no_email = [m for m in mail.outbox if "no_email_user" in str(m.to)]
    assert len(emails_to_no_email) == 0
