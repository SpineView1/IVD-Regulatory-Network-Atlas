"""monitoring URL routes."""

from __future__ import annotations

from django.urls import path

from monitoring import views

app_name = "monitoring"
urlpatterns = [
    path("pause/", views.pause, name="pause"),
    path("resume/", views.resume, name="resume"),
]
