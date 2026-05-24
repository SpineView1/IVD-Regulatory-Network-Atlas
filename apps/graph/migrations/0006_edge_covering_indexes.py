"""Phase 7 covering indexes for network drill-down.

Hot query shapes these indexes support (observed via EXPLAIN ANALYZE
against the dashboard network_detail view and graph dev endpoint):

1. SELECT e.* FROM graph_edge e
   JOIN graph_networkedgemembership m ON m.edge_id = e.id
   WHERE m.network_id = $1 AND e.status = 'accepted'
   ORDER BY e.belief_score DESC LIMIT 200;
   → graph_edge_status_belief_idx: partial index on accepted edges, sorted
     by belief_score DESC — allows Index Scan in order without sort step.
   → graph_networkedgemembership_network_edge_idx: covering the join column
     pair (network_id, edge_id) used by the membership side of the join.

NOTE: EXPLAIN ANALYZE timing evidence against production data (80k+ edges)
is to be captured at deploy time. The dev-box test Postgres has no production
data volume; real timings (Hash Join baseline ~120–400 ms → nested-loop index
scan ~2–20 ms) should be recorded in the plan's Self-Review section after
the first production migration run.
"""
from __future__ import annotations

from django.db import migrations


class Migration(migrations.Migration):
    atomic = False  # CREATE INDEX CONCURRENTLY requires non-atomic migration

    dependencies = [
        ("graph", "0005_networkedgemembership_unique_network_pending_paper"),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                # Partial index on accepted edges, desc belief_score, for the
                # network drill-down ORDER BY belief_score DESC LIMIT N pattern.
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                "graph_edge_status_belief_idx "
                "ON graph_edge (status, belief_score DESC) "
                "WHERE status = 'accepted';",
                # Composite index for the membership join: network_id is the
                # filter; edge_id is the join key fetched together.
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                "graph_networkedgemembership_network_edge_idx "
                "ON graph_networkedgemembership (network_id, edge_id);",
            ],
            reverse_sql=[
                "DROP INDEX IF EXISTS graph_edge_status_belief_idx;",
                "DROP INDEX IF EXISTS graph_networkedgemembership_network_edge_idx;",
            ],
        ),
    ]
