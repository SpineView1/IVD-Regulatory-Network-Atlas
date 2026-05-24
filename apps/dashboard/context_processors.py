"""Dashboard context processors.

Adds ``unread_notifications_count`` to every template context so the
notification badge in the nav bar is always up to date.
"""

from __future__ import annotations

from django.http import HttpRequest


def unread_notifications_count(request: HttpRequest) -> dict[str, int]:
    """Return ``{"unread_notifications_count": N}`` for the current user.

    Returns 0 for anonymous users without hitting the database.
    """
    if not request.user.is_authenticated:
        return {"unread_notifications_count": 0}

    from verify.models import Notification  # noqa: PLC0415 — avoid import cycle at module level

    count = Notification.objects.filter(
        user=request.user,
        read_at__isnull=True,
    ).count()
    return {"unread_notifications_count": count}
