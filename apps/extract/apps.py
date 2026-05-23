"""Django AppConfig for the extract app."""
from __future__ import annotations

from django.apps import AppConfig


class ExtractConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "extract"
    verbose_name = "Extraction (PPI tuples from chunks)"
