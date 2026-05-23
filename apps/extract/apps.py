"""Django AppConfig for the extract app."""

from __future__ import annotations

from django.apps import AppConfig


class ExtractConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "extract"
    verbose_name = "Extraction (PPI tuples from chunks)"

    def ready(self) -> None:
        """Register ExtractionRun with the janitor sweep.

        The janitor (schedule.tasks.janitor_reset_stale_running) scans every
        registered model for rows in status='running' with stale heartbeats
        and resets them to status='queued'. Per spec §8, the stale threshold
        for ExtractionRun is 10 minutes.
        """
        from schedule.tasks import register_janitor_target

        register_janitor_target(
            app_label="extract",
            model_name="ExtractionRun",
            status_field="status",
            heartbeat_field="heartbeat",
            attempts_field="attempts",
        )
