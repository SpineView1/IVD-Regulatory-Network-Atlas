"""Graph models — Entity, Edge, EdgeEvidence, Conflict, NetworkEdgeMembership."""

from __future__ import annotations

from django.db import models

from core.models import Identifier, OntologyEntity, TimestampedModel


class Entity(TimestampedModel):
    """A normalized node in the graph.

    1:1 with OntologyEntity. The split exists so the graph app can hang
    graph-level metadata (cached aggregate degree, last_seen_at, etc.) on
    nodes without polluting the ontology layer.
    """

    ontology_entity = models.OneToOneField(
        OntologyEntity,
        on_delete=models.PROTECT,
        related_name="graph_entity",
    )

    class Meta:
        verbose_name_plural = "entities"

    @property
    def preferred_label(self) -> str:
        return self.ontology_entity.preferred_label

    @property
    def primary_identifier(self) -> Identifier | None:
        return (
            self.ontology_entity.identifiers.filter(is_primary=True).first()
            or self.ontology_entity.identifiers.first()
        )

    # Proxy properties so Phase 4 (SBML emission) can read flat attributes off
    # an Entity without knowing the OntologyEntity split. See reconciliation
    # doc §5/§8.
    @property
    def symbol(self) -> str:
        return self.ontology_entity.preferred_label

    @property
    def compartment(self) -> str:
        return self.ontology_entity.compartment or "cytoplasm"

    @property
    def canonical_uri(self) -> str:
        return self.ontology_entity.canonical_uri

    @property
    def miriam_uris(self) -> list[str]:
        scheme_prefix = {
            "UNIPROT": "uniprot",
            "HGNC": "hgnc",
            "CHEBI": "chebi",
            "MIRBASE": "mirbase",
        }
        uris = []
        for ident in self.ontology_entity.identifiers.all():
            prefix = scheme_prefix.get(ident.scheme.upper())
            if prefix:
                uris.append(f"https://identifiers.org/{prefix}:{ident.value}")
        return uris

    def __str__(self) -> str:
        return self.preferred_label


class Edge(TimestampedModel):
    """A normalized relationship between two entities.

    Unique on (source, target, relation). belief_score and status are
    derived state — recomputed by graph.services.recompute_edge_belief
    every time new evidence lands. Direct DB writes to those columns
    should only happen via that helper.
    """

    RELATIONS = [
        ("activates", "activates"),
        ("inhibits", "inhibits"),
        ("binds", "binds"),
        ("phosphorylates", "phosphorylates"),
        ("dephosphorylates", "dephosphorylates"),
        ("ubiquitinates", "ubiquitinates"),
        ("deubiquitinates", "deubiquitinates"),
        ("methylates", "methylates"),
        ("acetylates", "acetylates"),
        ("deacetylates", "deacetylates"),
        ("transcribes", "transcribes"),
        ("represses", "represses"),
        ("cleaves", "cleaves"),
        ("regulates", "regulates"),
    ]

    STATUSES = [
        ("candidate", "candidate"),
        ("accepted", "accepted"),
        ("conflicted", "conflicted"),
        ("rejected", "rejected"),
    ]

    source = models.ForeignKey(
        Entity,
        related_name="outgoing_edges",
        on_delete=models.PROTECT,
    )
    target = models.ForeignKey(
        Entity,
        related_name="incoming_edges",
        on_delete=models.PROTECT,
    )
    relation = models.CharField(max_length=32, choices=RELATIONS, db_index=True)
    belief_score = models.FloatField(default=0.0, db_index=True)
    # Denormalized counters set by normalize_and_integrate alongside
    # belief_score (the counts are already computed there as args to
    # bayes_belief). Consumed by Phase 4 (SBML annotations + edges.csv) and
    # Phase 5 (verification UI). See cross-plan reconciliation doc §4/§8.
    n_supporting_papers = models.PositiveIntegerField(default=0)
    n_models_agreeing = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=16,
        choices=STATUSES,
        default="candidate",
        db_index=True,
    )

    raw_ppis = models.ManyToManyField(
        "extract.RawPPI",
        through="graph.EdgeEvidence",
        related_name="edges",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["source", "target", "relation"],
                name="edge_unique_source_target_relation",
            ),
        ]
        indexes = [
            models.Index(fields=["source", "target"]),
            models.Index(fields=["status", "belief_score"]),
        ]

    def __str__(self) -> str:
        return f"{self.source} -{self.relation}-> {self.target}"


