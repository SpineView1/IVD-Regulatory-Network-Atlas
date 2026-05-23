"""Network pipeline_status transition rules (spec section 7).

Pure-function state machine. Inputs: current status + event name.
Output: new status, or InvalidTransition. No I/O, no side effects.
The services layer is responsible for persistence and notifications.
"""
from __future__ import annotations

from enum import Enum


class NetworkStatus(str, Enum):
    IDLE = "idle"
    REFRESHING = "refreshing"
    STALE = "stale"
    VERSION_DRAFT = "version_draft"
    VERIFIED = "verified"


class InvalidTransition(Exception):
    """Raised when an event is not legal for the current status."""


# Adjacency map: {current_status: {event: next_status}}
_TRANSITIONS: dict[NetworkStatus, dict[str, NetworkStatus]] = {
    NetworkStatus.IDLE: {
        "new_corpus": NetworkStatus.STALE,
    },
    NetworkStatus.STALE: {
        "integration_start": NetworkStatus.REFRESHING,
        "new_corpus": NetworkStatus.STALE,  # idempotent
    },
    NetworkStatus.REFRESHING: {
        "regenerate_done": NetworkStatus.VERSION_DRAFT,
        "integration_failed": NetworkStatus.STALE,
    },
    NetworkStatus.VERSION_DRAFT: {
        "signoff": NetworkStatus.VERIFIED,
        "new_corpus": NetworkStatus.STALE,
    },
    NetworkStatus.VERIFIED: {
        "new_corpus": NetworkStatus.STALE,
    },
}


def transition(current: NetworkStatus | str, event: str) -> NetworkStatus:
    """Return the next status for the given event, or raise InvalidTransition.

    Idempotent re-fires (e.g. new_corpus while already STALE) are allowed
    because the corpus-refresh task fires once per ingested paper.

    Accepts both NetworkStatus enum values and plain string values (as stored
    in Network.pipeline_status) so callers can pass network.pipeline_status
    directly.
    """
    if not isinstance(current, NetworkStatus):
        current = NetworkStatus(current)
    try:
        return _TRANSITIONS[current][event]
    except KeyError as exc:
        raise InvalidTransition(
            f"No transition from {current.value!r} on event {event!r}"
        ) from exc
