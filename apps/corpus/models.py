"""corpus models — Paper, PaperRelevance, IngestRun.

Paper.pmid is the primary key (per spec §3). All ingest pipeline state
lives on Paper rows so resumability is automatic.
"""

from __future__ import annotations

from django.db import models

from core.models import TimestampedModel
from networks.models import Network


class Paper(TimestampedModel):
    INGEST_STATUS_CHOICES = [
        ("pending", "pending"),
        ("running", "running"),
        ("ingested", "ingested"),
        ("classified", "classified"),
        ("fetched", "fetched"),
        ("chunked", "chunked"),
        ("done", "done"),
        ("failed", "failed"),
        ("ingest_failed", "ingest_failed"),
    ]
    FULL_TEXT_STATUS_CHOICES = [
        ("none", "none"),
        ("abstract_only", "abstract_only"),
        ("pmc_jats", "pmc_jats"),
        ("grobid_tei", "grobid_tei"),
        ("fetch_failed", "fetch_failed"),
    ]

    pmid = models.BigIntegerField(primary_key=True)
    doi = models.CharField(max_length=128, blank=True, default="", db_index=True)
    pmcid = models.CharField(max_length=32, blank=True, default="", db_index=True)
    title = models.TextField()
    abstract = models.TextField(blank=True, default="")
    authors = models.JSONField(default=list, blank=True)
    journal = models.CharField(max_length=256, blank=True, default="")
    publication_date = models.DateField(null=True, blank=True)
    entrez_date = models.DateField(null=True, blank=True, db_index=True)
    publication_types = models.JSONField(default=list, blank=True)
    mesh_terms = models.JSONField(default=list, blank=True)
    pubtator_entities = models.JSONField(default=list, blank=True)

    is_original = models.BooleanField(null=True, blank=True)
    classification_confidence = models.FloatField(null=True, blank=True)
    classification_reason = models.TextField(blank=True, default="")

    full_text_status = models.CharField(
        max_length=24, choices=FULL_TEXT_STATUS_CHOICES, default="none"
    )
    fulltext_s3_key = models.CharField(max_length=256, blank=True, default="")
    fulltext_fetch_error = models.TextField(blank=True, default="")

    ingest_status = models.CharField(
        max_length=24, choices=INGEST_STATUS_CHOICES, default="pending", db_index=True
    )
    ingest_attempts = models.PositiveIntegerField(default=0)
    ingest_heartbeat = models.DateTimeField(null=True, blank=True)
    ingest_error = models.TextField(blank=True, default="")

    class Meta:
        db_table = "corpus_paper"
        indexes = [
            models.Index(fields=["ingest_status", "entrez_date"]),
            models.Index(fields=["is_original"]),
            models.Index(fields=["full_text_status"]),
        ]

    def __str__(self) -> str:
        return f"Paper<pmid={self.pmid}>"


class PaperRelevance(TimestampedModel):
    """Many-to-many between Paper and Network with relevance metadata.

    (per spec §5: "Result: many-to-many PaperRelevance. The corpus for
    network X is SELECT paper FROM PaperRelevance WHERE network=X AND
    relevance > 0.5".)
    """

    CLASSIFIED_BY_CHOICES = [
        ("cheap_keyword", "cheap_keyword"),
        ("cheap_pubtator", "cheap_pubtator"),
        ("llm:qwen3:8b", "llm:qwen3:8b"),
    ]

    paper = models.ForeignKey(Paper, related_name="relevances", on_delete=models.CASCADE)
    network = models.ForeignKey(Network, related_name="paper_relevances", on_delete=models.CASCADE)
    score = models.FloatField()
    classified_by = models.CharField(
        max_length=32, choices=CLASSIFIED_BY_CHOICES, default="cheap_keyword"
    )
    reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "corpus_paperrelevance"
        constraints = [
            models.UniqueConstraint(
                fields=["paper", "network"], name="uniq_paper_network_relevance"
            )
        ]
        indexes = [
            models.Index(fields=["network", "score"]),
        ]


class IngestRun(TimestampedModel):
    """One row per refresh-cycle. Audits how many papers came in per source."""

    SOURCE_CHOICES = [
        ("pubmed", "pubmed"),
        ("pubmed_full", "pubmed_full"),
        ("elink", "elink"),
        ("europe_pmc", "europe_pmc"),
    ]

    source = models.CharField(max_length=24, choices=SOURCE_CHOICES)
    query = models.TextField(blank=True, default="")
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    n_pmids_seen = models.PositiveIntegerField(default=0)
    n_papers_created = models.PositiveIntegerField(default=0)
    n_papers_updated = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True, default="")

    class Meta:
        db_table = "corpus_ingestrun"
        indexes = [models.Index(fields=["source", "started_at"])]
