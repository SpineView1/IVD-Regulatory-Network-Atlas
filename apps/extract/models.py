"""extract models — ExtractionRun, RawPPI, PromptTemplate.

Per spec §3:
  • ExtractionRun is the resumability anchor (status, heartbeat, attempts).
  • RawPPI is the terminal artifact — never deleted, audit trail.
  • PromptTemplate versions the prompt so iteration doesn't invalidate
    prior extractions.
"""

from __future__ import annotations

from django.db import models

from core.models import TimestampedModel


class PromptTemplate(TimestampedModel):
    """Versioned prompt body. One row per prompt iteration; exactly one
    row is ``is_active=True`` at any moment (enforced by partial unique
    index)."""

    version = models.CharField(max_length=32, unique=True)
    body = models.TextField()
    is_active = models.BooleanField(default=False)
    notes = models.TextField(blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["is_active"],
                condition=models.Q(is_active=True),
                name="extract_prompt_only_one_active",
            ),
        ]

    def __str__(self) -> str:
        marker = " (active)" if self.is_active else ""
        return f"PromptTemplate v{self.version}{marker}"


class ExtractionRun(TimestampedModel):
    """One row per (chunk × model × prompt_version). Drives resumability."""

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        DONE = "done", "Done"
        FAILED = "failed", "Failed"

    chunk = models.ForeignKey(
        "papers.Chunk", on_delete=models.CASCADE, related_name="extraction_runs"
    )
    model_name = models.CharField(max_length=64)
    prompt_version = models.CharField(max_length=32)

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    heartbeat = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    error = models.TextField(blank=True, default="")

    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    response_tokens = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["chunk", "model_name", "prompt_version"],
                name="extract_run_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "heartbeat"]),
            models.Index(fields=["model_name", "status"]),
        ]

    def __str__(self) -> str:
        return (
            f"ExtractionRun(chunk={self.chunk_id}, model={self.model_name},"
            f" status={self.status})"
        )


class RawPPI(TimestampedModel):
    """The terminal artifact: one extracted tuple as the LLM emitted it.

    Never deleted; the graph phase reads these and produces normalised
    ``Entity``/``Edge`` rows downstream. ``ungrounded`` is set later by
    graph.normalize_and_integrate when neither subject nor object can be
    mapped to an ontology identifier (spec §4 failure-handling table).
    """

    run = models.ForeignKey(ExtractionRun, on_delete=models.CASCADE, related_name="raw_ppis")

    subject = models.CharField(max_length=128)
    object = models.CharField(max_length=128)
    relation = models.CharField(max_length=32)
    evidence_span = models.TextField()
    evidence_offset_start = models.PositiveIntegerField()
    evidence_offset_end = models.PositiveIntegerField()
    cell_type = models.CharField(max_length=128, null=True, blank=True)  # noqa: DJ001
    stimulus = models.CharField(max_length=256, null=True, blank=True)  # noqa: DJ001
    confidence = models.FloatField()

    # logprob of the first token of the chosen ``relation`` value;
    # captured per spec §4 (``logprobs=true`` on /api/generate). Used
    # by the graph phase's Bayes belief update.
    relation_logprob = models.FloatField(null=True, blank=True)

    ungrounded = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=["run"]),
            models.Index(fields=["ungrounded"]),
        ]

    def __str__(self) -> str:
        return f"RawPPI({self.subject} {self.relation} {self.object})"
