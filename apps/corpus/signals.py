"""corpus signals.

``paper_ingested`` is fired by ``corpus.tasks.ingest_paper`` after a
new Paper row + its PaperRelevance rows are committed. Receivers should
be cheap (just enqueue downstream Celery tasks); they run synchronously
inside the ingest task's transaction-commit hook.
"""

from __future__ import annotations

from django.dispatch import Signal

# Sent with kwargs: paper_id (int), pmid (str), relevance_scores (dict[int,float])
paper_ingested = Signal()
