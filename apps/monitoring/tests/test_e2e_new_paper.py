"""End-to-end Phase 6 integration test (Task 12).

Tests the synthetic Paper → notification chain across 5 apps:
  corpus → graph → verify → monitoring → dashboard

Chain:
  1. Seed: a Network + subscriber + PaperRelevance + NetworkEdgeMembership
  2. Fire paper_ingested signal directly (simulating a completed ingest)
     → detect_affected_networks enqueued
  3. detect_affected_networks → creates pending NetworkEdgeMembership
  4. mark_stale on the network (simulating graph.integrate_pending completing)
     → _dispatch_notifications → Notification created for subscriber
  5. Verify: Notification exists + network is stale

Additionally tests that the pause flag short-circuits refresh_pubmed.

All external I/O is mocked. Celery runs eagerly.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.core import mail

User = get_user_model()


@pytest.fixture
def e2e_eager_celery(settings):
    """Make Celery run synchronously within the test."""
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True


@pytest.fixture
def e2e_network(db):
    """A verified network with keywords matching our synthetic paper."""
    from networks.models import Network

    return Network.objects.create(
        code="e2e_p6_sirt1_nfkb",
        title="SIRT1 / NF-kB Phase6 e2e",
        category="II",
        pipeline_status="verified",
        keywords=["SIRT1", "NF-kB", "p65"],
    )


@pytest.fixture
def e2e_subscriber(db):
    return User.objects.create_user(username="e2e_p6_subscriber", email="e2e_p6@upf.edu")


@pytest.fixture
def e2e_subscription(db, e2e_subscriber, e2e_network):
    from verify.services import subscribe

    return subscribe(user=e2e_subscriber, network=e2e_network)


@pytest.fixture
def e2e_paper(db):
    """A synthetic Paper already past ingest (status=ingested)."""
    from corpus.models import Paper

    return Paper.objects.create(
        pmid=99000001,
        title="SIRT1 deacetylates p65 and inhibits NF-kB",
        abstract="SIRT1 inhibits NF-kB by deacetylating p65 at K310 in NP cells.",
        ingest_status="ingested",
        is_original=True,
    )


@pytest.fixture
def e2e_relevance(db, e2e_paper, e2e_network):
    """PaperRelevance row connecting the paper to the network."""
    from corpus.models import PaperRelevance

    return PaperRelevance.objects.create(
        paper=e2e_paper,
        network=e2e_network,
        score=0.85,
        classified_by="cheap_keyword",
        reason="keyword_hit=True",
    )


# ---------------------------------------------------------------------------
# Test 1: paper_ingested signal → detect_affected_networks → NetworkEdgeMembership
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_paper_ingested_signal_triggers_detect_affected_networks(
    e2e_eager_celery,
    e2e_network,
    e2e_paper,
    e2e_relevance,
):
    """paper_ingested signal → detect_affected_networks creates pending membership row."""
    from corpus.signals import paper_ingested
    from graph.models import NetworkEdgeMembership

    # Pre-condition: no pending membership yet
    assert not NetworkEdgeMembership.objects.filter(
        network=e2e_network, pending_paper_id=e2e_paper.pmid
    ).exists()

    # Act: fire the signal (eager mode runs detect_affected_networks synchronously)
    paper_ingested.send(
        sender=None,
        paper_id=e2e_paper.pmid,
        pmid=e2e_paper.pmid,
        relevance_scores={e2e_network.pk: 0.85},
    )

    # Assert: pending membership row created
    assert NetworkEdgeMembership.objects.filter(
        network=e2e_network,
        pending_paper_id=e2e_paper.pmid,
        pending_extraction=True,
    ).exists(), "detect_affected_networks must create a pending NetworkEdgeMembership"


# ---------------------------------------------------------------------------
# Test 2: mark_stale → Notification created for subscriber
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_mark_stale_creates_subscriber_notification(
    settings,
    e2e_network,
    e2e_subscriber,
    e2e_subscription,
):
    """When a network goes stale, subscribers receive a Notification."""
    from unittest.mock import patch

    from verify.models import Notification, NotificationEvent
    from verify.services import mark_stale

    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

    with patch("verify.tasks.notify.delay"):
        mark_stale(network=e2e_network, reason="new SIRT1/NF-kB paper detected")

    e2e_network.refresh_from_db()
    assert e2e_network.pipeline_status == "stale"

    notif = Notification.objects.filter(
        user=e2e_subscriber,
        network=e2e_network,
        event_type=NotificationEvent.NETWORK_STALE,
    ).first()
    assert notif is not None, "Subscriber must receive NETWORK_STALE Notification"
    assert "SIRT1" in notif.message or "stale" in notif.message.lower()


# ---------------------------------------------------------------------------
# Test 3: Full chain — signal → membership → stale → notification
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_full_chain_paper_ingested_to_notification(
    settings,
    e2e_eager_celery,
    e2e_network,
    e2e_paper,
    e2e_relevance,
    e2e_subscriber,
    e2e_subscription,
):
    """Full chain: paper_ingested → detect_affected_networks → (simulate integration)
    → mark_stale → Notification for subscriber.
    """
    from unittest.mock import patch

    from corpus.signals import paper_ingested
    from graph.models import NetworkEdgeMembership
    from verify.models import Notification, NotificationEvent
    from verify.services import mark_stale

    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    mail.outbox.clear()

    # Step 1: Fire paper_ingested (eager Celery calls detect_affected_networks synchronously)
    paper_ingested.send(
        sender=None,
        paper_id=e2e_paper.pmid,
        pmid=e2e_paper.pmid,
        relevance_scores={e2e_network.pk: 0.85},
    )

    # Verify membership row was created
    assert NetworkEdgeMembership.objects.filter(
        network=e2e_network, pending_paper_id=e2e_paper.pmid, pending_extraction=True
    ).exists(), "Step 1 failed: NetworkEdgeMembership not created"

    # Step 2: Simulate graph.integrate_pending completing by calling mark_stale
    # (in production, integrate_pending → reassign_network_membership → mark_stale)
    with patch("verify.tasks.notify.delay"):
        mark_stale(network=e2e_network, reason="new evidence from paper 99000001")

    # Step 3: Assert the final state
    e2e_network.refresh_from_db()
    assert e2e_network.pipeline_status == "stale", "Network must be stale after new evidence"

    notif = Notification.objects.filter(
        user=e2e_subscriber,
        network=e2e_network,
        event_type=NotificationEvent.NETWORK_STALE,
    ).first()
    assert notif is not None, "Subscriber must receive NETWORK_STALE Notification"


# ---------------------------------------------------------------------------
# Test 4: Pause flag halts refresh_pubmed
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_pause_flag_halts_refresh_pubmed(settings, e2e_eager_celery):
    """When INGESTION_PAUSED is on, refresh_pubmed returns skipped without hitting NCBI."""
    from unittest.mock import patch

    from corpus.tasks import refresh_pubmed
    from monitoring.services import set_ingestion_paused

    set_ingestion_paused(True, by="ops_test", reason="e2e pause test")

    with patch("corpus.tasks._do_refresh_pubmed") as mock_do:
        result = refresh_pubmed()

    assert mock_do.called is False, "_do_refresh_pubmed must NOT be called when paused"
    assert result == {"skipped": True, "reason": "ingestion_paused"}
