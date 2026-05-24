"""verify URL routes — HTMX endpoints only.

The page-level views live in the dashboard app. This module only
exposes the POST-and-swap endpoints that HTMX clicks target.
"""

from __future__ import annotations

from django.urls import path

from verify import views

app_name = "verify"
urlpatterns = [
    path(
        "conflicts/<int:pk>/resolve/",
        views.resolve_conflict,
        name="resolve_conflict",
    ),
    path(
        "subscriptions/<int:pk>/toggle/",
        views.subscription_toggle,
        name="subscription_toggle",
    ),
    path(
        "subscriptions/<int:pk>/delete/",
        views.subscription_delete,
        name="subscription_delete",
    ),
    path(
        "edges/<int:pk>/review/",
        views.review_edge,
        name="review_edge",
    ),
]
