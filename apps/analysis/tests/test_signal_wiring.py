"""The edges_integrated signal must enqueue project_edges by task name.

Tests match the ACTUAL merged graph/services.py which emits `touched_edges`
(set[int]) not `edge_ids` — the plan's test snippet predated reconciliation.
"""

from __future__ import annotations

from unittest.mock import patch


def test_edges_integrated_enqueues_project_edges(db):
    from graph.signals import edges_integrated

    with patch("analysis.signals.current_app.send_task") as send_task:
        edges_integrated.send(sender=None, touched_edges={101, 102})

    send_task.assert_called_once()
    call_args = send_task.call_args
    # First positional arg is task name
    assert call_args[0][0] == "analysis.tasks.project_edges"
    # edge ids passed as first element of args list
    passed_ids = call_args[1].get("args", [None])[0]
    assert set(passed_ids) == {101, 102}


def test_edges_integrated_with_empty_set_does_not_enqueue(db):
    from graph.signals import edges_integrated

    with patch("analysis.signals.current_app.send_task") as send_task:
        edges_integrated.send(sender=None, touched_edges=set())

    send_task.assert_not_called()


def test_edges_integrated_with_none_does_not_enqueue(db):
    from graph.signals import edges_integrated

    with patch("analysis.signals.current_app.send_task") as send_task:
        edges_integrated.send(sender=None, touched_edges=None)

    send_task.assert_not_called()


def test_graph_does_not_import_analysis():
    """Static guard: importing graph.signals/services must not import analysis."""
    import sys

    for mod in list(sys.modules):
        if mod.startswith("analysis"):
            del sys.modules[mod]
    import graph.services  # noqa: F401
    import graph.signals  # noqa: F401

    assert not any(
        m == "analysis" or m.startswith("analysis.") for m in sys.modules
    ), "graph must not import analysis (would be circular)"
