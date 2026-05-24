"""Phase 7 covering index for the review-queue (pending sign-off reminders).

Hot query shape supported (from verify.tasks.remind_pending_signoffs):

  SELECT ra.* FROM verify_reviewassignment ra
  JOIN networks_network n ON n.id = ra.network_id
  WHERE ra.role = 'curator'
    AND n.pipeline_status IN ('version_draft', 'stale');

The index covers (network_id, role) with a partial predicate on
role = 'curator', keeping the index lean and enabling an index scan on
the most selective column pair for the curator-reminder task.

NOTE: EXPLAIN ANALYZE timing evidence against production data is to be
captured at deploy time. The dev-box test Postgres has no production data;
real timings should be recorded in the plan's Self-Review section after the
first production migration run.
"""

from __future__ import annotations

from django.db import migrations


class Migration(migrations.Migration):
    atomic = False  # CREATE INDEX CONCURRENTLY requires non-atomic migration

    dependencies = [
        ("verify", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                # Partial index covering (network_id, role) for curator lookups.
                # The WHERE clause filters to the only role that the pending-reminders
                # task queries, keeping the index small.
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                "verify_reviewassignment_network_role_idx "
                "ON verify_reviewassignment (network_id, role) "
                "WHERE role = 'curator';",
            ],
            reverse_sql=[
                "DROP INDEX IF EXISTS verify_reviewassignment_network_role_idx;",
            ],
        ),
    ]
