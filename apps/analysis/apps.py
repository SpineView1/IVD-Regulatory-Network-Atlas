"""AnalysisConfig — wires the edges_integrated signal receiver on startup."""

from __future__ import annotations

from django.apps import AppConfig


class AnalysisConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "analysis"
    verbose_name = "Graph analysis & crosstalk"

    def ready(self) -> None:
        # Importing the module connects the @receiver. Safe at import time:
        # it imports graph.signals (allowed direction analysis -> graph).
        from analysis import signals  # noqa: F401
