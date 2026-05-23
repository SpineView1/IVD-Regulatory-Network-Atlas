"""graph URL routes."""

from __future__ import annotations

from django.urls import URLPattern, path

from graph import views

app_name = "graph"
urlpatterns: list[URLPattern] = [
    path("dev/networks/<str:code>/", views.dev_network, name="dev-network"),
    path(
        "dev/networks/<str:code>/edges.json",
        views.dev_network_edges_json,
        name="dev-network-edges-json",
    ),
]
