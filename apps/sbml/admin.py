"""Django admin registration for sbml models."""

from __future__ import annotations

from django.contrib import admin

from sbml.models import ExportArtifact, ModelVersion


@admin.register(ModelVersion)
class ModelVersionAdmin(admin.ModelAdmin):
    list_display = ("network", "semver", "frozen_at", "n_species", "n_reactions", "n_edges")
    list_filter = ("network", "frozen_at")
    search_fields = ("network__code", "semver")
    # All fields that must not be mutated after a version is frozen (spec §3).
    # Keeping them read-only in the admin prevents silent corruption of the
    # immutable snapshot even for superusers.
    readonly_fields = (
        "frozen_at",
        "created_at",
        "updated_at",
        "semver",
        "frozen_edges",
        "sbml_s3_key",
        "csv_s3_key",
        "evidence_csv_s3_key",
        "zip_s3_key",
        "n_species",
        "n_reactions",
        "n_edges",
        "generated_from_edges",
    )


@admin.register(ExportArtifact)
class ExportArtifactAdmin(admin.ModelAdmin):
    list_display = ("model_version", "downloaded_by", "artifact_type", "downloaded_at")
    list_filter = ("artifact_type", "downloaded_at")
    search_fields = ("model_version__network__code", "downloaded_by__username")
    # ExportArtifact is an append-only audit log; every column is set at
    # creation time and must never be edited through the admin.
    readonly_fields = (
        "model_version",
        "downloaded_by",
        "downloaded_at",
        "artifact_type",
        "s3_key",
        "user_agent",
        "remote_addr",
    )
