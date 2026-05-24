"""Phase 7 end-to-end offline stack verification test (Task 15).

Exercises the Phase-7 additions together in one test:
  1. /metrics/ endpoint is reachable and returns Prometheus-format text
  2. schedule.healthcheck task writes HealthcheckState row
  3. signoff_ceremony: dry-run + commit path (sign_off → verified + Signoff)

Design constraints:
  - OFFLINE: no Neo4j (gated via @pytest.mark.neo4j), no Ollama, no MinIO,
    no real Celery workers.
  - sbml.tasks.regenerate.delay is mocked (no MinIO write needed).
  - CELERY_TASK_ALWAYS_EAGER is set via settings override for the healthcheck test.
  - Uses real DB (postgres via scripts/verify.sh harness).

This test runs in scripts/verify.sh (no extra marks needed).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.test import Client
from django.utils import timezone

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def e2e_curator(db):
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(
        username="e2e_phase7_curator",
        email="p7_curator@upf.edu",
    )


@pytest.fixture
def e2e_network(db):
    from networks.models import Network

    return Network.objects.create(
        code="e2e_phase7_nfkb",
        title="Phase 7 e2e NF-kB axis",
        category="I",
        pipeline_status="version_draft",
    )


@pytest.fixture
def e2e_entities(db):
    from core.models import OntologyEntity
    from graph.models import Entity

    oe1 = OntologyEntity.objects.create(entity_type="protein", preferred_label="IL1B_P7")
    oe2 = OntologyEntity.objects.create(entity_type="protein", preferred_label="NFKB1_P7")
    return Entity.objects.create(ontology_entity=oe1), Entity.objects.create(ontology_entity=oe2)


@pytest.fixture
def e2e_frozen_mv(db, e2e_network):
    from sbml.models import ModelVersion

    mv = ModelVersion.objects.create(
        network=e2e_network,
        semver="0.1.0",
        zip_s3_key="sbml/e2e_phase7_nfkb/v0.1.0.zip",
        n_species=2,
        n_reactions=1,
        n_edges=1,
    )
    mv.freeze()
    return mv


@pytest.fixture
def e2e_accepted_edge(db, e2e_entities, e2e_network):
    from graph.models import Edge, NetworkEdgeMembership

    src, tgt = e2e_entities
    edge = Edge.objects.create(
        source=src, target=tgt, relation="activates", belief_score=0.85, status="accepted"
    )
    NetworkEdgeMembership.objects.create(network=e2e_network, edge=edge, relevance=1.0)
    return edge


# ---------------------------------------------------------------------------
# Test 1: /metrics/ endpoint reachable, returns Prometheus format
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_metrics_endpoint_reachable() -> None:
    """/metrics/ returns 200 with text/plain content-type (Prometheus format)."""
    client = Client()
    response = client.get("/metrics")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    assert "text/plain" in response["Content-Type"]


@pytest.mark.django_db
def test_metrics_exposes_phase7_custom_metrics() -> None:
    """/metrics/ exposes at least one of our Phase 7 custom metrics."""
    from schedule.metrics import CeleryQueueDepthCollector

    with patch.object(CeleryQueueDepthCollector, "_redis_llen", return_value=0):
        client = Client()
        response = client.get("/metrics")

    content = response.content.decode()
    # Our two Phase 7 custom collectors must be present
    assert "interactome_celery_queue_depth" in content
    assert "interactome_healthcheck_last_run_seconds_ago" in content


# ---------------------------------------------------------------------------
# Test 2: healthcheck task writes HealthcheckState
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_healthcheck_task_writes_healthcheckstate(settings, monkeypatch) -> None:
    """Calling schedule.healthcheck updates HealthcheckState.last_run_at."""
    # Override network checks so no Ollama/PubMed/postgres-slow needed
    from schedule.models import HealthcheckState, Watermark
    from schedule.tasks import BEAT_HEARTBEAT_SOURCE

    # Seed a fresh-enough pubmed watermark and beat heartbeat
    Watermark.objects.get_or_create(
        source="pubmed",
        defaults={"last_entrez_date": None, "last_pmid_seen": None, "resumption_token": ""},
    )
    # Ensure beat heartbeat watermark is recent
    beat_wm, _ = Watermark.objects.get_or_create(
        source=BEAT_HEARTBEAT_SOURCE,
        defaults={"last_entrez_date": None, "last_pmid_seen": None, "resumption_token": ""},
    )
    beat_wm.updated_at = timezone.now()
    beat_wm.save(update_fields=["updated_at"])

    # Suppress external network probes (Ollama, postgres slow check)
    monkeypatch.setattr(
        "monitoring.tasks._check_ollama",
        lambda *a, **kw: None,
        raising=False,
    )
    monkeypatch.setattr(
        "monitoring.tasks._check_postgres_slow",
        lambda *a, **kw: None,
        raising=False,
    )

    from monitoring.tasks import healthcheck

    before = timezone.now()
    healthcheck()  # call synchronously (no delay)

    state = HealthcheckState.objects.get(id=1)
    assert state.last_run_at >= before, "HealthcheckState.last_run_at not updated by healthcheck"
    assert state.status == "ok"


# ---------------------------------------------------------------------------
# Test 3: Ceremony sign-off path (sign_off → verified + Signoff)
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_phase7_ceremony_sign_off_path(
    e2e_curator, e2e_network, e2e_frozen_mv, e2e_accepted_edge
) -> None:
    """sign_off transitions network to verified and creates a Signoff row."""
    from verify.models import Signoff
    from verify.services import sign_off

    regen_calls: list[dict] = []

    def recording_delay(*args, **kwargs):
        regen_calls.append({"args": args, "kwargs": kwargs})
        return type("R", (), {"id": "fake"})()

    with patch("sbml.tasks.regenerate.delay", side_effect=recording_delay):
        so = sign_off(
            network=e2e_network,
            model_version=e2e_frozen_mv,
            signed_by=e2e_curator,
            notes="Phase 7 e2e offline test",
        )

    # Signoff row created
    assert Signoff.objects.filter(pk=so.pk).exists()
    assert so.network == e2e_network
    assert so.signed_by == e2e_curator

    # Network transitioned to verified
    e2e_network.refresh_from_db()
    assert e2e_network.pipeline_status == "verified"

    # regenerate.delay was called with triggered_by_curator=True
    assert regen_calls, "regenerate.delay was not called"
    assert regen_calls[0]["kwargs"].get("triggered_by_curator") is True


@pytest.mark.django_db
def test_phase7_signoff_ceremony_command_dry_run(
    e2e_curator, e2e_network, e2e_frozen_mv, e2e_accepted_edge
) -> None:
    """signoff_ceremony --dry-run does not change state."""
    from io import StringIO

    from django.core.management import call_command

    from verify.models import Signoff

    out = StringIO()
    with patch("sbml.tasks.regenerate.delay", return_value=None):
        call_command(
            "signoff_ceremony",
            "e2e_phase7_nfkb",
            "e2e_phase7_curator",
            dry_run=True,
            stdout=out,
        )

    # No state change
    e2e_network.refresh_from_db()
    assert e2e_network.pipeline_status == "version_draft"
    assert Signoff.objects.filter(network=e2e_network).count() == 0

    output = out.getvalue()
    assert "DRY RUN" in output.upper()
