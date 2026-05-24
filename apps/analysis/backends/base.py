"""GraphBackend — the abstract seam between analysis logic and Neo4j.

Every projection and query in the analysis app goes through this interface,
so unit tests can swap in FakeGraphBackend and never need a live database.
All methods take/return plain Python dicts and lists (JSON-serializable),
never neo4j driver objects.
"""

from __future__ import annotations

import abc


class GraphBackend(abc.ABC):
    # --- schema / lifecycle -------------------------------------------------
    @abc.abstractmethod
    def ensure_constraints(self) -> None:
        """Create node/relationship uniqueness constraints (idempotent)."""

    @abc.abstractmethod
    def clear_all(self) -> None:
        """Wipe the entire read-model. Used by the rebuild-from-scratch path."""

    # --- node / relationship upserts ---------------------------------------
    @abc.abstractmethod
    def upsert_entity(self, props: dict) -> None:
        """MERGE an (:Entity {pg_id}) and set its properties."""

    @abc.abstractmethod
    def upsert_network(self, props: dict) -> None:
        """MERGE a (:Network {code}) and set its properties."""

    @abc.abstractmethod
    def upsert_edge(self, *, source_pg_id: int, target_pg_id: int, props: dict) -> None:
        """MERGE a (:Entity)-[:REGULATES {edge_id}]->(:Entity) and set properties."""

    @abc.abstractmethod
    def link_in_network(self, *, entity_pg_id: int, network_code: str) -> None:
        """MERGE (:Entity)-[:IN_NETWORK]->(:Network)."""

    @abc.abstractmethod
    def delete_edge(self, edge_id: int) -> None:
        """DELETE the :REGULATES relationship with this edge_id (idempotent)."""

    @abc.abstractmethod
    def prune_orphan_entities(self) -> int:
        """Delete :Entity nodes with no :REGULATES relationships. Returns count."""

    # --- read helpers used by reconcile + tests ----------------------------
    @abc.abstractmethod
    def all_edge_ids(self) -> set[int]:
        """Set of edge_id values currently projected as :REGULATES rels."""

    @abc.abstractmethod
    def count_entities(self) -> int: ...

    @abc.abstractmethod
    def count_edges(self) -> int: ...

    @abc.abstractmethod
    def get_entity(self, pg_id: int) -> dict | None: ...

    @abc.abstractmethod
    def get_edge(self, edge_id: int) -> dict | None: ...

    # --- query surface used by services.py ----------------------------------
    @abc.abstractmethod
    def neighborhood(self, *, entity_pg_id: int, k: int) -> dict:
        """k-hop neighborhood. Returns {"nodes": [...], "edges": [...]}."""

    @abc.abstractmethod
    def crosstalk_edges(self, *, network_a: str, network_b: str) -> dict:
        """Edges bridging two networks. Returns {"nodes": [...], "edges": [...]}."""

    @abc.abstractmethod
    def shortest_paths(self, *, source_pg_id: int, target_pg_id: int, max_len: int) -> list[dict]:
        """Shortest path(s). Returns a list of {"nodes": [...], "edges": [...]}."""

    @abc.abstractmethod
    def all_simple_paths(self, *, source_pg_id: int, target_pg_id: int, max_len: int) -> list[dict]:
        """All simple paths up to max_len. Returns a list of path dicts."""

    @abc.abstractmethod
    def centrality(self, *, network: str | None, measure: str) -> list[dict]:
        """GDS centrality ranking. Returns [{"pg_id", "symbol", "score"}, ...]."""

    @abc.abstractmethod
    def communities(self, *, network: str | None) -> list[dict]:
        """GDS Louvain communities. Returns [{"pg_id", "symbol", "community"}, ...]."""

    @abc.abstractmethod
    def feedback_loops(self, *, max_len: int, network: str | None) -> list[dict]:
        """Directed cycles. Returns [{"nodes": [...], "edges": [...], "double_negative": bool}]."""
