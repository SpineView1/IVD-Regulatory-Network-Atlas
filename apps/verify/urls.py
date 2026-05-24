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
]
