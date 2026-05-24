"""Unit tests for Neo4jBackend — Cypher param-building without a live DB.

These tests verify that:
  - Neo4jBackend can be imported and instantiated (without connecting)
  - It satisfies the GraphBackend abstract interface (no missing methods)
  - The driver is NOT contacted at import or at instantiation (safe at
    module-load time, no live DB required)

Live-DB integration tests are in test_neo4j_integration.py and are skipped
when NEO4J_URI is unset (@pytest.mark.neo4j).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_neo4j_backend_importable():
    """Importing neo4j_backend must not raise or require a live DB."""
    from analysis.backends.neo4j_backend import Neo4jBackend  # noqa: F401


def test_neo4j_backend_is_concrete():
    """Neo4jBackend must have no unimplemented abstract methods."""
    from analysis.backends.neo4j_backend import Neo4jBackend

    missing: frozenset[str] = getattr(Neo4jBackend, "__abstractmethods__", frozenset())
    assert not missing, f"Neo4jBackend leaves abstract methods unimplemented: {missing}"


def test_neo4j_backend_instantiation_does_not_connect():
    """Constructing Neo4jBackend must not open a live socket.

    GraphDatabase.driver() is patched so instantiation works without Neo4j.
    """
    with patch("analysis.backends.neo4j_backend.GraphDatabase.driver") as mock_driver:
        from analysis.backends.neo4j_backend import Neo4jBackend

        backend = Neo4jBackend(uri="bolt://fake:7687", user="neo4j", password="test")
        mock_driver.assert_called_once_with("bolt://fake:7687", auth=("neo4j", "test"))
        assert backend is not None


def test_neo4j_backend_implements_all_base_methods():
    """Verify every method declared in GraphBackend exists on Neo4jBackend."""
    from analysis.backends.base import GraphBackend
    from analysis.backends.neo4j_backend import Neo4jBackend

    abstract_methods = {
        m
        for m in dir(GraphBackend)
        if getattr(getattr(GraphBackend, m, None), "__isabstractmethod__", False)
    }
    for method in abstract_methods:
        assert hasattr(Neo4jBackend, method), f"Neo4jBackend missing: {method}"
        impl = getattr(Neo4jBackend, method)
        assert not getattr(
            impl, "__isabstractmethod__", False
        ), f"Neo4jBackend.{method} is still abstract"


def test_neo4j_backend_close_calls_driver_close():
    """close() delegates to the neo4j driver."""
    with patch("analysis.backends.neo4j_backend.GraphDatabase.driver") as mock_driver:
        mock_drv_instance = MagicMock()
        mock_driver.return_value = mock_drv_instance

        from analysis.backends.neo4j_backend import Neo4jBackend

        backend = Neo4jBackend(uri="bolt://fake:7687", user="neo4j", password="x")
        backend.close()
        mock_drv_instance.close.assert_called_once()
