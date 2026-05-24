"""monitoring models — HealthAlert and FeatureFlag.

Both tables are tiny (≤ hundreds of rows in steady state) and have no
foreign-key relationships outside this app. They are read by Beat tasks
on every tick, so primary-key lookups and a partial index on
``HealthAlert(resolved_at)`` are the only performance considerations.
"""
from __future__ import annotations

from django.db import models
from django.utils import timezone

from core.models import TimestampedModel


class FeatureFlag(TimestampedModel):
    """Single-row global toggle, keyed by ``name``.

    Beat tasks read ``FeatureFlag.objects.get(name='INGESTION_PAUSED').value``
    before doing real work. ``select_related`` is unnecessary; the row
    is cached in the worker memory by Django's query cache within a
    request/task.
    """

    name = models.CharField(max_length=64, unique=True)
    value = models.BooleanField(default=False)
    last_changed_by = models.CharField(max_length=150, blank=True, default="")
    last_changed_reason = models.TextField(blank=True, default="")

    class Meta:
        indexes = [models.Index(fields=["name"])]

    def __str__(self) -> str:
        return f"{self.name}={self.value}"


class HealthAlert(TimestampedModel):
    """One row per health-check failure. Append-only audit trail."""

    SEVERITY_CHOICES = [
        ("info", "Info"),
        ("warning", "Warning"),
        ("error", "Error"),
        ("critical", "Critical"),
    ]

    check_name = models.CharField(max_length=128, db_index=True)
    severity = models.CharField(max_length=16, choices=SEVERITY_CHOICES)
    message = models.TextField()
    context = models.JSONField(default=dict, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True, db_index=True)
    resolved_by = models.CharField(max_length=150, blank=True, default="")
    resolution_note = models.TextField(blank=True, default="")

    class Meta:
        indexes = [
            models.Index(
                fields=["check_name", "created_at"],
                name="health_check_recent_idx",
            ),
        ]

    @property
    def is_open(self) -> bool:
        return self.resolved_at is None

    def resolve(self, *, by: str, note: str = "") -> None:
        self.resolved_at = timezone.now()
        self.resolved_by = by
        self.resolution_note = note
        self.save(update_fields=["resolved_at", "resolved_by", "resolution_note", "updated_at"])
