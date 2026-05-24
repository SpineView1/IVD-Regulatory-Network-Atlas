"""corpus signal receivers — wire paper_ingested → detect_affected_networks."""

from __future__ import annotations

from django.dispatch import receiver

from corpus.signals import paper_ingested


@receiver(paper_ingested)
def on_paper_ingested(sender: object, **kwargs: object) -> None:
    """Enqueue per-network delta-detection for the newly-ingested paper."""
    from graph.tasks import detect_affected_networks  # noqa: PLC0415 — lazy to avoid circular

    paper_id: int = kwargs["paper_id"]  # type: ignore[assignment]
    detect_affected_networks.delay(paper_id)
