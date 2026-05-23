"""corpus URL routes."""

from __future__ import annotations

from django.urls import path

from corpus import views

app_name = "corpus"

urlpatterns = [
    path("corpus/export.csv", views.export_csv, name="export_csv"),
]
