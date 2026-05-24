"""Tests for verify.tasks.sweep_open_conflicts."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from graph.models import Conflict
from verify.tasks import sweep_open_conflicts


def _make_conflict(resolution_status: str = "open", age_hours: int = 2) -> Conflict:
    """Helper: create a Conflict with controlled age."""
    from core.models import OntologyEntity
    from graph.models import Edge, Entity

    oe_a = OntologyEntity.objects.create(
        preferred_label=f"GeneA_{age_hours}_{resolution_status}",
        entity_type="gene",
        canonical_uri=f"https://ex/{age_hours}A",
    )
    oe_b = OntologyEntity.objects.create(
        preferred_label=f"GeneB_{age_hours}_{resolution_status}",
        entity_type="gene",
        canonical_uri=f"https://ex/{age_hours}B",
    )
    e_a = Entity.objects.create(ontology_entity=oe_a)
    e_b = Entity.objects.create(ontology_entity=oe_b)
    edge_a = Edge.objects.create(source=e_a, target=e_b, relation="activates")
    edge_b = Edge.objects.create(source=e_a, target=e_b, relation="inhibits")

    c = Conflict.objects.create(
        edge_a=edge_a,
        edge_b=edge_b,
        conflict_type="inter_paper",
        resolution_status=resolution_status,
    )
    # Backdate created_at via queryset update (auto_now_add prevents direct assignment)
    Conflict.objects.filter(id=c.id).update(created_at=timezone.now() - timedelta(hours=age_hours))
    return Conflict.objects.get(id=c.id)


@pytest.mark.django_db
class TestSweepOpenConflicts:
    @patch("verify.tasks.auto_resolve.delay")
    def test_aged_open_conflict_is_enqueued(self, mock_delay):
        aged = _make_conflict(resolution_status="open", age_hours=2)
        sweep_open_conflicts()
        mock_delay.assert_called_once_with(aged.id)

    @patch("verify.tasks.auto_resolve.delay")
    def test_fresh_open_conflict_is_skipped(self, mock_delay):
        _make_conflict(resolution_status="open", age_hours=0)
        sweep_open_conflicts()
        mock_delay.assert_not_called()

    @patch("verify.tasks.auto_resolve.delay")
    def test_already_resolved_conflict_is_skipped(self, mock_delay):
        _make_conflict(resolution_status="auto_resolved", age_hours=2)
        sweep_open_conflicts()
        mock_delay.assert_not_called()

    @patch("verify.tasks.auto_resolve.delay")
    def test_returns_count_dispatched(self, mock_delay):
        _make_conflict(resolution_status="open", age_hours=2)
        result = sweep_open_conflicts()
        assert result["dispatched"] == 1
