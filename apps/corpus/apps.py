"""Django AppConfig for the corpus app."""

from __future__ import annotations

from django.apps import AppConfig


class CorpusConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "corpus"
    verbose_name = "Corpus (master IDD paper database)"

    def ready(self) -> None:
        # Importing the module registers its @receiver-decorated handlers.
        from corpus import receivers  # noqa: F401, PLC0415
