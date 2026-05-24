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
from typing import TYPE_CHECKING

from analysis.backends.base import GraphBackend

if TYPE_CHECKING:
    from graph.models import Edge, Entity
    from networks.models import Network


def accepted_edge_ids() -> set[int]:
    """Set of all Edge.id where status == 'accepted' in Postgres."""
    from graph.models import Edge

    return set(Edge.objects.filter(status="accepted").values_list("id", flat=True))


def build_entity_payload(entity: Entity) -> dict:
    """Map a graph.Entity to the (:Entity) node props."""
    oe = entity.ontology_entity
    return {
        "pg_id": entity.pk,
        "ontology_id": oe.pk,
        "symbol": entity.symbol,  # proxy -> preferred_label (§5)
        "entity_type": oe.entity_type,
        "compartment": entity.compartment,  # proxy (§5)
        "canonical_uri": entity.canonical_uri,
    }


def _edge_network_codes(edge: Edge) -> list[str]:
    """Network codes this edge belongs to, sorted, via NetworkEdgeMembership."""
    return sorted(edge.network_memberships.values_list("network__code", flat=True))


def build_edge_payload(edge: Edge) -> dict:
    """Map a graph.Edge to the [:REGULATES] relationship props."""
    return {
        "edge_id": edge.pk,
        "relation": edge.relation,  # NOT relation_type (§4)
        "belief_score": edge.belief_score,
        "n_supporting_papers": edge.n_supporting_papers,  # persisted (§8)
        "n_models_agreeing": edge.n_models_agreeing,  # persisted (§8)
        "status": edge.status,
        "networks": _edge_network_codes(edge),
    }


def build_network_payload(network: Network) -> dict:
    """Map a networks.Network to the (:Network) node props."""
    return {
        "code": network.code,
        "title": network.title,
        "category": network.category,
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
