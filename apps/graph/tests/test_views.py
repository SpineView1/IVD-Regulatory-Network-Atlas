"""Tests for graph dev UI views.

Task 14: dev network page + JSON edge endpoint.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from django.test import Client

# Module-level lookup table used by _fake_ground below.
_GROUND_TABLE: dict[str, Any] = {}


def _fake_ground(text: str) -> Any:
    return _GROUND_TABLE.get(text.strip().upper())


@pytest.fixture
def gilda_table(il1b_ontology_entity, nfkb1_ontology_entity):
    _GROUND_TABLE["IL1B"] = il1b_ontology_entity
    _GROUND_TABLE["NFKB1"] = nfkb1_ontology_entity
    yield
    _GROUND_TABLE.clear()


@pytest.fixture
def nfkb_network_with_edge(
    db,
    gilda_table,
    nfkb1_ontology_entity,
    paper_factory,
    chunk_factory,
    raw_ppi_factory,
):
    from graph.services import normalize_and_integrate
    from networks.models import Network

    network = Network.objects.create(
        code="nfkb_axis",
        title="NF-κB axis",
        category="I",
        root_entities=[{"scheme": "HGNC", "value": "7794"}],
        pipeline_status="idle",
    )
    paper = paper_factory(pmid="60001", year=2025)
    chunk = chunk_factory(paper=paper)
    with patch("graph.services.ground_mention", side_effect=_fake_ground):
        raw = raw_ppi_factory(
            subject="IL1B",
            object="NFKB1",
            relation="activates",
            chunk=chunk,
        )
        normalize_and_integrate([raw.pk])
    return network


@pytest.fixture
def authed_client() -> Client:
    return Client(HTTP_REMOTE_USER="fchemorion")


def test_dev_network_view_returns_200(db, nfkb_network_with_edge, authed_client):
    r = authed_client.get(f"/graph/dev/networks/{nfkb_network_with_edge.code}/")
    assert r.status_code == 200


def test_dev_network_view_contains_network_title(db, nfkb_network_with_edge, authed_client):
    r = authed_client.get(f"/graph/dev/networks/{nfkb_network_with_edge.code}/")
    assert b"NF-" in r.content


def test_dev_network_view_renders_cytoscape(db, nfkb_network_with_edge, authed_client):
    r = authed_client.get(f"/graph/dev/networks/{nfkb_network_with_edge.code}/")
    assert b"cytoscape" in r.content.lower()


def test_dev_network_view_404_on_missing_code(db, authed_client):
    r = authed_client.get("/graph/dev/networks/does_not_exist/")
    assert r.status_code == 404


def test_edges_json_endpoint_returns_edges(db, nfkb_network_with_edge, authed_client):
    r = authed_client.get(f"/graph/dev/networks/{nfkb_network_with_edge.code}/edges.json")
    assert r.status_code == 200
    data = r.json()
    assert "nodes" in data and "edges" in data
    assert len(data["edges"]) == 1
    e = data["edges"][0]
    assert e["data"]["source_label"] == "IL1B"
    assert e["data"]["target_label"] == "NFKB1"
    assert e["data"]["relation"] == "activates"
    assert "belief" in e["data"]
    assert "status" in e["data"]


def test_edges_json_includes_nodes_with_identifiers(db, nfkb_network_with_edge, authed_client):
    r = authed_client.get(f"/graph/dev/networks/{nfkb_network_with_edge.code}/edges.json")
    data = r.json()
    labels = {n["data"]["label"] for n in data["nodes"]}
    assert labels == {"IL1B", "NFKB1"}
    # Each node carries its primary identifier IRI
    for n in data["nodes"]:
        assert n["data"]["iri"].startswith("https://identifiers.org/hgnc:")
