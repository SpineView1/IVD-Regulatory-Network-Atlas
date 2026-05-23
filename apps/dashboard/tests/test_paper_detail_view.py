"""Tests for /corpus/paper/<pmid>."""

from __future__ import annotations


def test_paper_detail_returns_200_for_existing(db, client, seed):
    resp = client.get("/corpus/paper/1")
    assert resp.status_code == 200


def test_paper_detail_404_for_missing(db, client, seed):
    resp = client.get("/corpus/paper/99999")
    assert resp.status_code == 404


def test_paper_detail_shows_title(db, client, seed):
    resp = client.get("/corpus/paper/1")
    assert b"2024 paper A" in resp.content


def test_paper_detail_shows_relevances(db, client, seed):
    resp = client.get("/corpus/paper/1")
    body = resp.content.decode()
    assert "nfkb_axis" in body or "NF-κB" in body or "NF-kB" in body


def test_paper_detail_shows_full_text_status(db, client, seed):
    resp = client.get("/corpus/paper/1")
    body = resp.content.decode()
    assert "pmc_jats" in body or "Full-text" in body or "full-text" in body
