"""Signal receivers for the analysis app.

Connects to graph.signals.edges_integrated and dispatches the
project_edges Celery task by name (no static import of analysis into graph).
"""
from __future__ import annotations

from django.dispatch import receiver

from graph.signals import edges_integrated


@receiver(edges_integrated)
def on_edges_integrated(
    sender: object,
    touched_edges: set[int],
    **kwargs: object,
) -> None:
    """Receive edge-integration events and schedule incremental projection.

    Dispatches project_edges by task name so graph never imports analysis.
    """
    import celery  # noqa: PLC0415

    celery.current_app.send_task(
        "analysis.tasks.project_edges",
        args=[list(touched_edges)],
    )
