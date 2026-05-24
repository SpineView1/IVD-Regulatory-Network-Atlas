"""monitoring views — admin pause / resume HTMX endpoints."""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import render
from django.views.decorators.http import require_POST

from monitoring import services


def _is_curator(request: HttpRequest) -> bool:
    if not request.user.is_authenticated:
        return False
    return request.user.groups.filter(name="curators").exists()


@require_POST
def pause(request: HttpRequest) -> HttpResponse:
    if not _is_curator(request):
        return HttpResponseForbidden("curators-only")
    reason = request.POST.get("reason", "").strip() or "(no reason given)"
    services.set_ingestion_paused(True, by=request.user.username, reason=reason)
    return render(
        request,
        "monitoring/pause_panel.html",
        {"paused": True, "reason": reason},
    )


@require_POST
def resume(request: HttpRequest) -> HttpResponse:
    if not _is_curator(request):
        return HttpResponseForbidden("curators-only")
    reason = request.POST.get("reason", "").strip() or "(no reason given)"
    services.set_ingestion_paused(False, by=request.user.username, reason=reason)
    return render(
        request,
        "monitoring/pause_panel.html",
        {"paused": False, "reason": reason},
    )
