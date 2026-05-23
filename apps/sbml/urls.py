"""sbml URL routes."""

from __future__ import annotations

from django.urls import path

from sbml import views

app_name = "sbml"
urlpatterns = [
    path(
        "networks/<slug:code>/v/<str:semver>/download",
        views.download_artifact,
        name="download",
    ),
]
