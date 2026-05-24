"""Graph backends. The factory hides which implementation is active."""

from __future__ import annotations

from django.conf import settings

from analysis.backends.base import GraphBackend

# Module-level singleton for the Neo4j backend.  Built once on first request
# and reused thereafter to avoid opening a new connection pool on every call.
# The fake backend is intentionally NOT cached — tests may rely on a fresh
# instance, and it is cheap to construct.
_neo4j_singleton: GraphBackend | None = None


def _reset_neo4j_singleton() -> None:  # private; used by tests that need a clean slate
    global _neo4j_singleton
    _neo4j_singleton = None


def get_backend() -> GraphBackend:
    """Return the configured GraphBackend instance.

    Selected by settings.ANALYSIS_GRAPH_BACKEND ("neo4j" | "fake").
    Tests flip this to "fake" via the settings fixture; production uses
    "neo4j". Importing the neo4j backend is deferred so the fake path has
    no hard dependency on a running database.

    The Neo4jBackend is cached as a module-level singleton so that only one
    driver (and its underlying connection pool) is ever opened per process.
    """
    global _neo4j_singleton

    backend = getattr(settings, "ANALYSIS_GRAPH_BACKEND", "neo4j")
    if backend == "fake":
        from analysis.backends.fake import FakeGraphBackend

        return FakeGraphBackend()

    if _neo4j_singleton is None:
        from analysis.backends.neo4j_backend import Neo4jBackend

        _neo4j_singleton = Neo4jBackend(
            uri=settings.NEO4J_URI,
            user=settings.NEO4J_USER,
            password=settings.NEO4J_PASSWORD,
        )
    return _neo4j_singleton
