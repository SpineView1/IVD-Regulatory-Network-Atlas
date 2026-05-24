"""verify HTMX endpoints — POST handlers returning fragment HTML."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

if TYPE_CHECKING:
    from django.contrib.auth.models import User as _User

from graph.models import Conflict
from verify.models import ReviewDecision, Subscription
from verify.services import record_review, update_subscription
from verify.services import sign_off as service_sign_off
from verify.state_machine import InvalidTransition


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


# ---------------------------------------------------------------------------
# Task 14: Per-edge review endpoint
# ---------------------------------------------------------------------------


@require_POST
@login_required
def sign_off_view(request: HttpRequest, network_code: str, semver: str) -> HttpResponse:
    """HTMX endpoint: POST to sign off a network version.

    URL parameters:
    - ``network_code``: the network slug
    - ``semver``: the ModelVersion semver string to sign off

    POST parameters:
    - ``notes`` (optional): curator notes

    On success: transitions network to verified, enqueues sbml regeneration,
    notifies subscribers, returns the updated signoff_button.html partial.

    Returns 400 if the transition is invalid (network not in version_draft).
    Returns 404 if the network or model_version does not exist.
    """
    from networks.models import Network
    from sbml.models import ModelVersion

    network = get_object_or_404(Network, code=network_code)
    model_version = get_object_or_404(ModelVersion, network=network, semver=semver)
    notes = request.POST.get("notes", "").strip()
    user = cast("_User", request.user)

    try:
        service_sign_off(
            network=network,
            model_version=model_version,
            signed_by=user,
            notes=notes,
        )
    except InvalidTransition as exc:
        return HttpResponseBadRequest(f"Invalid transition: {exc}")

    network.refresh_from_db()
    return render(
        request,
        "verify/partials/signoff_button.html",
        {"network": network, "model_version": model_version},
    )


@require_POST
@login_required
def review_edge(request: HttpRequest, pk: int) -> HttpResponse:
    """HTMX endpoint: POST to record a review decision on a single Edge.

    Accepted POST parameters:
    - ``decision`` (required): one of ReviewDecision.values
    - ``comment`` (optional): free-text rationale

    APPEND-ONLY: every POST creates a new Review row. The latest row per
    reviewer (ordered by created_at DESC) is the current decision.

    Returns the ``review_history.html`` partial showing the latest-per-reviewer
    view (using .order_by("reviewer_id", "-created_at").distinct("reviewer_id"),
    which requires PostgreSQL).

    Returns 400 if decision is missing or invalid.
    Returns 404 if the edge does not exist.
    """
    from graph.models import Edge

    edge = get_object_or_404(Edge, pk=pk)
    decision = request.POST.get("decision", "").strip()
    comment = request.POST.get("comment", "").strip()

    if decision not in ReviewDecision.values:
        return HttpResponse(
            f"Invalid decision {decision!r}. Valid choices: {ReviewDecision.values}",
            status=400,
            content_type="text/plain",
        )

    user = cast("_User", request.user)
    record_review(
        reviewer=user,
        edge=edge,
        decision=decision,
        comment=comment,
    )

    # Latest-per-reviewer: PostgreSQL DISTINCT ON ordered by reviewer_id, -created_at
    latest_reviews = list(
        edge.reviews.select_related("reviewer")
        .order_by("reviewer_id", "-created_at")
        .distinct("reviewer_id")
    )

    return render(
        request,
        "verify/partials/review_history.html",
        {"edge": edge, "reviews": latest_reviews},
    )
