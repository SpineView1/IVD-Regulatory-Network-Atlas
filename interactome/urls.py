"""Top-level URL conf. Each app contributes via its own ``urls.py``."""

from __future__ import annotations

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("core.urls")),
    path("", include("corpus.urls")),
    path("", include("dashboard.urls")),
    path("graph/", include("graph.urls")),
    path("", include("sbml.urls")),
    path("verify/", include("verify.urls")),
    path("analysis/", include("analysis.urls")),
]
