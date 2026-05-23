"""Core views."""
from __future__ import annotations

from django.db import connection
from django.http import HttpRequest, JsonResponse


def health(request: HttpRequest) -> JsonResponse:
    """Liveness + identity + DB reachability check.

    Always returns 200. ``database`` will be ``"error"`` if the DB
    cursor open fails, but the response still returns 200 so external
    probes don't restart the container — the failure is in the body
    for the operator to read.
    """
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        db_status = "ok"
    except Exception as exc:
        db_status = f"error: {exc}"

    return JsonResponse(
        {
            "user": getattr(request.user, "username", None)
            if request.user.is_authenticated
            else None,
            "database": db_status,
        }
    )
