"""papers models — Section, Chunk, PaperClassification.

Section: one row per DoCO-tagged section of a paper.
Chunk: atomic LLM input. Denormalises `paper_id` so the extractor can
  filter without joining (spec §3: indexed on (paper_id, section_doco_type)).
PaperClassification: persisted output of the is_original classifier.
"""

from __future__ import annotations

from collections.abc import Iterable

from django.db import models

from core.models import TimestampedModel
from corpus.models import Paper


class Section(TimestampedModel):
    paper = models.ForeignKey(Paper, related_name="sections", on_delete=models.CASCADE)
    order_index = models.PositiveSmallIntegerField()
    doco_type = models.CharField(max_length=32, db_index=True)
    doco_iri = models.URLField(blank=True, default="")
    heading = models.CharField(max_length=512, blank=True, default="")
    body_text = models.TextField()
    token_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "papers_section"
        constraints = [
            models.UniqueConstraint(
                fields=["paper", "order_index"], name="uniq_paper_section_index"
            )
        ]
        ordering = ["paper", "order_index"]
        indexes = [models.Index(fields=["paper", "doco_type"])]


class Chunk(TimestampedModel):
    section = models.ForeignKey(Section, related_name="chunks", on_delete=models.CASCADE)
    paper = models.ForeignKey(
        Paper, related_name="chunks", on_delete=models.CASCADE, editable=False
    )
    chunk_index = models.PositiveSmallIntegerField()
    text = models.TextField()
    token_count = models.PositiveIntegerField()
    char_offset_start = models.PositiveIntegerField()
    char_offset_end = models.PositiveIntegerField()
    processed_by_models = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = "papers_chunk"
        constraints = [
            models.UniqueConstraint(
                fields=["section", "chunk_index"], name="uniq_section_chunk_index"
            )
        ]
        indexes = [
            models.Index(fields=["paper", "section"]),
        ]

    def save(  # type: ignore[override]
        self,
        force_insert: bool = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        if self.section_id and not self.paper_id:
            self.paper_id = self.section.paper_id
            if update_fields is not None and "paper" not in update_fields:
                update_fields = list(update_fields) + ["paper"]
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )


class PaperClassification(TimestampedModel):
    CLASSIFIER_CHOICES = [
        ("rule:pubtype", "rule:pubtype"),
        ("llm:qwen3:8b", "llm:qwen3:8b"),
    ]

    paper = models.OneToOneField(Paper, related_name="classification", on_delete=models.CASCADE)
    is_original = models.BooleanField()
    confidence = models.FloatField()
    classifier = models.CharField(max_length=32, choices=CLASSIFIER_CHOICES)
    reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "papers_paperclassification"
