"""In-memory GraphBackend backed by networkx — for unit tests.

Stores the same node/relationship shapes the Neo4jBackend produces, so
service logic and projection diffing are exercised identically. GDS calls
are emulated with networkx algorithms (PageRank, betweenness, degree,
greedy-modularity communities, simple_cycles) so the *shape* of the result
matches what the real backend returns.
"""
from __future__ import annotations

import networkx as nx  # type: ignore[import-untyped]

from analysis.backends.base import GraphBackend

# Relations whose semantics are inhibitory — used for double-negative motif tagging.
INHIBITORY = {"inhibits", "represses", "dephosphorylates", "deubiquitinates",
              "deacetylates", "demethylates"}


class FakeGraphBackend(GraphBackend):
    def __init__(self) -> None:
        self._g: nx.MultiDiGraph = nx.MultiDiGraph()  # entity nodes + REGULATES edges
        self._networks: dict[str, dict] = {}          # code -> props
        self._in_network: set[tuple[int, str]] = set()
        self._edge_by_id: dict[int, tuple[int, int]] = {}  # edge_id -> (src, tgt)

    # --- lifecycle ---
    def ensure_constraints(self) -> None:
        return None

    def clear_all(self) -> None:
        self._g.clear()
        self._networks.clear()
        self._in_network.clear()
        self._edge_by_id.clear()

    # --- upserts ---
    def upsert_entity(self, props: dict) -> None:
        self._g.add_node(props["pg_id"], **props)

    def upsert_network(self, props: dict) -> None:
        self._networks[props["code"]] = dict(props)

    def upsert_edge(self, *, source_pg_id: int, target_pg_id: int, props: dict) -> None:
        eid = props["edge_id"]
        if eid in self._edge_by_id:  # idempotent update-in-place
            self.delete_edge(eid)
        self._g.add_edge(source_pg_id, target_pg_id, key=eid, **props)
        self._edge_by_id[eid] = (source_pg_id, target_pg_id)

    def link_in_network(self, *, entity_pg_id: int, network_code: str) -> None:
        self._in_network.add((entity_pg_id, network_code))

    def delete_edge(self, edge_id: int) -> None:
        pair = self._edge_by_id.pop(edge_id, None)
        if pair is not None and self._g.has_edge(pair[0], pair[1], key=edge_id):
            self._g.remove_edge(pair[0], pair[1], key=edge_id)

    def prune_orphan_entities(self) -> int:
        orphans = [n for n in self._g.nodes if self._g.degree(n) == 0]
        self._g.remove_nodes_from(orphans)
        self._in_network = {(e, c) for (e, c) in self._in_network if e not in orphans}
        return len(orphans)

    # --- reads ---
    def all_edge_ids(self) -> set[int]:
        return set(self._edge_by_id)

    def count_entities(self) -> int:
        return self._g.number_of_nodes()

    def count_edges(self) -> int:
        return self._g.number_of_edges()

    def get_entity(self, pg_id: int) -> dict | None:
        return dict(self._g.nodes[pg_id]) if pg_id in self._g else None

    def get_edge(self, edge_id: int) -> dict | None:
        pair = self._edge_by_id.get(edge_id)
        if pair is None:
            return None
        return dict(self._g.edges[pair[0], pair[1], edge_id])

    # --- subgraph serialization helper ---
    def _serialize(self, node_ids: set[int], edge_ids: set[int]) -> dict:
        nodes = [self._node_payload(n) for n in node_ids if n in self._g]
        edges = []
        for eid in edge_ids:
            pair = self._edge_by_id.get(eid)
            if pair is None:
                continue
            edges.append(self._edge_payload(eid, pair))
        return {"nodes": nodes, "edges": edges}

    def _node_payload(self, n: int) -> dict:
        d = self._g.nodes[n]
        networks = sorted(c for (e, c) in self._in_network if e == n)
        return {"data": {"id": str(n), "pg_id": n, "label": d.get("symbol", str(n)),
                         "entity_type": d.get("entity_type", ""),
                         "compartment": d.get("compartment", ""),
                         "networks": networks}}

    def _edge_payload(self, eid: int, pair: tuple[int, int]) -> dict:
        d = self._g.edges[pair[0], pair[1], eid]
        return {"data": {"id": f"e{eid}", "edge_id": eid, "source": str(pair[0]),
                         "target": str(pair[1]), "relation": d.get("relation"),
                         "belief": d.get("belief_score"), "status": d.get("status"),
                         "n_supporting_papers": d.get("n_supporting_papers"),
                         "n_models_agreeing": d.get("n_models_agreeing"),
                         "networks": d.get("networks", [])}}

    # --- query surface ---
    def neighborhood(self, *, entity_pg_id: int, k: int) -> dict:
        if entity_pg_id not in self._g:
            return {"nodes": [], "edges": []}
        und = self._g.to_undirected(as_view=True)
        reach = nx.single_source_shortest_path_length(und, entity_pg_id, cutoff=k)
        node_ids = set(reach)
        edge_ids = {eid for eid, (s, t) in self._edge_by_id.items()
                    if s in node_ids and t in node_ids}
        return self._serialize(node_ids, edge_ids)

    def crosstalk_edges(self, *, network_a: str, network_b: str) -> dict:
        in_a = {e for (e, c) in self._in_network if c == network_a}
        in_b = {e for (e, c) in self._in_network if c == network_b}
        edge_ids = set()
        for eid, (s, t) in self._edge_by_id.items():
            nets = set(self._g.edges[s, t, eid].get("networks", []))
            bridges = (s in in_a and t in in_b) or (s in in_b and t in in_a) \
                or ({network_a, network_b} <= nets)
            if bridges:
                edge_ids.add(eid)
        node_ids = set()
        for eid in edge_ids:
            s, t = self._edge_by_id[eid]
            node_ids.update({s, t})
        return self._serialize(node_ids, edge_ids)

    def shortest_paths(self, *, source_pg_id: int, target_pg_id: int, max_len: int) -> list[dict]:
        try:
            path = nx.shortest_path(self._g, source_pg_id, target_pg_id)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return []
        if len(path) - 1 > max_len:
            return []
        return [self._path_to_dict(path)]

    def all_simple_paths(self, *, source_pg_id: int, target_pg_id: int, max_len: int) -> list[dict]:
        if source_pg_id not in self._g or target_pg_id not in self._g:
            return []
        paths = nx.all_simple_paths(self._g, source_pg_id, target_pg_id, cutoff=max_len)
        return [self._path_to_dict(p) for p in paths]

    def _path_to_dict(self, path: list[int]) -> dict:
        node_ids = set(path)
        edge_ids = set()
        for s, t in zip(path, path[1:]):
            for eid, pair in self._edge_by_id.items():
                if pair == (s, t):
                    edge_ids.add(eid)
                    break
        return self._serialize(node_ids, edge_ids)

    def _scope_graph(self, network: str | None) -> nx.MultiDiGraph:
        if network is None:
            return self._g
        nodes = {e for (e, c) in self._in_network if c == network}
        return self._g.subgraph(nodes)

    def centrality(self, *, network: str | None, measure: str) -> list[dict]:
        g = self._scope_graph(network)
        if g.number_of_nodes() == 0:
            return []
        if measure == "pagerank":
            scores = nx.pagerank(nx.DiGraph(g))
        elif measure == "betweenness":
            scores = nx.betweenness_centrality(nx.DiGraph(g))
        elif measure == "degree":
            scores = dict(g.degree())
        else:
            raise ValueError(f"unknown centrality measure: {measure}")
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        return [{"pg_id": n, "symbol": self._g.nodes[n].get("symbol", str(n)),
                 "score": float(s)} for n, s in ranked]

    def communities(self, *, network: str | None) -> list[dict]:
        g = self._scope_graph(network)
        if g.number_of_nodes() == 0:
            return []
        comms = nx.community.greedy_modularity_communities(nx.Graph(g))
        out = []
        for idx, members in enumerate(comms):
            for n in members:
                out.append({"pg_id": n, "symbol": self._g.nodes[n].get("symbol", str(n)),
                            "community": idx})
        return out

    def feedback_loops(self, *, max_len: int, network: str | None) -> list[dict]:
        g = self._scope_graph(network)
        loops = []
        for cycle in nx.simple_cycles(nx.DiGraph(g)):
            if len(cycle) > max_len:
                continue
            ring = cycle + [cycle[0]]
            edge_ids: set[int] = set()
            inhib_count = 0
            for s, t in zip(ring, ring[1:]):
                for eid, pair in self._edge_by_id.items():
                    if pair == (s, t):
                        edge_ids.add(eid)
                        if self._g.edges[s, t, eid].get("relation") in INHIBITORY:
                            inhib_count += 1
                        break
            payload = self._serialize(set(cycle), edge_ids)
            payload["double_negative"] = (len(cycle) == 2 and inhib_count == 2)
            loops.append(payload)
        return loops
