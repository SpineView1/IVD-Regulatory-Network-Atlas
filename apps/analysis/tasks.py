"""analysis Celery tasks — incremental projection + nightly reconciliation.

Postgres is the system of record. project_edges reflects a batch of edges
into the Neo4j read-model; reconcile_neo4j sweeps the whole accepted-edge set
(nightly Beat) and is also the rebuild-from-scratch path after Neo4j loss.
"""

from __future__ import annotations

import logging

from analysis.backends import get_backend
from analysis.projection import accepted_edge_ids, project_edge_ids
from celery import shared_task

logger = logging.getLogger(__name__)

RECONCILE_CHUNK = 500


@shared_task(name="analysis.tasks.project_edges")
def project_edges(edge_ids: list[int]) -> dict:
    """Incrementally reflect the given edges into the read-model.

    Idempotent. Accepted edges are MERGEd; non-accepted (rejected/conflicted/
    candidate) edges have their relationship DELETEd. Called by the
    edges_integrated signal receiver after each integration batch.
    """
    backend = get_backend()
    backend.ensure_constraints()
    result = project_edge_ids(edge_ids, backend=backend)
    logger.info("project_edges: %s", result)
    return result


@shared_task(name="analysis.tasks.reconcile_neo4j")
def reconcile_neo4j(rebuild: bool = False) -> dict:
    """Diff Postgres accepted-edge set vs the read-model; converge them.

    * rebuild=False (nightly Beat): add edges present in Postgres but missing
      from Neo4j; remove relationships orphaned in Neo4j; prune dangling nodes.
    * rebuild=True (after Neo4j loss): clear the read-model first, then project
      the entire accepted-edge set. This is the "pull the plug" guarantee —
      Neo4j is fully reconstructable from Postgres.
    """
    backend = get_backend()
    backend.ensure_constraints()

    pg_ids = accepted_edge_ids()

    if rebuild:
        backend.clear_all()
        backend.ensure_constraints()
        present: set[int] = set()
    else:
        present = backend.all_edge_ids()

    missing = pg_ids - present
    orphaned = present - pg_ids

    # Add missing (chunked to avoid giant transactions).
    missing_list = sorted(missing)
    for i in range(0, len(missing_list), RECONCILE_CHUNK):
        project_edge_ids(missing_list[i : i + RECONCILE_CHUNK], backend=backend)

    # Remove orphaned relationships.
    for edge_id in orphaned:
        backend.delete_edge(edge_id)

    pruned = backend.prune_orphan_entities()

    result = {
        "added": len(missing),
        "removed": len(orphaned),
        "pruned": pruned,
        "rebuild": rebuild,
    }
    logger.info("reconcile_neo4j: %s", result)
    return result
