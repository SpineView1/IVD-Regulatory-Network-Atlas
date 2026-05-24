"""Django admin registration for verify models."""

from __future__ import annotations

from django.contrib import admin

from verify.models import (
    Notification,
    Review,
    ReviewAssignment,
    Signoff,
    Subscription,
)


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ("reviewer", "edge", "conflict", "decision", "created_at")
    list_filter = ("decision",)
    search_fields = ("reviewer__username", "comment")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Signoff)
class SignoffAdmin(admin.ModelAdmin):
    list_display = ("network", "model_version", "signed_by", "created_at")
    list_filter = ("network__category",)


@admin.register(ReviewAssignment)
class ReviewAssignmentAdmin(admin.ModelAdmin):
    list_display = ("reviewer", "network", "role")
    list_filter = ("role",)


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("user", "network", "category", "email_enabled", "inapp_enabled")


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("user", "event_type", "network", "read_at", "created_at")
    list_filter = ("event_type",)
