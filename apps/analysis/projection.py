"""Postgres → backend projection mapping.

Pure-ish: reads the graph models, builds JSON-serializable payloads, and
drives a GraphBackend. Postgres is the system of record; this module never
writes graph truth — it only reflects accepted edges into the read-model.

Canonical field names (cross-plan reconciliation §4/§5/§6):
  Edge.relation, Edge.belief_score, Edge.status, Edge.n_supporting_papers,
  Edge.n_models_agreeing; Entity.symbol/compartment/canonical_uri proxies;
  Network.code/title/category; NetworkEdgeMembership.network/edge.
"""
from __future__ import annotations

from collections.abc import Iterable

from analysis.backends.base import GraphBackend


def accepted_edge_ids() -> set[int]:
    """Set of all Edge.id where status == 'accepted' in Postgres."""
    from graph.models import Edge

    return set(
        Edge.objects.filter(status="accepted").values_list("id", flat=True)
    )


def build_entity_payload(entity: object) -> dict:
    """Map a graph.Entity to the (:Entity) node props."""
    oe = entity.ontology_entity  # type: ignore[attr-defined]
    return {
        "pg_id": entity.id,  # type: ignore[attr-defined]
        "ontology_id": oe.id,
        "symbol": entity.symbol,            # proxy -> preferred_label (§5)  # type: ignore[attr-defined]
        "entity_type": oe.entity_type,
        "compartment": entity.compartment,  # proxy (§5)  # type: ignore[attr-defined]
        "canonical_uri": entity.canonical_uri,  # type: ignore[attr-defined]
    }


def _edge_network_codes(edge: object) -> list[str]:
    """Network codes this edge belongs to, sorted, via NetworkEdgeMembership."""
    return sorted(
        edge.network_memberships.values_list("network__code", flat=True)  # type: ignore[attr-defined]
    )


def build_edge_payload(edge: object) -> dict:
    """Map a graph.Edge to the [:REGULATES] relationship props."""
    return {
        "edge_id": edge.id,  # type: ignore[attr-defined]
        "relation": edge.relation,                       # NOT relation_type (§4)  # type: ignore[attr-defined]
        "belief_score": edge.belief_score,  # type: ignore[attr-defined]
        "n_supporting_papers": edge.n_supporting_papers,  # persisted (§8)  # type: ignore[attr-defined]
        "n_models_agreeing": edge.n_models_agreeing,      # persisted (§8)  # type: ignore[attr-defined]
        "status": edge.status,  # type: ignore[attr-defined]
        "networks": _edge_network_codes(edge),
    }


def build_network_payload(network: object) -> dict:
    """Map a networks.Network to the (:Network) node props."""
    return {
        "code": network.code,  # type: ignore[attr-defined]
        "title": network.title,  # type: ignore[attr-defined]
        "category": network.category,  # type: ignore[attr-defined]
    }


def project_edge_ids(edge_ids: Iterable[int], *, backend: GraphBackend) -> dict:
    """Incrementally reflect the given edges into the backend.

    For each edge:
      * status == 'accepted'  → MERGE both endpoint entities, the REGULATES
        relationship, the Network nodes, and the IN_NETWORK links.
      * otherwise (rejected/conflicted/candidate) → DELETE its relationship.
    Idempotent: re-running with the same accepted edge updates props in place.
    """
    from graph.models import Edge

    edge_ids_list = list(edge_ids)
    edges = (
        Edge.objects.filter(id__in=edge_ids_list)
        .select_related("source__ontology_entity", "target__ontology_entity")
        .prefetch_related("network_memberships__network")
    )
    by_id = {e.id: e for e in edges}

    projected = 0
    removed = 0
    for eid in edge_ids_list:
        edge = by_id.get(eid)
        if edge is None or edge.status != "accepted":
            backend.delete_edge(eid)
            removed += 1
            continue

        src_payload = build_entity_payload(edge.source)
        tgt_payload = build_entity_payload(edge.target)
        backend.upsert_entity(src_payload)
        backend.upsert_entity(tgt_payload)
        backend.upsert_edge(
            source_pg_id=edge.source_id,
            target_pg_id=edge.target_id,
            props=build_edge_payload(edge),
        )
        for membership in edge.network_memberships.all():
            net = membership.network
            backend.upsert_network(build_network_payload(net))
            backend.link_in_network(entity_pg_id=edge.source_id, network_code=net.code)
            backend.link_in_network(entity_pg_id=edge.target_id, network_code=net.code)
        projected += 1

    return {"projected": projected, "removed": removed}
