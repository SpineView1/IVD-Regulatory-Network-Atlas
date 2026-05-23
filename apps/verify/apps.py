"""Django AppConfig for the verify app."""
from __future__ import annotations

from django.apps import AppConfig


class VerifyConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "verify"
    verbose_name = "Verification (reviews, sign-off, notifications)"
