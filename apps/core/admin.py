"""Django admin for core."""

from __future__ import annotations

from django.contrib import admin

from core.models import Identifier, OntologyEntity


class IdentifierInline(admin.TabularInline):
    model = Identifier
    extra = 0
    fields = ("scheme", "value", "is_primary")


@admin.register(OntologyEntity)
class OntologyEntityAdmin(admin.ModelAdmin):
    list_display = ("preferred_label", "entity_type", "created_at")
    list_filter = ("entity_type",)
    search_fields = ("preferred_label",)
    inlines = [IdentifierInline]


@admin.register(Identifier)
class IdentifierAdmin(admin.ModelAdmin):
    list_display = ("entity", "scheme", "value", "is_primary")
    list_filter = ("scheme", "is_primary")
    search_fields = ("value", "entity__preferred_label")
