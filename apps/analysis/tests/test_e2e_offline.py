"""End-to-end offline test for the full Phase 8 pipeline.

Walks the complete loop without a live Neo4j instance:
  1. Seed 3 accepted edges across 2 networks in Postgres.
  2. Run project_edges (via tasks) with a FakeGraphBackend injected.
  3. Assert the fake backend has all projected nodes and relationships.
  4. Call services (crosstalk_edges, centrality, feedback_loops) and
     assert sane results.
  5. Hit the explorer JSON endpoints via the Django test client and
     assert Cytoscape element shape ({"data": {...}} for each element).

This test MUST pass in scripts/verify.sh (no live services required).
It is NOT gated by @pytest.mark.neo4j.
"""

from __future__ import annotations

import pytest
from django.test import Client
from unittest.mock import patch

from analysis.backends.fake import FakeGraphBackend


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def two_network_atlas(db):
    """Seed two networks (nfkb, sirt) sharing an entity (NFKB1) via 3 edges.

    Network nfkb:  IL1B(1) --activates--> NFKB1(2) --activates--> MMP3(3)
    Network sirt:  SIRT1(4) --inhibits--> NFKB1(2)
    Mutual inhibition (double-negative): NFKB1(2) --inhibits--> SIRT1(4)

    The last two edges (SIRT1->NFKB1 and NFKB1->SIRT1) form a 2-cycle and
    bridge the two networks — a double-negative toggle.
    """
    from core.models import Identifier, OntologyEntity
    from graph.models import Edge, Entity, NetworkEdgeMembership
    from networks.models import Network

    def make_entity(pg_hint, label, etype, scheme, value, uri):
        oe = OntologyEntity.objects.create(
            entity_type=etype,
            preferred_label=label,
            canonical_uri=uri,
            compartment="cytoplasm",
        )
        Identifier.objects.create(entity=oe, scheme=scheme, value=value)
        return Entity.objects.create(ontology_entity=oe)

    il1b = make_entity(1, "IL1B", "protein", "HGNC", "5992", "https://identifiers.org/hgnc:5992")
    nfkb1 = make_entity(2, "NFKB1", "protein", "HGNC", "7794", "https://identifiers.org/hgnc:7794")
    mmp3 = make_entity(3, "MMP3", "protein", "HGNC", "7173", "https://identifiers.org/hgnc:7173")
    sirt1 = make_entity(4, "SIRT1", "protein", "HGNC", "14929", "https://identifiers.org/hgnc:14929")

    net_nfkb = Network.objects.create(
        code="nfkb",
        title="NF-kB axis",
        category="I",
        root_entities=[{"scheme": "HGNC", "value": "7794"}],
        pipeline_status="idle",
    )
    net_sirt = Network.objects.create(
        code="sirt",
        title="Sirtuin axis",
        category="III",
        root_entities=[{"scheme": "HGNC", "value": "14929"}],
        pipeline_status="idle",
    )

    def make_edge(src, tgt, relation, nets, belief=0.8, papers=2, models=3):
        edge = Edge.objects.create(
            source=src,
            target=tgt,
            relation=relation,
            belief_score=belief,
            n_supporting_papers=papers,
            n_models_agreeing=models,
            status="accepted",
        )
        for net in nets:
            NetworkEdgeMembership.objects.create(network=net, edge=edge, relevance=1.0)
        return edge

    e1 = make_edge(il1b, nfkb1, "activates", [net_nfkb])
    e2 = make_edge(nfkb1, mmp3, "activates", [net_nfkb])
    e3 = make_edge(sirt1, nfkb1, "inhibits", [net_sirt])
    e4 = make_edge(nfkb1, sirt1, "inhibits", [net_nfkb])  # completes double-negative with e3

    return {
        "edges": [e1, e2, e3, e4],
        "entities": {"il1b": il1b, "nfkb1": nfkb1, "mmp3": mmp3, "sirt1": sirt1},
        "networks": {"nfkb": net_nfkb, "sirt": net_sirt},
    }


