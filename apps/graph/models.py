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
