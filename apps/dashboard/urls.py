"""dashboard URL routes."""

from __future__ import annotations

from django.urls import path

from dashboard import views

app_name = "dashboard"

urlpatterns = [
    path("corpus/stats", views.stats, name="stats"),
    path("corpus/paper/<int:pmid>", views.paper_detail, name="paper_detail"),
]
