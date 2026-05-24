"""dashboard URL routes."""

from __future__ import annotations

from django.urls import path

from dashboard import views

app_name = "dashboard"

urlpatterns = [
    path("", views.grid, name="grid"),
    path("corpus/stats", views.stats, name="stats"),
    path("corpus/paper/<int:pmid>", views.paper_detail, name="paper_detail"),
    path("networks/<slug:code>/", views.network_detail, name="network_detail"),
    path(
        "networks/<slug:code>/queue/",
        views.disagreement_queue,
        name="disagreement_queue",
    ),
    path(
        "networks/edges/<int:pk>/audit/",
        views.audit_trail,
        name="audit_trail",
    ),
    path(
        "subscriptions/",
        views.subscriptions,
        name="subscriptions",
    ),
]
