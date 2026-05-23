"""Django admin registration for sbml models."""

from __future__ import annotations

from django.contrib import admin

from sbml.models import ExportArtifact, ModelVersion


@admin.register(ModelVersion)
class ModelVersionAdmin(admin.ModelAdmin):
    list_display = ("network", "semver", "frozen_at", "n_species", "n_reactions", "n_edges")
    list_filter = ("network", "frozen_at")
    search_fields = ("network__code", "semver")
    readonly_fields = ("frozen_at", "created_at", "updated_at")


@admin.register(ExportArtifact)
class ExportArtifactAdmin(admin.ModelAdmin):
    list_display = ("model_version", "downloaded_by", "artifact_type", "downloaded_at")
    list_filter = ("artifact_type", "downloaded_at")
    search_fields = ("model_version__network__code", "downloaded_by__username")
