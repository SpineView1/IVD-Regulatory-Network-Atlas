"""Tests for corpus.views.export_csv."""

from __future__ import annotations

import csv
import io
from datetime import date

import pytest
from django.test import Client

from corpus.models import Paper, PaperRelevance
from networks.models import Network


@pytest.fixture
def client():
    return Client(HTTP_REMOTE_USER="fchemorion")


@pytest.fixture
def seed_corpus(db):
    n1 = Network.objects.create(code="nfkb_axis", category="I", title="NF-κB Axis")
    n2 = Network.objects.create(code="mechano_piezo", category="VIII", title="Piezo")
    p1 = Paper.objects.create(
        pmid=1,
        title="NF-kB paper",
        abstract="a",
        publication_date=date(2024, 5, 1),
        is_original=True,
        full_text_status="pmc_jats",
        ingest_status="chunked",
    )
    p2 = Paper.objects.create(
        pmid=2,
        title="Piezo paper",
        abstract="b",
        publication_date=date(2024, 4, 1),
        is_original=True,
        full_text_status="abstract_only",
        ingest_status="chunked",
    )
    p3 = Paper.objects.create(
        pmid=3,
        title="Review",
        abstract="c",
        is_original=False,
        full_text_status="none",
        ingest_status="classified",
    )
    PaperRelevance.objects.create(paper=p1, network=n1, score=0.92, classified_by="llm:qwen3:8b")
    PaperRelevance.objects.create(paper=p2, network=n2, score=0.85, classified_by="llm:qwen3:8b")
    PaperRelevance.objects.create(paper=p1, network=n2, score=0.10, classified_by="llm:qwen3:8b")
    return n1, n2, p1, p2, p3


def test_export_csv_returns_csv_content_type(db, client, seed_corpus):
    resp = client.get("/corpus/export.csv")
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("text/csv")


def test_export_csv_default_returns_all_papers(db, client, seed_corpus):
    resp = client.get("/corpus/export.csv")
    rows = list(csv.DictReader(io.StringIO(b"".join(resp.streaming_content).decode())))
    pmids = {int(r["pmid"]) for r in rows}
    assert pmids == {1, 2, 3}


def test_export_csv_full_format_includes_classifier_and_fulltext(db, client, seed_corpus):
    resp = client.get("/corpus/export.csv?format=full")
    rows = list(csv.DictReader(io.StringIO(b"".join(resp.streaming_content).decode())))
    headers = rows[0].keys()
    assert "is_original" in headers
    assert "full_text_status" in headers
    assert "publication_types" in headers
    assert "mesh_terms" in headers


def test_export_csv_network_filter(db, client, seed_corpus):
    resp = client.get("/corpus/export.csv?network=nfkb_axis")
    rows = list(csv.DictReader(io.StringIO(b"".join(resp.streaming_content).decode())))
    pmids = {int(r["pmid"]) for r in rows}
    # Only papers with relevance > 0.5 for the requested network.
    assert pmids == {1}


def test_export_csv_unknown_network_returns_400(db, client, seed_corpus):
    resp = client.get("/corpus/export.csv?network=does_not_exist")
    assert resp.status_code == 400


def test_export_csv_threshold_query_param(db, client, seed_corpus):
    resp = client.get("/corpus/export.csv?network=mechano_piezo&threshold=0.05")
    rows = list(csv.DictReader(io.StringIO(b"".join(resp.streaming_content).decode())))
    pmids = {int(r["pmid"]) for r in rows}
    assert pmids == {1, 2}  # both relevances above 0.05


def test_export_csv_filename_header(db, client, seed_corpus):
    resp = client.get("/corpus/export.csv")
    assert "attachment" in resp["Content-Disposition"]
    assert ".csv" in resp["Content-Disposition"]


def test_export_csv_network_filename_includes_code(db, client, seed_corpus):
    resp = client.get("/corpus/export.csv?network=nfkb_axis")
    assert "nfkb_axis" in resp["Content-Disposition"]
