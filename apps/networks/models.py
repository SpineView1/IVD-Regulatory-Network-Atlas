"""networks models — Network, NetworkQuery, FamilyFilter.

A Network is a regulatory module the system is trying to assemble
(e.g. "NF-κB axis", "TGF-β / BMP / SMAD"). It carries the metadata
needed by every downstream stage:

- ``keywords`` and ``root_entity_aliases`` drive the cheap relevance
  pass in ``corpus.triage_relevance_cheap``.
- ``pipeline_status`` is the per-network state machine from spec §7.
- NetworkQuery rows hold the PubMed/Europe PMC query strings used by
  ``corpus.refresh_pubmed`` for network-targeted discovery.
- FamilyFilter constrains which protein families are eligible to
  appear in this network (per spec §2).
"""

from __future__ import annotations

from django.db import models

from core.models import TimestampedModel


class Network(TimestampedModel):
    PIPELINE_STATUS_CHOICES = [
        ("idle", "idle"),
        ("refreshing", "refreshing"),
        ("stale", "stale"),
        ("version_draft", "version_draft"),
        ("verified", "verified"),
    ]

    code = models.SlugField(max_length=64, unique=True)
    category = models.CharField(max_length=8)
    title = models.CharField(max_length=256)
    description = models.TextField(blank=True, default="")
    keywords = models.JSONField(default=list, blank=True)
    # Free-text alias strings ("NF-κB", "RelA", "p65") for cheap keyword
    # relevance triage.
    root_entity_aliases = models.JSONField(default=list, blank=True)
    # Structured identifier dicts ({"scheme": "HGNC", "value": "7794"}) used by
    # Phase 3's NetworkEdgeMembership assignment. Distinct from the aliases
    # above. See cross-plan reconciliation doc §6/§8.
    root_entities = models.JSONField(default=list, blank=True)
    pipeline_status = models.CharField(
        max_length=24, choices=PIPELINE_STATUS_CHOICES, default="idle"
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "networks_network"
        ordering = ["category", "code"]

    def __str__(self) -> str:
        return f"Network<{self.code}>"


class NetworkQuery(TimestampedModel):
    PURPOSE_CHOICES = [
        ("discovery", "discovery"),
        ("triage_cheap", "triage_cheap"),
        ("expansion", "expansion"),
    ]

    network = models.ForeignKey(Network, related_name="queries", on_delete=models.CASCADE)
    purpose = models.CharField(max_length=24, choices=PURPOSE_CHOICES)
    query = models.TextField()
    notes = models.TextField(blank=True, default="")

    class Meta:
        db_table = "networks_networkquery"
        constraints = [
            models.UniqueConstraint(
                fields=["network", "purpose"], name="uniq_network_query_purpose"
            )
        ]


class FamilyFilter(TimestampedModel):
    network = models.ForeignKey(Network, related_name="family_filters", on_delete=models.CASCADE)
    family_name = models.CharField(max_length=128)
    uniprot_family_id = models.CharField(max_length=32, blank=True, default="")
    members = models.JSONField(default=list, blank=True)
    is_inclusion = models.BooleanField(default=True)

    class Meta:
        db_table = "networks_familyfilter"
