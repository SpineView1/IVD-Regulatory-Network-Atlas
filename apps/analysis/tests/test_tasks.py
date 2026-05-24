"""Tests for analysis.tasks: project_edges + reconcile_neo4j (FakeGraphBackend)."""

from __future__ import annotations

from unittest.mock import patch

import pytest


@pytest.fixture
def patch_backend(fake_backend):
    """Make get_backend() return the shared in-memory fake."""
    with patch("analysis.tasks.get_backend", return_value=fake_backend):
        yield fake_backend


def test_project_edges_projects_accepted_edge(db, accepted_edge, patch_backend):
    from analysis.tasks import project_edges

    project_edges([accepted_edge.id])
    assert patch_backend.count_edges() == 1


def test_project_edges_is_idempotent(db, accepted_edge, patch_backend):
    from analysis.tasks import project_edges

    project_edges([accepted_edge.id])
    project_edges([accepted_edge.id])
    assert patch_backend.count_edges() == 1


def test_project_edges_removes_now_rejected_edge(db, accepted_edge, patch_backend):
    from analysis.tasks import project_edges

    project_edges([accepted_edge.id])
    accepted_edge.status = "rejected"
    accepted_edge.save(update_fields=["status"])
    project_edges([accepted_edge.id])
    assert patch_backend.count_edges() == 0


def test_reconcile_adds_missing_edges(db, accepted_edge, patch_backend):
    from analysis.tasks import reconcile_neo4j

    # Backend starts empty; Postgres has one accepted edge.
    assert patch_backend.count_edges() == 0
    result = reconcile_neo4j()
    assert patch_backend.count_edges() == 1
    assert result["added"] == 1
    assert result["removed"] == 0


def test_reconcile_removes_orphaned_edges(db, accepted_edge, patch_backend):
    from analysis.projection import project_edge_ids
    from analysis.tasks import reconcile_neo4j

    project_edge_ids([accepted_edge.id], backend=patch_backend)
    # Edge rejected in Postgres but still present in the read-model.
    accepted_edge.status = "rejected"
    accepted_edge.save(update_fields=["status"])
    result = reconcile_neo4j()
    assert patch_backend.count_edges() == 0
    assert result["removed"] == 1


def test_reconcile_rebuild_from_scratch(db, accepted_edge, patch_backend):
    from analysis.tasks import reconcile_neo4j

    # Simulate Neo4j loss: backend already cleared (empty). Full rebuild path.
    result = reconcile_neo4j(rebuild=True)
    assert patch_backend.count_edges() == 1
    assert result["added"] == 1


def test_project_edges_returns_projection_stats(db, accepted_edge, patch_backend):
    from analysis.tasks import project_edges

    result = project_edges([accepted_edge.id])
    assert result["projected"] == 1
    assert result["removed"] == 0


def test_reconcile_idempotent_when_already_in_sync(db, accepted_edge, patch_backend):
    from analysis.projection import project_edge_ids
    from analysis.tasks import reconcile_neo4j

    # Pre-project so backend already has the edge.
    project_edge_ids([accepted_edge.id], backend=patch_backend)
    result = reconcile_neo4j()
    # Nothing to add, nothing to remove.
    assert result["added"] == 0
    assert result["removed"] == 0
    assert patch_backend.count_edges() == 1
