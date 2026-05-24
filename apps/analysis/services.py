"""analysis public API.

The app's services.py is the boundary other code calls (spec §2 boundary
discipline). Each function is a thin pass-through to the active GraphBackend,
returning plain JSON-serializable structures the views serialize directly.
Postgres remains the system of record; these are read-only queries over the
derived Neo4j read-model.
"""

from __future__ import annotations

from analysis.backends import get_backend


def neighborhood(*, entity_id: int, k: int = 1) -> dict:
    """k-hop neighborhood of an entity across the whole atlas.

    Returns {"nodes": [...], "edges": [...]} in Cytoscape element shape.
    """
    return get_backend().neighborhood(entity_pg_id=entity_id, k=k)


def crosstalk_edges(*, network_a: str, network_b: str) -> dict:
    """Relationships bridging network_a and network_b."""
    return get_backend().crosstalk_edges(network_a=network_a, network_b=network_b)


def shortest_paths(*, source_entity: int, target_entity: int, max_len: int = 6) -> list[dict]:
    """Shortest directed path(s) from source to target (each a subgraph dict)."""
    return get_backend().shortest_paths(
        source_pg_id=source_entity, target_pg_id=target_entity, max_len=max_len
    )


def all_simple_paths(*, source_entity: int, target_entity: int, max_len: int = 6) -> list[dict]:
    """All simple directed paths up to max_len hops."""
    return get_backend().all_simple_paths(
        source_pg_id=source_entity, target_pg_id=target_entity, max_len=max_len
    )


def centrality(*, network: str | None = None, measure: str = "pagerank") -> list[dict]:
    """GDS centrality ranking, optionally scoped to one network.

    measure ∈ {"pagerank", "betweenness", "degree"}.
    """
    if measure not in {"pagerank", "betweenness", "degree"}:
        raise ValueError(f"unknown centrality measure: {measure}")
    return get_backend().centrality(network=network, measure=measure)


def communities(*, network: str | None = None) -> list[dict]:
    """GDS Louvain community assignment, optionally scoped to one network."""
    return get_backend().communities(network=network)


def feedback_loops(*, max_len: int = 4, network: str | None = None) -> list[dict]:
    """Directed cycles up to max_len, each flagged with `double_negative`.

    A double-negative motif is a 2-cycle where both relations are inhibitory
    (mutual inhibition / toggle switch) — a load-bearing regulatory pattern.
    """
    return get_backend().feedback_loops(max_len=max_len, network=network)
