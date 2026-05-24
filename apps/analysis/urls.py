"""analysis URL conf."""

from __future__ import annotations

from django.urls import path

from analysis import views

app_name = "analysis"

urlpatterns = [
    path("", views.explorer, name="explorer"),
    path("neighborhood.json", views.neighborhood_json, name="neighborhood_json"),
    path("crosstalk.json", views.crosstalk_json, name="crosstalk_json"),
    path("paths.json", views.paths_json, name="paths_json"),
    path("panel/", views.analysis_panel, name="analysis_panel"),
]
