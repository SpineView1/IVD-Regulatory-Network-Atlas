"""verify Celery tasks — notification email dispatch + reviewer reminders.

``notify`` is the async email sender enqueued by
``verify.services._dispatch_notifications``. The in-app ``Notification`` rows
are created synchronously in ``services``; this task only renders + sends the
matching email (the queue hop keeps SMTP latency off the request path).

``dispatch_review_assignments`` is a Beat task (hourly, spec §6) that reminds
every curator about networks awaiting their review.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail

from celery import shared_task
from verify.emails import render_event_email
from verify.models import Notification, NotificationEvent, ReviewAssignment

log = logging.getLogger(__name__)
User = get_user_model()


@shared_task(name="verify.notify", queue="q.io")
def notify(
    *,
    notification_id: int | None = None,
    user_id: int | None = None,
    network_id: int | None = None,
    event_type: str | None = None,
    message: str | None = None,
) -> str:
    """Send the email for one notification.

    Two call shapes (see ``services._dispatch_notifications``):
    - ``notify(notification_id=<pk>)`` — an in-app Notification already exists;
      derive the recipient + content from it.
    - ``notify(user_id=, network_id=, event_type=, message=)`` — email-only
      subscriber with no Notification row.
    """
    from networks.models import Network  # noqa: PLC0415 — avoid app-load import cycle

    if notification_id is not None:
        notif = Notification.objects.select_related("user", "network").get(pk=notification_id)
        recipient = notif.user
        network = notif.network
        ev = notif.event_type
        msg = notif.message
    else:
        if user_id is None or network_id is None or event_type is None:
            raise ValueError("notify: supply notification_id, or user_id+network_id+event_type.")
        recipient = User.objects.get(pk=user_id)
        network = Network.objects.get(pk=network_id)
        ev = event_type
        msg = message or ""

    email = getattr(recipient, "email", "")
    if not email or network is None:
        return "skipped"

    subject, body = render_event_email(event_type=ev, network=network, message=msg, user=recipient)
    send_mail(
        subject=subject,
        message=body,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        recipient_list=[email],
        fail_silently=False,
    )
    return "sent"


@shared_task(name="verify.dispatch_review_assignments", queue="q.io")
def dispatch_review_assignments() -> int:
    """Hourly: remind every curator about networks awaiting their review.

    Targets networks in ``version_draft`` (ready to sign off) or ``stale``
    (disagreements to resolve). Skips ``idle``/``verified``/``refreshing``
    networks. Creates an in-app Notification per curator and enqueues its
    email. Returns the number of reminders fired.
    """
    from verify import services  # noqa: PLC0415 — avoid app-load import cycle

    pending = ReviewAssignment.objects.filter(
        role="curator",
        network__pipeline_status__in=["version_draft", "stale"],
    ).select_related("reviewer", "network")

    count = 0
    for ra in pending:
        network = ra.network
        if network.pipeline_status == "stale":
            event_type = NotificationEvent.NETWORK_DISAGREEMENTS
            message = (
                f"Reminder: {network.title} is stale and has disagreements "
                f"awaiting your review."
            )
        else:
            event_type = NotificationEvent.NEW_VERSION
            message = f"Reminder: {network.title} has a draft version awaiting your " f"sign-off."
        services.notify_user(
            user=ra.reviewer,
            network=network,
            event_type=event_type,
            message=message,
        )
        count += 1
    return count
