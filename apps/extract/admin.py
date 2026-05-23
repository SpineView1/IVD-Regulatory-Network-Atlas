"""Django admin registrations for extract models."""

from __future__ import annotations

from django.contrib import admin

from extract.models import ExtractionRun, PromptTemplate, RawPPI


@admin.register(PromptTemplate)
class PromptTemplateAdmin(admin.ModelAdmin):
    list_display = ("version", "is_active", "updated_at")
    list_filter = ("is_active",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(ExtractionRun)
class ExtractionRunAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "chunk_id",
        "model_name",
        "prompt_version",
        "status",
        "attempts",
        "duration_ms",
        "updated_at",
    )
    list_filter = ("status", "model_name", "prompt_version")
    search_fields = ("chunk__id", "model_name", "error")
    readonly_fields = (
        "created_at",
        "updated_at",
        "started_at",
        "finished_at",
        "duration_ms",
        "response_tokens",
    )


@admin.register(RawPPI)
class RawPPIAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "run_id",
        "subject",
        "relation",
        "object",
        "confidence",
        "ungrounded",
        "created_at",
    )
    list_filter = ("relation", "ungrounded")
    search_fields = ("subject", "object", "evidence_span")
