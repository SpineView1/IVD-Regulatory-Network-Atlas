"""Tests for the signoff_ceremony management command (Task 10, Phase 7 TDD).

Uses REAL model field names (per cross-plan reconciliation doc):
- Network.title (not name); Network.category max_length=8
- Entity requires OntologyEntity FK
- Edge.relation (not relation_type)
- ModelVersion: frozen_at (not frozen), n_species/n_reactions/n_edges required
- Signoff: network, model_version, signed_by, notes
- verify.services.sign_off(network=, model_version=, signed_by=, notes=)
- Network starts in version_draft for sign_off to work
- sbml.tasks.regenerate.delay is MOCKED (no MinIO/Celery in test container)
"""

from __future__ import annotations

from io import StringIO
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command

User = get_user_model()


# ---------------------------------------------------------------------------
# Fixtures — use real field names throughout
# ---------------------------------------------------------------------------


@pytest.fixture
def curator(db):
    return User.objects.create_user(
        username="fchemorion",
        email="francis.chemorion@upf.edu",
        first_name="Francis",
        last_name="Chemorion",
    )


@pytest.fixture
def nfkb_network(db):
    """Network at version_draft — the only state sign_off accepts."""
    from networks.models import Network

    return Network.objects.create(
        code="nfkb_axis_mmp_adamts",
        title="NF-kB → MMP/ADAMTS catabolic output (NP cells)",
        category="I",
        pipeline_status="version_draft",
    )


@pytest.fixture
def entities(db):
    """OntologyEntity + Entity pairs — required by graph.models.Entity."""
    from core.models import OntologyEntity
    from graph.models import Entity

    oe1 = OntologyEntity.objects.create(
        entity_type="protein",
        preferred_label="IL1B",
        canonical_uri="https://identifiers.org/uniprot:P01584",
    )
    oe2 = OntologyEntity.objects.create(
        entity_type="protein",
        preferred_label="NFKB1",
        canonical_uri="https://identifiers.org/uniprot:P19838",
    )
    return Entity.objects.create(ontology_entity=oe1), Entity.objects.create(ontology_entity=oe2)


@pytest.fixture
def accepted_edge(db, entities, nfkb_network):
    """One accepted edge + membership — the minimum graph state for ceremony."""
    from graph.models import Edge, NetworkEdgeMembership

    src, tgt = entities
    edge = Edge.objects.create(
        source=src,
        target=tgt,
        relation="activates",
        belief_score=0.92,
        status="accepted",
    )
    NetworkEdgeMembership.objects.create(network=nfkb_network, edge=edge, relevance=1.0)
    return edge


@pytest.fixture
def frozen_mv(db, nfkb_network):
    """A frozen ModelVersion at v0.3.2 — the pre-ceremony draft version."""
    from sbml.models import ModelVersion

    mv = ModelVersion.objects.create(
        network=nfkb_network,
        semver="0.3.2",
        zip_s3_key="sbml/nfkb_axis_mmp_adamts/v0.3.2.zip",
        n_species=2,
        n_reactions=1,
        n_edges=1,
    )
    mv.freeze()
    return mv


# ---------------------------------------------------------------------------
# Helper: patch regenerate.delay so no MinIO/Celery needed
# ---------------------------------------------------------------------------

FAKE_DELAY = "sbml.tasks.regenerate.delay"


def _fake_delay(*_args, **_kwargs):
    return type("AsyncResult", (), {"id": "fake-task"})()


# ---------------------------------------------------------------------------
# RED tests — each tests one behaviour of the command
# ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_ceremony_requires_existing_network(db):
    """Raises CommandError with descriptive message when network code not found."""
    with pytest.raises(CommandError, match="network code 'no_such_network' not found"):
        call_command("signoff_ceremony", "no_such_network", "fchemorion")


@pytest.mark.django_db
def test_ceremony_requires_curator_user_exists(nfkb_network, frozen_mv):
    """Raises CommandError when the curator username doesn't exist."""
    with pytest.raises(CommandError, match="user 'ghost' not found"):
        call_command("signoff_ceremony", "nfkb_axis_mmp_adamts", "ghost")


