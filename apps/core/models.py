"""Core models — abstract bases and shared concrete models."""

from __future__ import annotations

from django.db import models
from django.db.models import CheckConstraint, Q, UniqueConstraint


class TimestampedModel(models.Model):
    """Abstract base that adds ``created_at`` and ``updated_at``.

    Every concrete model in the project should inherit from this so that
    audit timestamps are uniform across the schema.
    """

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        abstract = True


class OntologyEntity(TimestampedModel):
    """A canonical biological concept (gene, protein, miRNA, metabolite, complex).

    The graph layer's ``Entity`` rows point here; provenance and tools that
    care about the underlying ontology dereference via the ``identifiers``
    reverse relation.
    """

    ENTITY_TYPES = [
        ("gene", "Gene"),
        ("protein", "Protein"),
        ("mirna", "microRNA"),
        ("lncrna", "lncRNA"),
        ("metabolite", "Metabolite"),
        ("complex", "Complex"),
        ("cell_type", "Cell type"),
        ("phenotype", "Phenotype"),
        ("other", "Other"),
    ]

    entity_type = models.CharField(max_length=32, choices=ENTITY_TYPES, db_index=True)
    preferred_label = models.CharField(max_length=255, db_index=True)
    description = models.TextField(blank=True, default="")
    # Cellular compartment for SBML-qual compartment assignment (Phase 4).
    # See cross-plan reconciliation doc §5/§8.
    compartment = models.CharField(max_length=32, blank=True, default="cytoplasm")
    # Primary identifiers.org URI (derived from the preferred Identifier).
    # Consumed by Phase 4 SBML MIRIAM annotation. See reconciliation doc §5/§8.
    canonical_uri = models.URLField(blank=True, default="")

    class Meta:
        constraints = [
            CheckConstraint(
                condition=~Q(preferred_label=""),
                name="ontologyentity_label_nonempty",
            ),
        ]
        indexes = [
            models.Index(fields=["entity_type", "preferred_label"]),
        ]

    def __str__(self) -> str:
        return f"{self.preferred_label} ({self.entity_type})"


class Identifier(TimestampedModel):
    """One external identifier for an ``OntologyEntity``.

    A single concept can have many identifiers (UNIPROT + HGNC + ENSEMBL +
    NCBI Gene + ...). The ``(entity, scheme, value)`` triple is unique so
    the same (scheme, value) can exist on different entities.
    """

    SCHEMES = [
        ("HGNC", "HGNC"),
        ("UNIPROT", "UniProt"),
        ("ENSEMBL", "Ensembl"),
        ("NCBI_GENE", "NCBI Gene"),
        ("CHEBI", "ChEBI"),
        ("MIRBASE", "miRBase"),
        ("MESH", "MeSH"),
        ("GO", "Gene Ontology"),
        ("CL", "Cell Ontology"),
        ("DOID", "Disease Ontology"),
        ("REACTOME", "Reactome"),
        ("OTHER", "Other"),
    ]

    entity = models.ForeignKey(
        OntologyEntity,
        related_name="identifiers",
        on_delete=models.CASCADE,
    )
    scheme = models.CharField(max_length=32, choices=SCHEMES, db_index=True)
    value = models.CharField(max_length=128, db_index=True)
    is_primary = models.BooleanField(default=False)

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["entity", "scheme", "value"],
                name="identifier_unique_per_entity_scheme_value",
            ),
        ]
        indexes = [
            models.Index(fields=["scheme", "value"]),
        ]

    def as_iri(self) -> str:
        """Return the canonical identifiers.org IRI for this identifier."""
        prefix = self.scheme.lower()
        # ChEBI's identifiers.org pattern keeps the CHEBI: prefix in the value.
        if self.scheme == "CHEBI" and not self.value.upper().startswith("CHEBI:"):
            value = f"CHEBI:{self.value}"
        else:
            value = self.value
        return f"https://identifiers.org/{prefix}:{value}"

    def __str__(self) -> str:
        return f"{self.scheme}:{self.value}"
