"""verify HTMX endpoints — POST handlers returning fragment HTML."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

if TYPE_CHECKING:
    from django.contrib.auth.models import User as _User

from graph.models import Conflict
from verify.models import ReviewDecision, Subscription
from verify.services import record_review, update_subscription


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


# ---------------------------------------------------------------------------
# Task 13: Subscription toggle + delete HTMX endpoints
# ---------------------------------------------------------------------------


@require_POST
@login_required
def subscription_toggle(request: HttpRequest, pk: int) -> HttpResponse:
    """HTMX endpoint: toggle email_enabled / inapp_enabled on a Subscription.

    POST parameters:
    - ``email_enabled``: "true" | "false"
    - ``inapp_enabled``: "true" | "false"

    Returns the updated subscription_row.html partial.
    Returns 403 if the user does not own this subscription.
    """
    user = cast("_User", request.user)

    try:
        sub = update_subscription(
            user=user,
            subscription_id=pk,
            email_enabled=request.POST.get("email_enabled", "true").lower() == "true",
            inapp_enabled=request.POST.get("inapp_enabled", "true").lower() == "true",
        )
    except PermissionDenied:
        return HttpResponse("Forbidden", status=403)

    return render(
        request,
        "verify/partials/subscription_row.html",
        {"sub": sub},
    )


@require_POST
@login_required
def subscription_delete(request: HttpRequest, pk: int) -> HttpResponse:
    """HTMX endpoint: unsubscribe (delete a Subscription row).

    Returns 200 with an empty fragment on success.
    Returns 403 if the user does not own this subscription.
    """
    user = cast("_User", request.user)
    sub = get_object_or_404(Subscription, pk=pk)
    if sub.user_id != user.pk:
        return HttpResponse("Forbidden", status=403)
    sub.delete()
    return HttpResponse("", status=200)
