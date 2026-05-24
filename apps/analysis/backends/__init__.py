"""Graph backends. The factory hides which implementation is active."""
from __future__ import annotations

from django.conf import settings

from analysis.backends.base import GraphBackend


def get_backend() -> GraphBackend:
    """Return the configured GraphBackend instance.

    Selected by settings.ANALYSIS_GRAPH_BACKEND ("neo4j" | "fake").
    Tests flip this to "fake" via the settings fixture; production uses
    "neo4j". Importing the neo4j backend is deferred so the fake path has
    no hard dependency on a running database.
    """
    backend = getattr(settings, "ANALYSIS_GRAPH_BACKEND", "neo4j")
    if backend == "fake":
        from analysis.backends.fake import FakeGraphBackend

        return FakeGraphBackend()
    from analysis.backends.neo4j_backend import Neo4jBackend

    return Neo4jBackend(
        uri=settings.NEO4J_URI,
        user=settings.NEO4J_USER,
        password=settings.NEO4J_PASSWORD,
    )