class EdgeEvidence(TimestampedModel):
    """One RawPPI supporting one Edge. Many-to-many through table.

    Never deleted, even when a RawPPI is superseded — the audit trail
    is load-bearing for the verification UI's provenance tree (spec §3
    "Provenance is a graph, not a string").
    """

    edge = models.ForeignKey(Edge, on_delete=models.CASCADE, related_name="evidence")
    raw_ppi = models.ForeignKey(
        "extract.RawPPI",
        on_delete=models.PROTECT,
        related_name="edge_evidence",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["edge", "raw_ppi"],
                name="edgeevidence_unique_edge_raw_ppi",
            ),
        ]


class Conflict(TimestampedModel):
    """A pair of edges that disagree (typically opposite relation).

    Three conflict_types per spec §4:
      * intra_paper — two extractions on the same chunk, opposite signs
      * inter_paper — same edge pair, different papers, opposite signs
      * inter_model — consensus across the 7 models is below majority

    Canonical resolution_status values (reconciliation doc §9.C):
      open / auto_resolved / human_resolved
    Phase 6 auto-resolver sets ``auto_resolved``; verify UI (Phase 5) sets
    ``human_resolved``. Do NOT add ``curator_resolved`` or ``ignored`` — this
    is the authoritative list.
    """

    CONFLICT_TYPES = [
        ("intra_paper", "intra-paper"),
        ("inter_paper", "inter-paper"),
        ("inter_model", "inter-model"),
    ]

    RESOLUTION_STATUSES = [
        ("open", "open"),
        ("auto_resolved", "auto-resolved"),
        ("human_resolved", "human-resolved"),
    ]

    # on_delete=CASCADE is intentional: a conflict is meaningless without both parties.
    edge_a = models.ForeignKey(
        Edge,
        on_delete=models.CASCADE,
        related_name="conflicts_as_a",
    )
    # on_delete=CASCADE is intentional: a conflict is meaningless without both parties.
    edge_b = models.ForeignKey(
        Edge,
        on_delete=models.CASCADE,
        related_name="conflicts_as_b",
    )
    conflict_type = models.CharField(
        max_length=16,
        choices=CONFLICT_TYPES,
        db_index=True,
    )
    resolution_status = models.CharField(
        max_length=24,
        choices=RESOLUTION_STATUSES,
        default="open",
        db_index=True,
    )
    # Phase 3 defines this field; Phase 6 reuses it (reconciliation doc §9.B).
    reasoning = models.TextField(blank=True, default="")
    # Phase 6: auto-resolver outcome fields (additive; reasoning NOT re-added).
    resolved_relation = models.CharField(max_length=64, blank=True, default="")
    resolved_at = models.DateTimeField(null=True, blank=True)
    auto_resolve_attempted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["edge_a", "edge_b", "conflict_type"],
                name="conflict_unique_pair_type",
            ),
        ]


class NetworkEdgeMembership(TimestampedModel):
    """An edge's membership in a network slice.

    The same Edge can appear in many networks — e.g. an IL1B→NFKB1 edge
    is relevant to NF-κB axis, to inflammatory networks, and to ECM
    catabolism networks. Each membership row carries a per-network
    relevance score (1.0 if either endpoint matches the network's
    root_entities directly, falling off for second-degree links).
    """

    network = models.ForeignKey(
        "networks.Network",
        on_delete=models.CASCADE,
        related_name="edge_memberships",
    )
    edge = models.ForeignKey(
        Edge,
        on_delete=models.CASCADE,
        related_name="network_memberships",
        null=True,
        blank=True,
    )
    relevance = models.FloatField(default=1.0, db_index=True)
    # Phase 6: pending-extraction fields. Set when detect_affected_networks
    # creates a placeholder membership before the extraction worker has
    # integrated the paper's RawPPIs into Edges. Cleared (edge set, flag
    # False) when graph.integrate_pending promotes them.
    pending_paper_id = models.IntegerField(null=True, blank=True, db_index=True)
    pending_extraction = models.BooleanField(default=False, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["network", "edge"],
                name="networkedgemembership_unique_network_edge",
                condition=models.Q(edge__isnull=False),
            ),
            # Durable DB-level idempotency for detect_affected_networks:
            # only one pending-extraction placeholder per (network, paper).
            # The condition restricts to NULL-edge rows so it does NOT
            # clash with the edge-based constraint above, and does NOT
            # affect Phase 3's reassign_network_membership (which always
            # writes a non-null edge) or Phase 8 projection (read-only).
            models.UniqueConstraint(
                fields=["network", "pending_paper_id"],
                name="networkedgemembership_unique_network_pending_paper",
                condition=models.Q(edge__isnull=True),
            ),
        ]
        indexes = [
            models.Index(fields=["network", "relevance"]),
            models.Index(
                fields=["pending_paper_id", "pending_extraction"],
                name="mem_pending_paper_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.network.code} ⊇ {self.edge}"
