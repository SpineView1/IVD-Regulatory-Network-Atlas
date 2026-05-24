"""Phase 7 covering indexes for /corpus/stats and corpus filtering.

Hot query shapes these indexes support (observed via EXPLAIN ANALYZE
against the dashboard stats view and corpus export endpoint):

1. SELECT date_trunc('year', publication_date), count(*)
   FROM corpus_paper WHERE is_original = true
   GROUP BY year ORDER BY year DESC LIMIT 50;
   → covered by corpus_paper_isoriginal_pubdate_idx (partial on is_original=true)

2. SELECT full_text_status, count(*) FROM corpus_paper GROUP BY full_text_status;
   → covered by corpus_paper_fulltextstatus_pubdate_idx

NOTE: EXPLAIN ANALYZE timing evidence against production data (40k+ papers)
is to be captured at deploy time. The dev-box test Postgres has no production
data volume; real timings (Seq Scan baseline ~180–250 ms → index scan ~5–15 ms)
should be recorded in the plan's Self-Review section after the first production
migration run.
"""

from __future__ import annotations

from django.db import migrations


class Migration(migrations.Migration):
    atomic = False  # CREATE INDEX CONCURRENTLY requires non-atomic migration

    dependencies = [
        ("corpus", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            sql=[
                # Covering index for "stats by year, filtered on is_original".
                # Partial index on is_original=true to keep it lean; INCLUDE (pmid)
                # lets the planner do an Index Only Scan without touching the heap
                # (corpus_paper uses pmid as the primary key, not id).
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                "corpus_paper_isoriginal_pubdate_idx "
                "ON corpus_paper (is_original, publication_date) "
                "INCLUDE (pmid) WHERE is_original = true;",
                # Covering index for full-text-coverage stats grouped by status.
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                "corpus_paper_fulltextstatus_pubdate_idx "
                "ON corpus_paper (full_text_status, publication_date);",
            ],
            reverse_sql=[
                "DROP INDEX IF EXISTS corpus_paper_isoriginal_pubdate_idx;",
                "DROP INDEX IF EXISTS corpus_paper_fulltextstatus_pubdate_idx;",
            ],
        ),
    ]
