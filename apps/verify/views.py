"""verify HTMX endpoints — POST handlers returning fragment HTML."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

if TYPE_CHECKING:
    from django.contrib.auth.models import User as _User

from graph.models import Conflict
from verify.models import ReviewDecision
from verify.services import record_review


@require_POST
@login_required
def resolve_conflict(request: HttpRequest, pk: int) -> HttpResponse:
    """HTMX endpoint: POST to resolve a Conflict.

    Accepted POST parameters:
    - ``decision`` (required): one of ReviewDecision.values
    - ``comment`` (optional): free-text rationale

    On success: marks the conflict as ``human_resolved``, creates an
    append-only Review row via ``record_review``, and returns the updated
    ``conflict_card.html`` partial fragment for HTMX swap.

    Returns 400 if decision is missing or invalid.
    """
    conflict = get_object_or_404(Conflict, pk=pk)

    decision = request.POST.get("decision", "").strip()
    comment = request.POST.get("comment", "").strip()

    if decision not in ReviewDecision.values:
        return HttpResponse(
            f"Invalid decision {decision!r}. Valid choices: {ReviewDecision.values}",
            status=400,
            content_type="text/plain",
        )

    user = cast("_User", request.user)

    # Record the review (append-only)
    record_review(
        reviewer=user,
        conflict=conflict,
        decision=decision,
        comment=comment,
    )

    # Mark conflict as human_resolved
    Conflict.objects.filter(pk=conflict.pk).update(resolution_status="human_resolved")
    conflict.resolution_status = "human_resolved"

    return render(
        request,
        "verify/partials/conflict_card.html",
        {"conflict": conflict},
    )
