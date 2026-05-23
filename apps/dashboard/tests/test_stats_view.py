"""Tests for /corpus/stats."""

from __future__ import annotations


def test_stats_view_returns_200(db, client, seed):
    resp = client.get("/corpus/stats")
    assert resp.status_code == 200


def test_stats_view_total_papers(db, client, seed):
    resp = client.get("/corpus/stats")
    assert b"3" in resp.content  # 3 total papers


def test_stats_view_original_vs_review_breakdown(db, client, seed):
    resp = client.get("/corpus/stats")
    body = resp.content.decode()
    assert "Original" in body or "original" in body
    assert "Review" in body or "review" in body


def test_stats_view_full_text_coverage(db, client, seed):
    resp = client.get("/corpus/stats")
    body = resp.content.decode()
    assert "pmc_jats" in body or "Full-text" in body or "full-text" in body


def test_stats_view_by_year(db, client, seed):
    resp = client.get("/corpus/stats")
    body = resp.content.decode()
    assert "2024" in body
    assert "2023" in body


def test_stats_view_by_journal(db, client, seed):
    resp = client.get("/corpus/stats")
    body = resp.content.decode()
    assert "Spine" in body
    assert "JOR" in body
