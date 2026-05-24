"""Service-layer tests over a projected FakeGraphBackend atlas."""

from __future__ import annotations

import pytest

from analysis.backends.fake import FakeGraphBackend


@pytest.fixture
def atlas() -> FakeGraphBackend:
    """A small two-network atlas with a crosstalk edge and a 2-cycle.

    Network A (nfkb): 1(IL1B) -> 2(NFKB1) -> 3(MMP3)
    Network B (sirt): 4(SIRT1) -> 2(NFKB1)            # 4 bridges B into A's NFKB1
    Mutual inhibition (double-negative): 2 -inhibits-> 4 and 4 -inhibits-> 2
    """
    b = FakeGraphBackend()
    nodes = {1: "IL1B", 2: "NFKB1", 3: "MMP3", 4: "SIRT1"}
    for pg, sym in nodes.items():
        b.upsert_entity(
            {
                "pg_id": pg,
                "symbol": sym,
                "entity_type": "protein",
                "compartment": "c",
                "canonical_uri": f"u{pg}",
                "ontology_id": pg,
            }
        )
    b.upsert_network({"code": "nfkb", "title": "NF-kB", "category": "I"})
    b.upsert_network({"code": "sirt", "title": "Sirtuin", "category": "III"})

    def edge(eid, s, t, rel, nets):
        b.upsert_edge(
            source_pg_id=s,
            target_pg_id=t,
            props={
                "edge_id": eid,
                "relation": rel,
                "belief_score": 0.8,
                "n_supporting_papers": 2,
                "n_models_agreeing": 3,
                "status": "accepted",
                "networks": nets,
            },
        )

    edge(10, 1, 2, "activates", ["nfkb"])
    edge(11, 2, 3, "activates", ["nfkb"])
    edge(12, 4, 2, "inhibits", ["sirt"])
    edge(13, 2, 4, "inhibits", ["nfkb"])  # together with 12 -> double negative

    for pg, code in [(1, "nfkb"), (2, "nfkb"), (3, "nfkb"), (2, "sirt"), (4, "sirt")]:
        b.link_in_network(entity_pg_id=pg, network_code=code)
    return b


@pytest.fixture
def svc(atlas, monkeypatch):
    """Point analysis.services at the prebuilt atlas backend."""
    import analysis.services as services

    monkeypatch.setattr(services, "get_backend", lambda: atlas)
    return services


def test_neighborhood_one_hop(db, svc):
    out = svc.neighborhood(entity_id=2, k=1)
    labels = {n["data"]["label"] for n in out["nodes"]}
    assert labels == {"IL1B", "NFKB1", "MMP3", "SIRT1"}


def test_crosstalk_edges_between_networks(db, svc):
    out = svc.crosstalk_edges(network_a="sirt", network_b="nfkb")
    # SIRT1->NFKB1 (12) bridges sirt into nfkb; NFKB1->SIRT1 (13) bridges back
    eids = {e["data"]["edge_id"] for e in out["edges"]}
    assert {12, 13} <= eids


def test_shortest_paths(db, svc):
    out = svc.shortest_paths(source_entity=1, target_entity=3, max_len=5)
    assert len(out) == 1
    eids = {e["data"]["edge_id"] for e in out[0]["edges"]}
    assert eids == {10, 11}


def test_all_simple_paths(db, svc):
    out = svc.all_simple_paths(source_entity=1, target_entity=3, max_len=5)
    assert len(out) >= 1


def test_centrality_pagerank_default(db, svc):
    ranked = svc.centrality()
    assert ranked[0]["symbol"] == "NFKB1"  # highest in-degree hub
    assert all("score" in r for r in ranked)


def test_centrality_rejects_unknown_measure(db, svc):
    with pytest.raises(ValueError):
        svc.centrality(measure="nonsense")


def test_communities(db, svc):
    comms = svc.communities()
    assert all("community" in c for c in comms)


def test_feedback_loops_flags_double_negative(db, svc):
    loops = svc.feedback_loops(max_len=4)
    dn = [loop for loop in loops if loop["double_negative"]]
    assert len(dn) >= 1  # the NFKB1<->SIRT1 mutual inhibition
