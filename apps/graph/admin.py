"""Django admin registrations for graph models."""

from __future__ import annotations

from django.contrib import admin

from graph.models import Conflict, Edge, EdgeEvidence, Entity, NetworkEdgeMembership


@admin.register(Entity)
class EntityAdmin(admin.ModelAdmin):
    list_display = ("preferred_label", "ontology_entity", "created_at")
    search_fields = ("ontology_entity__preferred_label",)


class EdgeEvidenceInline(admin.TabularInline):
    model = EdgeEvidence
    extra = 0
    readonly_fields = ("raw_ppi", "created_at")


@admin.register(Edge)
class EdgeAdmin(admin.ModelAdmin):
    list_display = ("__str__", "status", "belief_score", "created_at")
    list_filter = ("status", "relation")
    search_fields = (
        "source__ontology_entity__preferred_label",
        "target__ontology_entity__preferred_label",
    )
    readonly_fields = ("belief_score", "status", "created_at", "updated_at")
    inlines = [EdgeEvidenceInline]


@admin.register(Conflict)
class ConflictAdmin(admin.ModelAdmin):
    list_display = ("__str__", "conflict_type", "resolution_status", "created_at")
    list_filter = ("conflict_type", "resolution_status")


@admin.register(NetworkEdgeMembership)
class NetworkEdgeMembershipAdmin(admin.ModelAdmin):
    list_display = ("network", "edge", "relevance")
    list_filter = ("network",)
