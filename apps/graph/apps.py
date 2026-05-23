"""AppConfig for the graph app."""

from __future__ import annotations

from django.apps import AppConfig


class GraphConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "graph"
    verbose_name = "Graph (entities, edges, conflicts)"
