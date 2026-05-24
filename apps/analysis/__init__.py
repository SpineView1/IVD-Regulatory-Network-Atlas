"""analysis — Neo4j-backed crosstalk explorer and network-analysis app.

Owns the derived Neo4j read-model of the accepted-Edge graph. Reads
Postgres (graph.Edge / Entity / NetworkEdgeMembership) only; never the
system of record's writer. See docs/superpowers/specs §1 Neo4j invariant.
"""
