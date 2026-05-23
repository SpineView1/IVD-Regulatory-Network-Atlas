"""schedule models — Watermark, RateLimitBucket, ScheduledJob.

These three tables hold all the durable cross-task coordination state:
- Watermark: how far each external-source ingestion has progressed.
- RateLimitBucket: token bucket per provider, persisted so restarts
  don't reset budget. (per spec §5 / §6)
- ScheduledJob: bookkeeping for Beat-driven periodic tasks.
"""

from __future__ import annotations

from django.db import models, transaction
from django.utils import timezone

from core.models import TimestampedModel


class RateLimitBucket(TimestampedModel):
    """Token-bucket for one outbound provider.

    `consume(cost)` is the public API: returns True if a token was
    deducted (and persists the decrement), False if the bucket is empty.
    Callers re-enqueue with `countdown=seconds_until_refill(cost)` on
    a False return.
    """

    provider = models.CharField(max_length=64, unique=True)
    capacity = models.PositiveIntegerField()
    refill_per_sec = models.FloatField()
    current_tokens = models.FloatField()

    class Meta:
        db_table = "schedule_ratelimitbucket"

    def __str__(self) -> str:
        return f"{self.provider}: {self.current_tokens:.1f}/{self.capacity}"

    def refill(self) -> None:
        """Advance tokens based on wall-clock elapsed since updated_at."""
        with transaction.atomic():
            locked = RateLimitBucket.objects.select_for_update().get(pk=self.pk)
            elapsed = (timezone.now() - locked.updated_at).total_seconds()
            replenished = locked.current_tokens + (elapsed * locked.refill_per_sec)
            locked.current_tokens = min(replenished, float(locked.capacity))
            locked.save(update_fields=["current_tokens", "updated_at"])

    def consume(self, cost: int = 1) -> bool:
        """Atomically deduct `cost` tokens if available."""
        with transaction.atomic():
            locked = RateLimitBucket.objects.select_for_update().get(pk=self.pk)
            elapsed = (timezone.now() - locked.updated_at).total_seconds()
            replenished = min(
                locked.current_tokens + (elapsed * locked.refill_per_sec),
                float(locked.capacity),
            )
            if replenished < cost:
                locked.current_tokens = replenished
                locked.save(update_fields=["current_tokens", "updated_at"])
                self.current_tokens = locked.current_tokens
                return False
            locked.current_tokens = replenished - cost
            locked.save(update_fields=["current_tokens", "updated_at"])
            self.current_tokens = locked.current_tokens
            return True

    def seconds_until_refill(self, cost: int = 1) -> float:
        """How long the caller should wait before retrying."""
        deficit = max(0.0, cost - self.current_tokens)
        if self.refill_per_sec <= 0:
            return float("inf")
        return deficit / self.refill_per_sec


class Watermark(TimestampedModel):
    """One row per external source. Tracks how far ingestion has progressed."""

    source = models.CharField(max_length=64, unique=True)
    last_entrez_date = models.DateField(null=True, blank=True)
    last_pmid_seen = models.BigIntegerField(null=True, blank=True)
    resumption_token = models.TextField(blank=True, default="")
    notes = models.TextField(blank=True, default="")

    class Meta:
        db_table = "schedule_watermark"

    def __str__(self) -> str:
        return f"watermark<{self.source}>"


class ScheduledJob(TimestampedModel):
    """Lightweight log of Beat-driven jobs: when did each task last run?"""

    STATUS_CHOICES = [
        ("never_run", "never_run"),
        ("running", "running"),
        ("done", "done"),
        ("failed", "failed"),
    ]
    name = models.CharField(max_length=128, unique=True)
    cadence_seconds = models.PositiveIntegerField()
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="never_run")
    last_error = models.TextField(blank=True, default="")

    class Meta:
        db_table = "schedule_scheduledjob"

    def mark_running(self) -> None:
        self.last_run_at = timezone.now()
        self.last_status = "running"
        self.save(update_fields=["last_run_at", "last_status", "updated_at"])

    def mark_done(self) -> None:
        self.last_status = "done"
        self.last_error = ""
        self.save(update_fields=["last_status", "last_error", "updated_at"])

    def mark_failed(self, error: str) -> None:
        self.last_status = "failed"
        self.last_error = error[:4000]
        self.save(update_fields=["last_status", "last_error", "updated_at"])
