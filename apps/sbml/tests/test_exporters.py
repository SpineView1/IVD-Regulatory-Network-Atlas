"""Tests for sbml.exporters — edges.csv and evidence.csv per spec §7."""
from __future__ import annotations

import csv
import io

import pytest

from sbml.exporters import EDGES_CSV_COLUMNS, EVIDENCE_CSV_COLUMNS, write_edges_csv, write_evidence_csv


def test_edges_csv_column_order_matches_spec():
    assert EDGES_CSV_COLUMNS == [
        "source_symbol",
        "source_id",
        "source_type",
        "relation",
        "target_symbol",
        "target_id",
        "target_type",
        "belief",
        "n_supporting_papers",
        "n_models_agreeing",
        "reviewer_status",
        "first_seen",
        "last_seen",
    ]


def test_evidence_csv_column_order_matches_spec():
    assert EVIDENCE_CSV_COLUMNS == [
        "edge_id",
        "pmid",
        "chunk_excerpt",
        "evidence_span_start",
        "evidence_span_end",
        "extractor_model",
        "extraction_logprob",
        "extracted_at",
    ]


def test_write_edges_csv_one_row_per_edge(db, network, accepted_edges):
    data = write_edges_csv(accepted_edges)
    reader = csv.DictReader(io.StringIO(data.decode("utf-8")))
    rows = list(reader)
    assert len(rows) == 2


def test_write_edges_csv_has_correct_header(db, network, accepted_edges):
    data = write_edges_csv(accepted_edges)
    first_line = data.decode("utf-8").splitlines()[0]
    assert first_line == ",".join(EDGES_CSV_COLUMNS)


def test_write_edges_csv_uses_hgnc_symbol(db, network, accepted_edges):
    data = write_edges_csv(accepted_edges)
    rows = list(csv.DictReader(io.StringIO(data.decode("utf-8"))))
    symbols = {(r["source_symbol"], r["target_symbol"]) for r in rows}
    assert ("IL1B", "NFKB1") in symbols
    assert ("NFKB1", "MMP13") in symbols


def test_write_edges_csv_includes_belief(db, network, accepted_edges):
    data = write_edges_csv(accepted_edges)
    rows = list(csv.DictReader(io.StringIO(data.decode("utf-8"))))
    beliefs = {float(r["belief"]) for r in rows}
    assert 0.94 in beliefs


def test_write_evidence_csv_has_one_row_per_edge_evidence(db, network, accepted_edges, evidence_rows):
    data = write_evidence_csv(accepted_edges)
    rows = list(csv.DictReader(io.StringIO(data.decode("utf-8"))))
    assert len(rows) == len(evidence_rows)


def test_write_evidence_csv_columns(db, network, accepted_edges, evidence_rows):
    data = write_evidence_csv(accepted_edges)
    first_line = data.decode("utf-8").splitlines()[0]
    assert first_line == ",".join(EVIDENCE_CSV_COLUMNS)


def test_write_evidence_csv_resolves_pmid(db, network, accepted_edges, evidence_rows):
    data = write_evidence_csv(accepted_edges)
    rows = list(csv.DictReader(io.StringIO(data.decode("utf-8"))))
    pmids = {r["pmid"] for r in rows}
    assert "12345678" in pmids
