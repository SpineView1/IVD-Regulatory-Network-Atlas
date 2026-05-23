"""Django AppConfig for the dashboard app."""

from __future__ import annotations

from django.apps import AppConfig


class DashboardConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "dashboard"
    verbose_name = "Dashboard (read-only operator views)"