@pytest.fixture
def e2e_backend(two_network_atlas):
    """A FakeGraphBackend with all 4 edges projected via project_edges task."""
    backend = FakeGraphBackend()
    edge_ids = [e.id for e in two_network_atlas["edges"]]

    with patch("analysis.tasks.get_backend", return_value=backend):
        from analysis.tasks import project_edges

        project_edges(edge_ids)

    return backend


@pytest.fixture
def e2e_client(e2e_backend):
    """Django test client with e2e_backend injected into all services calls."""
    with patch("analysis.services.get_backend", return_value=e2e_backend):
        yield Client(HTTP_REMOTE_USER="fchemorion")


# ---------------------------------------------------------------------------
# Step 2+3: projection assertions
# ---------------------------------------------------------------------------


def test_e2e_projection_creates_all_entities(two_network_atlas, e2e_backend):
    """project_edges writes all 4 entity nodes into the backend."""
    assert e2e_backend.count_entities() == 4


def test_e2e_projection_creates_all_edges(two_network_atlas, e2e_backend):
    """project_edges writes all 4 REGULATES relationships into the backend."""
    assert e2e_backend.count_edges() == 4


def test_e2e_projection_sets_network_memberships(two_network_atlas, e2e_backend):
    """Entities are linked to the correct networks."""
    # NFKB1 appears in both networks (nfkb via e1/e2/e4, sirt via e3)
    nfkb1_id = two_network_atlas["entities"]["nfkb1"].id
    networks_of_nfkb1 = {c for (e, c) in e2e_backend._in_network if e == nfkb1_id}
    assert "nfkb" in networks_of_nfkb1
    assert "sirt" in networks_of_nfkb1


def test_e2e_projection_idempotent_on_reconcile(two_network_atlas, e2e_backend):
    """Running reconcile_neo4j after projection adds 0 and removes 0."""
    with patch("analysis.tasks.get_backend", return_value=e2e_backend):
        from analysis.tasks import reconcile_neo4j

        result = reconcile_neo4j()
    assert result["added"] == 0
    assert result["removed"] == 0
    assert e2e_backend.count_edges() == 4


# ---------------------------------------------------------------------------
# Step 4: services assertions
# ---------------------------------------------------------------------------


def test_e2e_crosstalk_edges_between_networks(two_network_atlas, e2e_backend):
    """crosstalk_edges returns the bridging edges between nfkb and sirt."""
    import analysis.services as services

    with patch.object(services, "get_backend", return_value=e2e_backend):
        result = services.crosstalk_edges(network_a="nfkb", network_b="sirt")

    edge_ids = {e["data"]["edge_id"] for e in result["edges"]}
    # e3 (SIRT1->NFKB1) and e4 (NFKB1->SIRT1) bridge the networks
    assert len(edge_ids) >= 2
    assert all("data" in e for e in result["edges"])
    assert all("data" in n for n in result["nodes"])


def test_e2e_centrality_returns_ranked_list(two_network_atlas, e2e_backend):
    """centrality(measure='pagerank') returns all 4 entities ranked by score."""
    import analysis.services as services

    with patch.object(services, "get_backend", return_value=e2e_backend):
        ranked = services.centrality(measure="pagerank")

    assert len(ranked) == 4
    assert all("pg_id" in r and "symbol" in r and "score" in r for r in ranked)
    # NFKB1 is the hub (highest in-degree) — should rank highest
    assert ranked[0]["symbol"] == "NFKB1"


