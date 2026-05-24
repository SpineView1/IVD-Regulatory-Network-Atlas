"""Tests for graph.curation_export — biologist per-network curation CSV."""

from __future__ import annotations

import csv
import io

import pytest

from graph.curation_export import (
    CURATION_CSV_COLUMNS,
    network_curation_rows,
    write_network_curation_csv,
)


@pytest.fixture
def network(db):
    from networks.models import Network

    return Network.objects.create(
        code="nfkb_axis",
        title="NF-κB axis",
        category="I",
        root_entities=[{"scheme": "HGNC", "value": "7794"}],
        pipeline_status="idle",
    )


@pytest.fixture
def edge_with_evidence(db, il1b_ontology_entity, nfkb1_ontology_entity, network, chunk_factory):
    """An IL1B→NFKB1 edge supported by one RawPPI carrying the V2 fields."""
    from extract.models import ExtractionRun, RawPPI
    from graph.models import Edge, EdgeEvidence, Entity, NetworkEdgeMembership

    src = Entity.objects.create(ontology_entity=il1b_ontology_entity)
    tgt = Entity.objects.create(ontology_entity=nfkb1_ontology_entity)
    edge = Edge.objects.create(
        source=src, target=tgt, relation="activates", belief_score=0.57, status="accepted"
    )
    NetworkEdgeMembership.objects.create(network=network, edge=edge, relevance=1.0)

    chunk = chunk_factory(text="IL-1β activates NF-κB in degenerated human NP cells.")
    run = ExtractionRun.objects.create(
        chunk=chunk, model_name="qwen3:8b", prompt_version="2.0.0", status="done"
    )
    rp = RawPPI.objects.create(
        run=run,
        subject="IL1B",
        object="NFKB1",
        relation="activates",
        evidence_span=chunk.text,
        evidence_offset_start=0,
        evidence_offset_end=len(chunk.text),
        cell_type="nucleus pulposus",
        species="human",
        deg_status="DEG",
        stimulus="IL-1β stimulation",
        confidence=0.9,
    )
    EdgeEvidence.objects.create(edge=edge, raw_ppi=rp)
    return edge


def test_columns_match_curation_spec():
    assert CURATION_CSV_COLUMNS == [
        "STIMULI",
        "RELATION",
        "RESPONSE",
        "PATHWAY INVOLVED",
        "TYPE OF CELLS",
        "DEG/NON-DEG",
        "COMMENTS",
        "REFERENCE",
    ]


def test_row_maps_fields_correctly(db, network, edge_with_evidence):
    rows = network_curation_rows(network)
    assert len(rows) == 1
    row = rows[0]
    assert row["STIMULI"] == "IL1B"
    assert row["RELATION"] == "activates"
    assert row["RESPONSE"] == "NFKB1"
    assert row["PATHWAY INVOLVED"] == "NF-κB axis"
    # species folded into TYPE OF CELLS
    assert row["TYPE OF CELLS"] == "human · nucleus pulposus"
    assert row["DEG/NON-DEG"] == "DEG"
    assert "IL-1β stimulation" in row["COMMENTS"]
    assert "qwen3:8b" in row["COMMENTS"]
    assert row["REFERENCE"].startswith("PMID:")


def test_csv_bytes_have_header_and_row(db, network, edge_with_evidence):
    payload = write_network_curation_csv(network)
    text = payload.decode("utf-8")
    reader = list(csv.reader(io.StringIO(text)))
    assert reader[0] == CURATION_CSV_COLUMNS
    assert len(reader) == 2  # header + one data row
    assert reader[1][0] == "IL1B"


def test_empty_network_yields_header_only(db, network):
    payload = write_network_curation_csv(network)
    reader = list(csv.reader(io.StringIO(payload.decode("utf-8"))))
    assert reader == [CURATION_CSV_COLUMNS]


def test_missing_v2_fields_render_blank(
    db, il1b_ontology_entity, nfkb1_ontology_entity, network, chunk_factory
):
    """An edge whose evidence predates V2 (no species/deg_status) still
    exports — those columns are just blank."""
    from extract.models import ExtractionRun, RawPPI
    from graph.models import Edge, EdgeEvidence, Entity, NetworkEdgeMembership

    src = Entity.objects.create(ontology_entity=il1b_ontology_entity)
    tgt = Entity.objects.create(ontology_entity=nfkb1_ontology_entity)
    edge = Edge.objects.create(source=src, target=tgt, relation="inhibits", belief_score=0.4)
    NetworkEdgeMembership.objects.create(network=network, edge=edge, relevance=1.0)
    chunk = chunk_factory(text="IL1B inhibits NFKB1.")
    run = ExtractionRun.objects.create(
        chunk=chunk, model_name="qwen3:8b", prompt_version="1.0.0", status="done"
    )
    rp = RawPPI.objects.create(
        run=run,
        subject="IL1B",
        object="NFKB1",
        relation="inhibits",
        evidence_span=chunk.text,
        evidence_offset_start=0,
        evidence_offset_end=len(chunk.text),
        confidence=0.7,
    )
    EdgeEvidence.objects.create(edge=edge, raw_ppi=rp)

    row = network_curation_rows(network)[0]
    assert row["TYPE OF CELLS"] == ""
    assert row["DEG/NON-DEG"] == ""
    # candidate (non-accepted) status is surfaced in COMMENTS
    assert "status: candidate" in row["COMMENTS"]
