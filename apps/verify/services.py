"""verify services — public API for other apps.

Key contracts (spec §7 + cross-plan reconciliation):
- record_review: APPEND-ONLY. Never updates an existing Review row.
  A changed decision is a NEW row. Latest row by created_at wins.
- sign_off: records Signoff → transitions network to verified via state
  machine → enqueues sbml.tasks.regenerate with triggered_by_curator=True
  for a curator MAJOR semver bump → notifies subscribers.
- notify_subscribers: compatible with Phase 4's callsite in sbml/services.py:
    notify_subscribers(network=network, model_version=mv)
  Creates in-app Notification rows for all subscribers and enqueues
  verify.tasks.notify to send email.
- subscribe: create-or-get a Subscription (idempotent).
- mark_stale: canonical transition+notification API that records a network
  move to stale and notifies subscribers.  Designed so Phase 3's graph
  callsites (reassign_network_membership) can wire in without breaking their
  own direct DB updates.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.contrib.auth.models import AbstractBaseUser
from django.core.exceptions import ValidationError
from django.db import transaction

from verify.models import (
    Notification,
    NotificationEvent,
    Review,
    ReviewDecision,
    Signoff,
    Subscription,
)
from verify.state_machine import NetworkStatus, transition

if TYPE_CHECKING:
    from graph.models import Conflict, Edge
    from networks.models import Network
    from sbml.models import ModelVersion

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# record_review
# ---------------------------------------------------------------------------


def record_review(
    *,
    reviewer: AbstractBaseUser,
    edge: Edge | None = None,
    conflict: Conflict | None = None,
    decision: str,
    comment: str = "",
) -> Review:
    """Append a new Review row for *reviewer* on *edge* or *conflict*.

    APPEND-ONLY: a changed decision creates a NEW row; existing rows are
    never updated.  The latest row (by created_at) for a given
    (reviewer, edge/conflict) tuple is the current decision.

    Raises ValidationError when neither edge nor conflict is supplied, or
    when decision is not in ReviewDecision.
    """
    if edge is None and conflict is None:
        raise ValidationError(
            "record_review: must supply edge or conflict."
        )
    if decision not in ReviewDecision.values:
        raise ValidationError(
            f"record_review: invalid decision {decision!r}. "
            f"Valid choices: {ReviewDecision.values}"
        )

    review = Review(
        reviewer=reviewer,  # type: ignore[misc]  # AbstractBaseUser API → concrete User FK
        edge=edge,
        conflict=conflict,
        decision=decision,
        comment=comment,
    )
    review.full_clean()
    review.save()
    return review


# ---------------------------------------------------------------------------
# subscribe
# ---------------------------------------------------------------------------


def subscribe(
    *,
    user: AbstractBaseUser,
    network: Network | None = None,
    category: str = "",
    email_enabled: bool = True,
    inapp_enabled: bool = True,
) -> Subscription:
    """Create or retrieve a Subscription.

    Idempotent: calling twice for the same (user, network) or (user, category)
    returns the existing row without raising.

    Raises ValidationError when neither network nor category is provided.
    """
    if network is None and not category:
        raise ValidationError(
            "subscribe: must supply network or category."
        )

    if network is not None:
        sub, _ = Subscription.objects.get_or_create(
            user=user,
            network=network,
            defaults={
                "email_enabled": email_enabled,
                "inapp_enabled": inapp_enabled,
            },
        )
    else:
        sub, _ = Subscription.objects.get_or_create(
            user=user,
            category=category,
            defaults={
                "email_enabled": email_enabled,
                "inapp_enabled": inapp_enabled,
            },
        )
    return sub


# ---------------------------------------------------------------------------
# notify_subscribers
# ---------------------------------------------------------------------------


def notify_subscribers(
    *,
    network: Network,
    model_version: ModelVersion,
) -> list[Notification]:
    """Notify all subscribers of *network* (or its category) that a new
    version is available.

    This function is the canonical Phase 4 callsite:
        from verify.services import notify_subscribers
        notify_subscribers(network=network, model_version=mv)

    For each subscriber with inapp_enabled=True, creates a Notification row.
    For subscribers with email_enabled=True, enqueues verify.tasks.notify.

    Returns the list of Notification rows created (useful for testing).
    """
    message = (
        f"Network {network.code!r} has a new version "
        f"v{model_version.semver} available."
    )
    return _dispatch_notifications(
        network=network,
        event_type=NotificationEvent.NEW_VERSION,
        message=message,
    )


# ---------------------------------------------------------------------------
# mark_stale
# ---------------------------------------------------------------------------


def mark_stale(
    *,
    network: Network,
    reason: str = "",
) -> None:
    """Canonical transition + notification API to move a network to stale.

    Applies the state machine transition (verified/idle → stale is also
    allowed via stale→stale idempotent). Persists to DB, then notifies all
    subscribers.

    Raises InvalidTransition only if the state machine does not allow it
    (e.g. refreshing → stale via new_corpus is not modelled; that path uses
    integration_failed instead). The state machine allows:
      idle → stale (new_corpus)
      stale → stale (idempotent new_corpus)
      verified → stale (new_corpus)
    All are reachable via the "new_corpus" event.

    Designed for future Batch C wiring at graph.services callsites WITHOUT
    breaking existing Phase 3 tests which already do the DB update directly.
    """
    from networks.models import (
        Network as NetworkModel,  # noqa: PLC0415 — avoid top-level import cycle
    )

    next_status = transition(network.pipeline_status, "new_corpus")
    NetworkModel.objects.filter(pk=network.pk).update(
        pipeline_status=next_status.value,
    )
    network.pipeline_status = next_status.value

    if next_status == NetworkStatus.STALE:
        msg = reason or f"Network {network.code!r} has new data and requires re-verification."
        _dispatch_notifications(
            network=network,
            event_type=NotificationEvent.NETWORK_STALE,
            message=msg,
        )


# ---------------------------------------------------------------------------
# sign_off
# ---------------------------------------------------------------------------


def sign_off(
    *,
    network: Network,
    model_version: ModelVersion,
    signed_by: AbstractBaseUser,
    notes: str = "",
) -> Signoff:
    """Record a curator sign-off, advance the network to *verified*, and
    enqueue a curator MAJOR semver regeneration.

    Steps (spec §7):
    1. Validate that network.pipeline_status == version_draft (via state machine).
    2. Create Signoff row.
    3. Transition network to verified in DB.
    4. Enqueue sbml.tasks.regenerate with triggered_by_curator=True (MAJOR bump).
    5. Notify subscribers with NETWORK_SIGNED_OFF.

    Raises InvalidTransition if the network is not in version_draft status.
    """
    from networks.models import Network as NetworkModel  # noqa: PLC0415
    from sbml.tasks import regenerate  # noqa: PLC0415

    with transaction.atomic():
        # 1. Validate transition (raises InvalidTransition if not version_draft)
        next_status = transition(network.pipeline_status, "signoff")

        # 2. Create Signoff
        so = Signoff.objects.create(
            network=network,
            model_version=model_version,
            signed_by=signed_by,  # type: ignore[misc]  # AbstractBaseUser API → concrete User FK
            notes=notes,
        )

        # 3. Transition network to verified
        NetworkModel.objects.filter(pk=network.pk).update(
            pipeline_status=next_status.value,
        )
        network.pipeline_status = next_status.value

    # 4. Enqueue curator MAJOR semver regeneration (outside atomic to avoid
    #    Celery task firing inside transaction before commit).
    try:
        regenerate.delay(network.pk, triggered_by_curator=True)
    except Exception:
        log.exception(
            "sign_off: failed to enqueue regenerate for network %s", network.code
        )

    # 5. Notify subscribers
    _dispatch_notifications(
        network=network,
        event_type=NotificationEvent.NETWORK_SIGNED_OFF,
        message=(
            f"Network {network.code!r} has been signed off as v{model_version.semver} "
            f"by {signed_by.get_username()}."
        ),
    )

    return so


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def notify_user(
    *,
    user: AbstractBaseUser,
    network: Network,
    event_type: str,
    message: str,
    email: bool = True,
) -> Notification:
    """Create one in-app Notification for *user* and (optionally) enqueue its
    email. Used by reviewer-reminder dispatch (curators are targeted by role,
    not by Subscription)."""
    from verify.tasks import notify as notify_task  # noqa: PLC0415 — avoid circular import

    notif = Notification.objects.create(
        user=user,  # type: ignore[misc]  # AbstractBaseUser API → concrete User FK
        network=network,
        event_type=event_type,
        message=message,
    )
    if email and getattr(user, "email", None):
        try:
            notify_task.delay(notification_id=notif.pk)
        except Exception:
            log.exception("verify.notify enqueue failed for user %s", user.pk)
    return notif


def _dispatch_notifications(
    *,
    network: Network,
    event_type: str,
    message: str,
) -> list[Notification]:
    """Create Notification rows + enqueue email tasks for all matching subscribers.

    Matches on:
    - Subscription.network == network  (direct)
    - Subscription.category == network.category  (category-wide)

    Only creates rows when inapp_enabled=True; only enqueues email tasks when
    email_enabled=True.
    """
    from verify.tasks import notify as notify_task  # noqa: PLC0415 — avoid circular import

    # Collect unique subscribers (direct + category-wide)
    subs = list(
        Subscription.objects.filter(network=network).select_related("user")
    )
    if network.category:
        cat_subs = list(
            Subscription.objects.filter(
                category=network.category
            ).select_related("user")
        )
        # Merge, dedup by user_id (prefer direct sub if both present)
        seen: set[int] = {s.user_id for s in subs}
        for cs in cat_subs:
            if cs.user_id not in seen:
                subs.append(cs)
                seen.add(cs.user_id)

    created: list[Notification] = []
    for sub in subs:
        if sub.inapp_enabled:
            notif = Notification.objects.create(
                user=sub.user,
                network=network,
                event_type=event_type,
                message=message,
            )
            created.append(notif)
            if sub.email_enabled:
                try:
                    notify_task.delay(notification_id=notif.pk)
                except Exception:
                    log.exception(
                        "verify.notify task enqueue failed for user %s",
                        sub.user_id,
                    )
        elif sub.email_enabled:
            # email-only subscriber — no Notification row but still send email
            try:
                notify_task.delay(
                    notification_id=None,
                    user_id=sub.user_id,
                    network_id=network.pk,
                    event_type=event_type,
                    message=message,
                )
            except Exception:
                log.exception(
                    "verify.notify task (email-only) enqueue failed for user %s",
                    sub.user_id,
                )

    return created
