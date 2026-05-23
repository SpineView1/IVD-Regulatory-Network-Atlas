"""Tests for graph.tasks.integrate_pending.

Uses canonical field names per reconciliation doc:
  - raw_ppi_factory uses: subject=, object=, model_name=
  - Pending detection: ungrounded=False + no EdgeEvidence row + run.status='done'
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from graph.models import Edge, EdgeEvidence
from graph.tasks import integrate_pending


def _fake_ground(text: str) -> object | None:
    return _fake_ground.table.get(text.strip().upper())  # type: ignore[attr-defined]


_fake_ground.table = {}  # type: ignore[attr-defined]


@pytest.fixture
def gilda_table(il1b_ontology_entity, nfkb1_ontology_entity):
    _fake_ground.table = {  # type: ignore[attr-defined]
        "IL1B": il1b_ontology_entity,
        "NFKB1": nfkb1_ontology_entity,
    }
    yield
    _fake_ground.table = {}  # type: ignore[attr-defined]


@patch("graph.services.ground_mention", side_effect=_fake_ground)
def test_integrate_pending_processes_unintegrated_raw_ppis(
    mock_ground,
    db,
    gilda_table,
    paper_factory,
    chunk_factory,
    raw_ppi_factory,
    settings,
):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    paper = paper_factory(pmid="50001", year=2025)
    chunk = chunk_factory(paper=paper)
    raw_ppi_factory(
        subject="IL1B",
        object="NFKB1",
        relation="activates",
        chunk=chunk,
    )

    integrate_pending.delay()

    assert Edge.objects.count() == 1


@patch("graph.services.ground_mention", side_effect=_fake_ground)
def test_integrate_pending_skips_already_integrated(
    mock_ground,
    db,
    gilda_table,
    paper_factory,
    chunk_factory,
    raw_ppi_factory,
    settings,
):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    paper = paper_factory(pmid="50002", year=2025)
    chunk = chunk_factory(paper=paper)
    raw_ppi_factory(
        subject="IL1B",
        object="NFKB1",
        relation="activates",
        chunk=chunk,
    )

    integrate_pending.delay()
    edge_count_before = Edge.objects.count()
    evidence_count_before = EdgeEvidence.objects.count()

    integrate_pending.delay()
    assert Edge.objects.count() == edge_count_before
    assert EdgeEvidence.objects.count() == evidence_count_before


@patch("graph.services.ground_mention", side_effect=_fake_ground)
def test_integrate_pending_respects_batch_size(
    mock_ground,
    db,
    gilda_table,
    paper_factory,
    chunk_factory,
    raw_ppi_factory,
    settings,
):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    paper = paper_factory(pmid="50003", year=2025)
    chunk = chunk_factory(paper=paper)
    # 75 raw PPIs; default batch size 50 → first call integrates 50, second 25
    for i in range(75):
        raw_ppi_factory(
            subject="IL1B",
            object="NFKB1",
            relation="activates",
            chunk=chunk,
            model_name=f"model_{i % 7}",
        )

    # First sweep
    integrate_pending.delay()
    assert EdgeEvidence.objects.count() == 50

    # Second sweep
    integrate_pending.delay()
    assert EdgeEvidence.objects.count() == 75


@patch("graph.services.ground_mention", side_effect=_fake_ground)
def test_integrate_pending_skips_ungrounded(
    mock_ground,
    db,
    gilda_table,
    paper_factory,
    chunk_factory,
    raw_ppi_factory,
    settings,
):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    paper = paper_factory(pmid="50004", year=2025)
    chunk = chunk_factory(paper=paper)
    raw = raw_ppi_factory(
        subject="UnknownXYZ",
        object="NFKB1",
        relation="activates",
        chunk=chunk,
    )

    integrate_pending.delay()  # first pass marks it ungrounded
    raw.refresh_from_db()
    assert raw.ungrounded is True

    # Second pass: no work to do (ungrounded=True is excluded from pending)
    integrate_pending.delay()
    assert Edge.objects.count() == 0


def test_beat_schedule_has_integrate_pending_entry(settings):
    """integrate_pending must appear in CELERY_BEAT_SCHEDULE routed to q.io."""
    schedule = getattr(settings, "CELERY_BEAT_SCHEDULE", {})
    entry = schedule.get("graph-integrate-pending")
    assert entry is not None, "Missing 'graph-integrate-pending' Beat schedule entry"
    assert entry["task"] == "graph.integrate_pending"
    assert entry["options"]["queue"] == "q.io"
    # 10 minutes = 600 seconds
    assert entry["schedule"] == 600
