"""Live Neo4j integration tests.

Skipped automatically when NEO4J_URI is unset (the neo4j_backend fixture in
conftest.py calls pytest.skip). Run locally with:

    NEO4J_URI=bolt://localhost:7687 NEO4J_USER=neo4j \\
    NEO4J_PASSWORD=<pw> poetry run pytest -m neo4j -v

These verify the real driver + a real GDS PageRank call against the docker
neo4j service — the part FakeGraphBackend cannot exercise.
"""

from __future__ import annotations

import pytest


@pytest.mark.neo4j
def test_real_projection_and_counts(db, accepted_edge, neo4j_backend, settings):
    from analysis.projection import project_edge_ids

    project_edge_ids([accepted_edge.id], backend=neo4j_backend)
    assert neo4j_backend.count_entities() == 2
    assert neo4j_backend.count_edges() == 1
    assert neo4j_backend.all_edge_ids() == {accepted_edge.id}


@pytest.mark.neo4j
def test_real_projection_is_idempotent(db, accepted_edge, neo4j_backend):
    from analysis.projection import project_edge_ids

    project_edge_ids([accepted_edge.id], backend=neo4j_backend)
    project_edge_ids([accepted_edge.id], backend=neo4j_backend)
    assert neo4j_backend.count_edges() == 1


@pytest.mark.neo4j
def test_real_delete_on_reject(db, accepted_edge, neo4j_backend):
    from analysis.projection import project_edge_ids

    project_edge_ids([accepted_edge.id], backend=neo4j_backend)
    accepted_edge.status = "rejected"
    accepted_edge.save(update_fields=["status"])
    project_edge_ids([accepted_edge.id], backend=neo4j_backend)
    assert neo4j_backend.count_edges() == 0


@pytest.mark.neo4j
def test_real_gds_pagerank_runs(db, accepted_edge, neo4j_backend):
    """Exercise a real GDS projection + PageRank stream end-to-end."""
    from analysis.projection import project_edge_ids

    project_edge_ids([accepted_edge.id], backend=neo4j_backend)
    ranked = neo4j_backend.centrality(network=None, measure="pagerank")
    assert len(ranked) == 2
    assert all("score" in r and "symbol" in r for r in ranked)


@pytest.mark.neo4j
def test_real_neighborhood_query(db, accepted_edge, neo4j_backend):
    from analysis.projection import project_edge_ids

    project_edge_ids([accepted_edge.id], backend=neo4j_backend)
    out = neo4j_backend.neighborhood(entity_pg_id=accepted_edge.source_id, k=1)
    labels = {n["data"]["label"] for n in out["nodes"]}
    assert labels == {"IL1B", "NFKB1"}
