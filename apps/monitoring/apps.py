"""Django AppConfig for the monitoring app."""

from __future__ import annotations

from django.apps import AppConfig


class MonitoringConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "monitoring"
    verbose_name = "Monitoring (health + feature flags)"
