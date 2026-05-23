"""Tests for the canonical IDD PubMed query."""

from __future__ import annotations

from datetime import date

from corpus.pubmed_query import (
    MASTER_IDD_QUERY,
    build_incremental_query,
)


def test_master_query_includes_mesh_terms():
    assert '"Intervertebral Disc"[MeSH]' in MASTER_IDD_QUERY
    assert '"Intervertebral Disc Degeneration"[MeSH]' in MASTER_IDD_QUERY
    assert '"Intervertebral Disc Displacement"[MeSH]' in MASTER_IDD_QUERY
    assert '"Nucleus Pulposus"[MeSH]' in MASTER_IDD_QUERY


def test_master_query_includes_tiab_terms():
    assert '"intervertebral disc"[TIAB]' in MASTER_IDD_QUERY
    assert '"intervertebral disk"[TIAB]' in MASTER_IDD_QUERY
    assert '"nucleus pulposus"[TIAB]' in MASTER_IDD_QUERY
    assert '"annulus fibrosus"[TIAB]' in MASTER_IDD_QUERY
    assert '"disc degeneration"[TIAB]' in MASTER_IDD_QUERY
    assert '"disc herniation"[TIAB]' in MASTER_IDD_QUERY
    assert '"cartilage endplate"[TIAB]' in MASTER_IDD_QUERY
    assert '"spinal disc"[TIAB]' in MASTER_IDD_QUERY


def test_master_query_language_and_date_filters():
    assert "English[Language]" in MASTER_IDD_QUERY
    assert '("1980"[PDAT] : "3000"[PDAT])' in MASTER_IDD_QUERY


def test_build_incremental_query_includes_mindate():
    q = build_incremental_query(since=date(2024, 5, 1))
    assert "2024/05/01" in q
    assert "EDAT" in q


def test_build_incremental_query_uses_overlap_window():
    q = build_incremental_query(since=date(2024, 5, 8), overlap_days=7)
    # 8th minus 7 days = 1st
    assert "2024/05/01" in q


def test_build_incremental_query_none_since_returns_master():
    q = build_incremental_query(since=None)
    assert q == MASTER_IDD_QUERY