def test_e2e_feedback_loops_detects_double_negative(two_network_atlas, e2e_backend):
    """feedback_loops detects the NFKB1<->SIRT1 mutual-inhibition toggle."""
    import analysis.services as services

    with patch.object(services, "get_backend", return_value=e2e_backend):
        loops = services.feedback_loops(max_len=4)

    double_neg = [loop for loop in loops if loop["double_negative"]]
    assert len(double_neg) >= 1
    # The double-negative loop must contain NFKB1 and SIRT1
    labels_in_dn = {n["data"]["label"] for loop in double_neg for n in loop["nodes"]}
    assert "NFKB1" in labels_in_dn
    assert "SIRT1" in labels_in_dn


# ---------------------------------------------------------------------------
# Step 5: explorer JSON endpoint assertions (Cytoscape shape)
# ---------------------------------------------------------------------------


def test_e2e_neighborhood_json_cytoscape_shape(two_network_atlas, e2e_client, e2e_backend):
    """neighborhood.json returns nodes and edges in Cytoscape element shape."""
    nfkb1_id = two_network_atlas["entities"]["nfkb1"].id
    r = e2e_client.get(f"/analysis/neighborhood.json?entity_id={nfkb1_id}&k=1")
    assert r.status_code == 200
    data = r.json()
    assert "nodes" in data and "edges" in data
    # Every element must have a "data" key with an "id" field (Cytoscape contract)
    for element in data["nodes"] + data["edges"]:
        assert "data" in element, f"Missing 'data' in element: {element}"
        assert "id" in element["data"], f"Missing 'id' in element data: {element['data']}"
    # IL1B and MMP3 are 1-hop away from NFKB1
    labels = {n["data"]["label"] for n in data["nodes"]}
    assert "IL1B" in labels or "MMP3" in labels or "SIRT1" in labels


def test_e2e_crosstalk_json_cytoscape_shape(two_network_atlas, e2e_client, e2e_backend):
    """crosstalk.json returns Cytoscape-shaped edges and nodes."""
    r = e2e_client.get("/analysis/crosstalk.json?network_a=nfkb&network_b=sirt")
    assert r.status_code == 200
    data = r.json()
    assert "nodes" in data and "edges" in data
    assert len(data["edges"]) >= 2
    for element in data["nodes"] + data["edges"]:
        assert "data" in element
        assert "id" in element["data"]


def test_e2e_paths_json_cytoscape_shape(two_network_atlas, e2e_client, e2e_backend):
    """paths.json returns a list of path-subgraphs in Cytoscape shape."""
    il1b_id = two_network_atlas["entities"]["il1b"].id
    mmp3_id = two_network_atlas["entities"]["mmp3"].id
    r = e2e_client.get(
        f"/analysis/paths.json?source={il1b_id}&target={mmp3_id}&mode=shortest&max_len=5"
    )
    assert r.status_code == 200
    data = r.json()
    assert "paths" in data
    assert len(data["paths"]) >= 1
    for path in data["paths"]:
        assert "nodes" in path and "edges" in path
        for element in path["nodes"] + path["edges"]:
            assert "data" in element


def test_e2e_analysis_panel_renders_with_results(two_network_atlas, e2e_client, e2e_backend):
    """The HTMX analysis panel partial returns centrality rows in HTML."""
    r = e2e_client.get("/analysis/panel/?measure=pagerank&max_len=4")
    assert r.status_code == 200
    # Must be an HTML fragment (no full page shell)
    assert b"<html" not in r.content.lower()
    # Must contain "Centrality" heading and at least one entity label
    assert b"Centrality" in r.content or b"centrality" in r.content
    # Should contain NFKB1 as it is the top-ranked hub
    assert b"NFKB1" in r.content


def test_e2e_explorer_page_renders(db, settings):
    """The explorer page shell renders with Cytoscape + HTMX script tags."""
    settings.ANALYSIS_GRAPH_BACKEND = "fake"
    client = Client(HTTP_REMOTE_USER="fchemorion")
    r = client.get("/analysis/")
    assert r.status_code == 200
    assert b"cytoscape" in r.content.lower()
    assert b"htmx" in r.content.lower()
