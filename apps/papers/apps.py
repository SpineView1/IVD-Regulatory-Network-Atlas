"""Django AppConfig for the papers app."""

from __future__ import annotations

from django.apps import AppConfig


class PapersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "papers"
    verbose_name = "Papers (sectioning and chunking)"
