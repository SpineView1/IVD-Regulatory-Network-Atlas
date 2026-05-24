"""Neo4jBackend — the production GraphBackend.

All graph truth lives in Postgres; this backend reflects accepted edges into
Neo4j and answers traversal/GDS queries. Uses parameterized Cypher and the
GDS library (gds.graph.project on an anonymous in-memory projection per call,
then drops it). Returns plain dicts/lists shaped exactly like FakeGraphBackend.
"""

from __future__ import annotations

import uuid
from typing import Any

from neo4j import GraphDatabase

from analysis.backends.base import GraphBackend

INHIBITORY = {
    "inhibits",
    "represses",
    "dephosphorylates",
    "deubiquitinates",
    "deacetylates",
    "demethylates",
}


class Neo4jBackend(GraphBackend):
    def __init__(self, *, uri: str, user: str, password: str) -> None:
        self._driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self) -> None:
        self._driver.close()

    def _run(self, cypher: str, **params: Any) -> list:
        with self._driver.session() as session:
            return list(session.run(cypher, **params))

    # --- lifecycle ---
    def ensure_constraints(self) -> None:
        self._run(
            "CREATE CONSTRAINT entity_pg_id IF NOT EXISTS "
            "FOR (e:Entity) REQUIRE e.pg_id IS UNIQUE"
        )
        self._run(
            "CREATE CONSTRAINT network_code IF NOT EXISTS "
            "FOR (n:Network) REQUIRE n.code IS UNIQUE"
        )
        self._run(
            "CREATE CONSTRAINT regulates_id IF NOT EXISTS "
            "FOR ()-[r:REGULATES]-() REQUIRE r.edge_id IS UNIQUE"
        )

    def clear_all(self) -> None:
        self._run("MATCH (n) DETACH DELETE n")

    # --- upserts ---
    def upsert_entity(self, props: dict) -> None:
        self._run(
            "MERGE (e:Entity {pg_id: $pg_id}) "
            "SET e.ontology_id=$ontology_id, e.symbol=$symbol, "
            "e.entity_type=$entity_type, e.compartment=$compartment, "
            "e.canonical_uri=$canonical_uri",
            **props,
        )

    def upsert_network(self, props: dict) -> None:
        self._run(
            "MERGE (n:Network {code: $code}) SET n.title=$title, n.category=$category",
            **props,
        )

    def upsert_edge(self, *, source_pg_id: int, target_pg_id: int, props: dict) -> None:
        self._run(
            "MATCH (s:Entity {pg_id:$source_pg_id}), (t:Entity {pg_id:$target_pg_id}) "
            "MERGE (s)-[r:REGULATES {edge_id:$edge_id}]->(t) "
            "SET r.relation=$relation, r.belief_score=$belief_score, "
            "r.n_supporting_papers=$n_supporting_papers, "
            "r.n_models_agreeing=$n_models_agreeing, r.status=$status, "
            "r.networks=$networks",
            source_pg_id=source_pg_id,
            target_pg_id=target_pg_id,
            **props,
        )

    def link_in_network(self, *, entity_pg_id: int, network_code: str) -> None:
        self._run(
            "MATCH (e:Entity {pg_id:$entity_pg_id}), (n:Network {code:$network_code}) "
            "MERGE (e)-[:IN_NETWORK]->(n)",
            entity_pg_id=entity_pg_id,
            network_code=network_code,
        )

    def delete_edge(self, edge_id: int) -> None:
        self._run(
            "MATCH ()-[r:REGULATES {edge_id:$edge_id}]->() DELETE r",
            edge_id=edge_id,
        )

    def prune_orphan_entities(self) -> int:
        rows = self._run(
            "MATCH (e:Entity) WHERE NOT (e)-[:REGULATES]-() "
            "AND NOT ()-[:REGULATES]->(e) "
            "WITH collect(e) AS orphans, count(e) AS c "
            "FOREACH (o IN orphans | DETACH DELETE o) RETURN c AS c"
        )
        return int(rows[0]["c"]) if rows else 0

    # --- reads ---
    def all_edge_ids(self) -> set[int]:
        rows = self._run("MATCH ()-[r:REGULATES]->() RETURN r.edge_id AS id")
        return {int(row["id"]) for row in rows}

    def count_entities(self) -> int:
        rows = self._run("MATCH (e:Entity) RETURN count(e) AS c")
        return int(rows[0]["c"])

    def count_edges(self) -> int:
        rows = self._run("MATCH ()-[r:REGULATES]->() RETURN count(r) AS c")
        return int(rows[0]["c"])

    def get_entity(self, pg_id: int) -> dict | None:
        rows = self._run("MATCH (e:Entity {pg_id:$pg_id}) RETURN e", pg_id=pg_id)
        return dict(rows[0]["e"]) if rows else None

    def get_edge(self, edge_id: int) -> dict | None:
        rows = self._run(
            "MATCH ()-[r:REGULATES {edge_id:$edge_id}]->() RETURN r",
            edge_id=edge_id,
        )
        return dict(rows[0]["r"]) if rows else None

    # --- serialization helpers ---
    # neo4j Node/Relationship objects are dict-like; typed as Any because
    # the neo4j driver has no mypy stubs (see mypy.ini [mypy-neo4j.*]).
    @staticmethod
    def _node_payload(node: Any) -> dict:
        return {
            "data": {
                "id": str(node["pg_id"]),
                "pg_id": node["pg_id"],
                "label": node.get("symbol", ""),
                "entity_type": node.get("entity_type", ""),
                "compartment": node.get("compartment", ""),
                "networks": node.get("networks", []),
            }
        }

    @staticmethod
    def _rel_payload(rel: Any, src_pg: int, tgt_pg: int) -> dict:
        return {
            "data": {
                "id": f"e{rel['edge_id']}",
                "edge_id": rel["edge_id"],
                "source": str(src_pg),
                "target": str(tgt_pg),
                "relation": rel.get("relation"),
                "belief": rel.get("belief_score"),
                "status": rel.get("status"),
                "n_supporting_papers": rel.get("n_supporting_papers"),
                "n_models_agreeing": rel.get("n_models_agreeing"),
                "networks": rel.get("networks", []),
            }
        }

    def _subgraph(self, cypher: str, **params: Any) -> dict:
        """Run a query returning rels and serialize to {nodes, edges}."""
        rows = self._run(cypher, **params)
        nodes: dict[int, dict] = {}
        edges: dict[int, dict] = {}
        for row in rows:
            for rel in row.get("rels", []):
                s = rel.start_node
                t = rel.end_node
                nodes[s["pg_id"]] = self._node_payload(s)
                nodes[t["pg_id"]] = self._node_payload(t)
                edges[rel["edge_id"]] = self._rel_payload(rel, s["pg_id"], t["pg_id"])
        return {"nodes": list(nodes.values()), "edges": list(edges.values())}

    # --- query surface ---
    def neighborhood(self, *, entity_pg_id: int, k: int) -> dict:
        return self._subgraph(
            f"MATCH p=(c:Entity {{pg_id:$pg_id}})-[:REGULATES*1..{int(k)}]-(:Entity) "
            "UNWIND relationships(p) AS rel RETURN collect(rel) AS rels",
            pg_id=entity_pg_id,
        )

    def crosstalk_edges(self, *, network_a: str, network_b: str) -> dict:
        return self._subgraph(
            "MATCH (s:Entity)-[r:REGULATES]->(t:Entity) "
            "WHERE ($a IN r.networks AND $b IN r.networks) "
            "   OR ((s)-[:IN_NETWORK]->(:Network {code:$a}) AND "
            "       (t)-[:IN_NETWORK]->(:Network {code:$b})) "
            "   OR ((s)-[:IN_NETWORK]->(:Network {code:$b}) AND "
            "       (t)-[:IN_NETWORK]->(:Network {code:$a})) "
            "RETURN collect(r) AS rels",
            a=network_a,
            b=network_b,
        )

    def shortest_paths(self, *, source_pg_id: int, target_pg_id: int, max_len: int) -> list[dict]:
        rows = self._run(
            f"MATCH p=shortestPath((s:Entity {{pg_id:$s}})-[:REGULATES*..{int(max_len)}]->"
            "(t:Entity {pg_id:$t})) RETURN relationships(p) AS rels",
            s=source_pg_id,
            t=target_pg_id,
        )
        return self._rows_to_paths(rows)

    def all_simple_paths(self, *, source_pg_id: int, target_pg_id: int, max_len: int) -> list[dict]:
        rows = self._run(
            f"MATCH p=(s:Entity {{pg_id:$s}})-[:REGULATES*1..{int(max_len)}]->"
            "(t:Entity {pg_id:$t}) WHERE all(n IN nodes(p) WHERE "
            "size([m IN nodes(p) WHERE m=n])=1) RETURN relationships(p) AS rels",
            s=source_pg_id,
            t=target_pg_id,
        )
        return self._rows_to_paths(rows)

    def _rows_to_paths(self, rows: list) -> list[dict]:
        paths = []
        for row in rows:
            nodes: dict[int, dict] = {}
            edges: dict[int, dict] = {}
            for rel in row["rels"]:
                s = rel.start_node
                t = rel.end_node
                nodes[s["pg_id"]] = self._node_payload(s)
                nodes[t["pg_id"]] = self._node_payload(t)
                edges[rel["edge_id"]] = self._rel_payload(rel, s["pg_id"], t["pg_id"])
            paths.append({"nodes": list(nodes.values()), "edges": list(edges.values())})
        return paths

    # --- GDS-backed analytics (anonymous projection per call) ---
    def _with_projection(self, network: str | None) -> str:
        """Project an in-memory GDS graph; returns the projection name."""
        name = f"g_{uuid.uuid4().hex}"
        if network is None:
            self._run(
                "CALL gds.graph.project($name, $labels, " "{REGULATES: {orientation: 'NATURAL'}})",
                name=name,
                labels="Entity",
            )
        else:
            self._run(
                "MATCH (e:Entity)-[:IN_NETWORK]->(:Network {code:$code}) "
                "WITH collect(e) AS ns "
                "CALL gds.graph.project.cypher($name, "
                "  'MATCH (e:Entity) WHERE e IN $ns RETURN id(e) AS id', "
                "  'MATCH (a:Entity)-[r:REGULATES]->(b:Entity) "
                "   WHERE a IN $ns AND b IN $ns RETURN id(a) AS source, id(b) AS target', "
                "  {parameters: {ns: ns}}) YIELD graphName RETURN graphName",
                name=name,
                code=network,
            )
        return name

    def _drop_projection(self, name: str) -> None:
        self._run("CALL gds.graph.drop($name, false) YIELD graphName", name=name)

    def centrality(self, *, network: str | None, measure: str) -> list[dict]:
        proc = {
            "pagerank": "gds.pageRank",
            "betweenness": "gds.betweenness",
            "degree": "gds.degree",
        }.get(measure)
        if proc is None:
            raise ValueError(f"unknown centrality measure: {measure}")
        name = self._with_projection(network)
        try:
            rows = self._run(
                f"CALL {proc}.stream($name) YIELD nodeId, score "
                "MATCH (e) WHERE id(e)=nodeId "
                "RETURN e.pg_id AS pg_id, e.symbol AS symbol, score "
                "ORDER BY score DESC",
                name=name,
            )
        finally:
            self._drop_projection(name)
        return [
            {"pg_id": r["pg_id"], "symbol": r["symbol"], "score": float(r["score"])} for r in rows
        ]

    def communities(self, *, network: str | None) -> list[dict]:
        name = self._with_projection(network)
        try:
            rows = self._run(
                "CALL gds.louvain.stream($name) YIELD nodeId, communityId "
                "MATCH (e) WHERE id(e)=nodeId "
                "RETURN e.pg_id AS pg_id, e.symbol AS symbol, communityId AS community",
                name=name,
            )
        finally:
            self._drop_projection(name)
        return [
            {"pg_id": r["pg_id"], "symbol": r["symbol"], "community": r["community"]} for r in rows
        ]

    def feedback_loops(self, *, max_len: int, network: str | None) -> list[dict]:
        scope = ""
        params: dict[str, object] = {"max_len": int(max_len)}
        if network is not None:
            scope = (
                "MATCH (start:Entity)-[:IN_NETWORK]->(:Network {code:$code}) "
                "WITH collect(start) AS scope "
            )
            params["code"] = network
        rows = self._run(
            scope
            + f"MATCH p=(a:Entity)-[:REGULATES*1..{int(max_len)}]->(a) "
            + ("WHERE all(n IN nodes(p) WHERE n IN scope) " if network else "")
            + "RETURN nodes(p) AS ns, relationships(p) AS rels",
            **params,
        )
        loops = []
        for row in rows:
            edges: dict[int, dict] = {}
            nodes: dict[int, dict] = {}
            inhib = 0
            for rel in row["rels"]:
                s = rel.start_node
                t = rel.end_node
                nodes[s["pg_id"]] = self._node_payload(s)
                nodes[t["pg_id"]] = self._node_payload(t)
                edges[rel["edge_id"]] = self._rel_payload(rel, s["pg_id"], t["pg_id"])
                if rel.get("relation") in INHIBITORY:
                    inhib += 1
            ring_len = len(row["rels"])
            loops.append(
                {
                    "nodes": list(nodes.values()),
                    "edges": list(edges.values()),
                    "double_negative": ring_len == 2 and inhib == 2,
                }
            )
        return loops
