"""TDD: Phase 7 covering indexes for corpus dashboard hot paths.

Tests assert that the indexes created by migration
0002_paper_covering_indexes exist in the database after migrate runs.
They also verify that the hot queries still return correct results
after the indexes are added.

EXPLAIN ANALYZE timings against production data (40k+ papers, 80k+ edges)
are to be captured at deploy time — not fabricated here. The dev-box
test Postgres has no production data volume, so only correctness is
asserted here.
"""
from __future__ import annotations

import pytest
from django.db import connection


@pytest.mark.django_db
def test_covering_index_corpus_paper_isoriginal_pubdate_exists() -> None:
    """corpus_paper_isoriginal_pubdate_idx must exist after migration."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT indexname
            FROM pg_indexes
            WHERE tablename = 'corpus_paper'
              AND indexname = 'corpus_paper_isoriginal_pubdate_idx'
            """
        )
        row = cursor.fetchone()
    assert row is not None, (
        "Index corpus_paper_isoriginal_pubdate_idx not found — "
        "migration 0002_paper_covering_indexes may not have run."
    )


@pytest.mark.django_db
def test_covering_index_corpus_paper_fulltextstatus_pubdate_exists() -> None:
    """corpus_paper_fulltextstatus_pubdate_idx must exist after migration."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT indexname
            FROM pg_indexes
            WHERE tablename = 'corpus_paper'
              AND indexname = 'corpus_paper_fulltextstatus_pubdate_idx'
            """
        )
        row = cursor.fetchone()
    assert row is not None, (
        "Index corpus_paper_fulltextstatus_pubdate_idx not found — "
        "migration 0002_paper_covering_indexes may not have run."
    )


@pytest.mark.django_db
def test_stats_query_returns_correct_year_counts(db) -> None:
    """The corpus stats hot query groups by year for is_original=True papers.

    Verifies the query shape still returns correct counts after the covering
    index is applied.
    """
    from datetime import date

    from django.db.models import Count
    from django.db.models.functions import ExtractYear

    from corpus.models import Paper

    Paper.objects.create(
        pmid=100001,
        title="IDD paper A",
        publication_date=date(2022, 3, 1),
        is_original=True,
        ingest_status="classified",
    )
    Paper.objects.create(
        pmid=100002,
        title="IDD paper B",
        publication_date=date(2022, 8, 1),
        is_original=True,
        ingest_status="classified",
    )
    Paper.objects.create(
        pmid=100003,
        title="Review paper",
        publication_date=date(2022, 5, 1),
        is_original=False,
        ingest_status="classified",
    )

    by_year = list(
        Paper.objects.filter(is_original=True)
        .exclude(publication_date__isnull=True)
        .annotate(year=ExtractYear("publication_date"))
        .values("year")
        .annotate(n=Count("pmid"))
        .order_by("-year")
    )

    assert len(by_year) == 1
    assert by_year[0]["year"] == 2022
    assert by_year[0]["n"] == 2


@pytest.mark.django_db
def test_fulltext_breakdown_query_returns_counts(db) -> None:
    """full_text_status breakdown query returns correct counts."""
    from django.db.models import Count

    from corpus.models import Paper

    Paper.objects.create(
        pmid=200001,
        title="Paper with PMC",
        full_text_status="pmc_jats",
        ingest_status="ingested",
    )
    Paper.objects.create(
        pmid=200002,
        title="Paper without full text",
        full_text_status="none",
        ingest_status="ingested",
    )

    breakdown = list(Paper.objects.values("full_text_status").annotate(n=Count("pmid")))
    statuses = {row["full_text_status"]: row["n"] for row in breakdown}

    assert statuses.get("pmc_jats", 0) >= 1
    assert statuses.get("none", 0) >= 1