@pytest.mark.django_db
def test_ceremony_rejects_network_not_in_draft_state(nfkb_network, frozen_mv, curator):
    """Raises CommandError when network is not in version_draft state."""
    nfkb_network.pipeline_status = "verified"
    nfkb_network.save()

    with pytest.raises(CommandError, match="must be in version_draft"):
        call_command("signoff_ceremony", "nfkb_axis_mmp_adamts", "fchemorion")


@pytest.mark.django_db
def test_ceremony_raises_when_no_frozen_model_version(nfkb_network, curator):
    """Raises CommandError when the network has no frozen ModelVersion to sign off."""
    with (
        pytest.raises(CommandError, match="no frozen ModelVersion"),
        patch(FAKE_DELAY, side_effect=_fake_delay),
    ):
        call_command("signoff_ceremony", "nfkb_axis_mmp_adamts", "fchemorion")


@pytest.mark.django_db
def test_ceremony_creates_signoff_row(nfkb_network, frozen_mv, curator, accepted_edge):
    """A successful ceremony creates exactly one Signoff row for the network."""
    from verify.models import Signoff

    with patch(FAKE_DELAY, side_effect=_fake_delay):
        call_command("signoff_ceremony", "nfkb_axis_mmp_adamts", "fchemorion")

    assert Signoff.objects.filter(network=nfkb_network).count() == 1


@pytest.mark.django_db
def test_ceremony_transitions_network_to_verified(nfkb_network, frozen_mv, curator, accepted_edge):
    """A successful ceremony sets network.pipeline_status to 'verified'."""
    with patch(FAKE_DELAY, side_effect=_fake_delay):
        call_command("signoff_ceremony", "nfkb_axis_mmp_adamts", "fchemorion")

    nfkb_network.refresh_from_db()
    assert nfkb_network.pipeline_status == "verified"


@pytest.mark.django_db
def test_ceremony_enqueues_sbml_regenerate(nfkb_network, frozen_mv, curator, accepted_edge):
    """A successful ceremony calls sbml.tasks.regenerate.delay with triggered_by_curator=True."""
    calls: list[dict] = []

    def recording_delay(*args, **kwargs):
        calls.append({"args": args, "kwargs": kwargs})
        return type("AsyncResult", (), {"id": "fake-task"})()

    with patch(FAKE_DELAY, side_effect=recording_delay):
        call_command("signoff_ceremony", "nfkb_axis_mmp_adamts", "fchemorion")

    assert calls, "regenerate.delay was never called"
    assert calls[0]["kwargs"].get("triggered_by_curator") is True


@pytest.mark.django_db
def test_ceremony_prints_success_summary(nfkb_network, frozen_mv, curator, accepted_edge):
    """A successful ceremony prints the network code and a success indicator to stdout."""
    out = StringIO()

    with patch(FAKE_DELAY, side_effect=_fake_delay):
        call_command(
            "signoff_ceremony",
            "nfkb_axis_mmp_adamts",
            "fchemorion",
            stdout=out,
        )

    summary = out.getvalue()
    assert "nfkb_axis_mmp_adamts" in summary
    # Should mention the version or success
    assert "PASSED" in summary or "verified" in summary.lower()


@pytest.mark.django_db
def test_ceremony_dry_run_does_not_change_state(nfkb_network, frozen_mv, curator, accepted_edge):
    """--dry-run validates preconditions but creates no Signoff and leaves network unchanged."""
    from verify.models import Signoff

    with patch(FAKE_DELAY, side_effect=_fake_delay):
        call_command(
            "signoff_ceremony",
            "nfkb_axis_mmp_adamts",
            "fchemorion",
            dry_run=True,
        )

    # No state change
    nfkb_network.refresh_from_db()
    assert nfkb_network.pipeline_status == "version_draft"
    assert Signoff.objects.filter(network=nfkb_network).count() == 0


@pytest.mark.django_db
def test_ceremony_dry_run_prints_dry_run_output(nfkb_network, frozen_mv, curator, accepted_edge):
    """--dry-run prints a DRY RUN indicator and the target network/version."""
    out = StringIO()

    with patch(FAKE_DELAY, side_effect=_fake_delay):
        call_command(
            "signoff_ceremony",
            "nfkb_axis_mmp_adamts",
            "fchemorion",
            dry_run=True,
            stdout=out,
        )

    summary = out.getvalue()
    assert "DRY RUN" in summary.upper()
    assert "nfkb_axis_mmp_adamts" in summary
