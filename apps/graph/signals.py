"""graph.signals — Django signals emitted by the graph app.

Phase 8 (analysis app / Neo4j projection) connects to ``edges_integrated``.
The graph app NEVER imports the analysis app — dependency arrow is
``analysis → graph`` only (see reconciliation doc §12.A).

Signal contract (reconciliation doc §12.A):
  sender:        graph.services.normalize_and_integrate (the function)
  touched_edges: set[int] — the edge PKs that were created or updated
  raws:          list[RawPPI] — the raw PPI rows that were processed
"""

from __future__ import annotations

from django.dispatch import Signal

# Emitted at the end of normalize_and_integrate after all edges and
# belief scores are committed to the database.
#
# Receivers (e.g. analysis/signals.py) dispatch:
#   celery.current_app.send_task("analysis.tasks.project_edges",
#                                args=[list(touched_edges)])
#
# Guard test ``test_graph_does_not_import_analysis`` enforces that
# no code in the ``graph`` app imports the ``analysis`` app.
edges_integrated = Signal()
