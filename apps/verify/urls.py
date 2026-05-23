"""verify URL routes — HTMX endpoints only.

The page-level views live in the dashboard app. This module only
exposes the POST-and-swap endpoints that HTMX clicks target.
"""
from __future__ import annotations

app_name = "verify"
urlpatterns: list = []
