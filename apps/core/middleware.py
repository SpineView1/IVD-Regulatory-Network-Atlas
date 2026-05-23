"""Authelia SSO middleware.

Reads the ``Remote-User``, ``Remote-Email``, ``Remote-Name``, and
``Remote-Groups`` headers set by Authelia after a successful upstream
auth at the Caddy reverse proxy. Creates or updates the corresponding
Django ``User`` and attaches it to ``request.user``.

In development, falls back to ``settings.AUTHELIA_DEV_FAKE_USER`` if
no header is present, so the app remains usable when run outside
docker-compose.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Group
from django.http import HttpRequest, HttpResponse

if TYPE_CHECKING:
    from django.contrib.auth.models import User

_User = get_user_model()


class AutheliaRemoteUserMiddleware:
    """Middleware factory in Django's new-style ``(get_response)`` form."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        username = request.META.get("HTTP_REMOTE_USER")
        if not username:
            username = getattr(settings, "AUTHELIA_DEV_FAKE_USER", None)

        if username:
            user = self._upsert_user(
                username=username,
                email=request.META.get("HTTP_REMOTE_EMAIL", ""),
                full_name=request.META.get("HTTP_REMOTE_NAME", ""),
                groups_csv=request.META.get("HTTP_REMOTE_GROUPS", ""),
            )
            request.user = user
        else:
            request.user = AnonymousUser()

        return self.get_response(request)

    @staticmethod
    def _upsert_user(
        *,
        username: str,
        email: str,
        full_name: str,
        groups_csv: str,
    ) -> User:
        user, _ = _User.objects.get_or_create(username=username)
        changed = False

        if email and user.email != email:
            user.email = email
            changed = True

        if full_name:
            first, _, last = full_name.partition(" ")
            if user.first_name != first:
                user.first_name = first
                changed = True
            if user.last_name != last:
                user.last_name = last
                changed = True

        if changed:
            user.save()

        if groups_csv:
            wanted = {g.strip() for g in groups_csv.split(",") if g.strip()}
            current = set(user.groups.values_list("name", flat=True))
            for name in wanted - current:
                group, _ = Group.objects.get_or_create(name=name)
                user.groups.add(group)
            for name in current - wanted:
                user.groups.remove(Group.objects.get(name=name))

        return user
