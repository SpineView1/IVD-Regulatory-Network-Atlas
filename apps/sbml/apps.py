"""Django AppConfig for the sbml app."""
from __future__ import annotations

from django.apps import AppConfig


class SbmlConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "sbml"
    verbose_name = "SBML emission and versioning"
