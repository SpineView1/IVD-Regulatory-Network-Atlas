"""Core models — abstract bases and shared concrete models."""
from __future__ import annotations

from django.db import models


class TimestampedModel(models.Model):
    """Abstract base that adds ``created_at`` and ``updated_at``.

    Every concrete model in the project should inherit from this so that
    audit timestamps are uniform across the schema.
    """

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        abstract = True
