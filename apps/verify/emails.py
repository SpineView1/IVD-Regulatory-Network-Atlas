"""Email rendering helpers.

Centralises the event-type -> (subject, body) template mapping so that
``verify.tasks.notify`` can call one function instead of repeating
``render_to_string``. Bodies are plain text (readable in any client; no
HTML headaches). Subjects/bodies render from templates under
``verify/templates/verify/emails/``.

Event types are the ``NotificationEvent`` values from ``verify.models``:
``network_stale``, ``network_disagreements``, ``network_signed_off``,
``new_version``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.template.loader import render_to_string

if TYPE_CHECKING:
    from networks.models import Network


_SUBJECT_TEMPLATES = {
    "network_stale": "verify/emails/stale_subject.txt",
    "network_disagreements": "verify/emails/disagreements_subject.txt",
    "network_signed_off": "verify/emails/signed_off_subject.txt",
    "new_version": "verify/emails/new_version_subject.txt",
}

_BODY_TEMPLATES = {
    "network_stale": "verify/emails/stale_body.txt",
    "network_disagreements": "verify/emails/disagreements_body.txt",
    "network_signed_off": "verify/emails/signed_off_body.txt",
    "new_version": "verify/emails/new_version_body.txt",
}


def render_event_email(
    *,
    event_type: str,
    network: Network,
    message: str,
    user: Any | None = None,
) -> tuple[str, str]:
    """Return ``(subject, body)`` for a notification *event_type*.

    Raises ``ValueError`` for an unknown event type so a typo surfaces
    loudly rather than sending a blank email.
    """
    if event_type not in _SUBJECT_TEMPLATES:
        raise ValueError(f"Unknown event_type: {event_type!r}")
    ctx = {"network": network, "message": message, "user": user}
    subject = render_to_string(_SUBJECT_TEMPLATES[event_type], ctx).strip()
    body = render_to_string(_BODY_TEMPLATES[event_type], ctx)
    return subject, body
