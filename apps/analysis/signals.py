"""Signal receivers for the analysis app.

Connects to graph.signals.edges_integrated and dispatches the
project_edges Celery task by name (no static import of analysis into graph).
"""

from __future__ import annotations

from django.dispatch import receiver

from celery import current_app
from graph.signals import edges_integrated


@receiver(edges_integrated, dispatch_uid="analysis.project_on_edges_integrated")
def on_edges_integrated(
    sender: object,
    touched_edges: set[int] | None = None,
    **kwargs: object,
) -> None:
    """Receive edge-integration events and schedule incremental projection.

    Dispatches project_edges by task name so graph never imports analysis.
    Dispatches nothing when the touched set is empty or absent.
    """
    ids = list(touched_edges or [])
    if not ids:
        return
    current_app.send_task(
        "analysis.tasks.project_edges",
        args=[ids],
        queue="q.io",
    )
