"""Django AppConfig for the schedule app."""

from __future__ import annotations

from django.apps import AppConfig


class ScheduleConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "schedule"
    verbose_name = "Schedule (Beat, rate limits, janitors)"

    def ready(self) -> None:
        from schedule import metrics  # noqa: PLC0415 — deferred to avoid circular imports

        metrics.register_collectors()
