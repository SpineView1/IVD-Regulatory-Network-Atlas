"""Tests for core.middleware.AutheliaRemoteUserMiddleware."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import RequestFactory, override_settings

from core.middleware import AutheliaRemoteUserMiddleware

User = get_user_model()


@pytest.fixture
def factory() -> RequestFactory:
    return RequestFactory()


@pytest.fixture
def middleware():
    return AutheliaRemoteUserMiddleware(lambda r: HttpResponse("ok"))


def test_middleware_creates_user_from_remote_user_header(db, factory, middleware):
    request = factory.get("/health/", HTTP_REMOTE_USER="fchemorion")
    request.session = {}
    middleware(request)
    assert User.objects.filter(username="fchemorion").exists()


def test_middleware_attaches_user_to_request(db, factory, middleware):
    request = factory.get("/health/", HTTP_REMOTE_USER="fchemorion")
    request.session = {}
    middleware(request)
    assert request.user.username == "fchemorion"


def test_middleware_sets_email_from_remote_email_header(db, factory, middleware):
    request = factory.get(
        "/health/",
        HTTP_REMOTE_USER="fchemorion",
        HTTP_REMOTE_EMAIL="francis.chemorion@upf.edu",
    )
    request.session = {}
    middleware(request)
    request.user.refresh_from_db()
    assert request.user.email == "francis.chemorion@upf.edu"


def test_middleware_sets_full_name_from_remote_name_header(db, factory, middleware):
    request = factory.get(
        "/health/",
        HTTP_REMOTE_USER="fchemorion",
        HTTP_REMOTE_NAME="Francis Chemorion",
    )
    request.session = {}
    middleware(request)
    request.user.refresh_from_db()
    assert request.user.first_name == "Francis"
    assert request.user.last_name == "Chemorion"


def test_middleware_assigns_groups_from_remote_groups_header(db, factory, middleware):
    request = factory.get(
        "/health/",
        HTTP_REMOTE_USER="fchemorion",
        HTTP_REMOTE_GROUPS="simbiosys-lab,curators",
    )
    request.session = {}
    middleware(request)
    request.user.refresh_from_db()
    group_names = set(request.user.groups.values_list("name", flat=True))
    assert group_names == {"simbiosys-lab", "curators"}


def test_middleware_idempotent_on_repeated_requests(db, factory, middleware):
    request = factory.get("/health/", HTTP_REMOTE_USER="fchemorion")
    request.session = {}
    middleware(request)
    middleware(request)
    assert User.objects.filter(username="fchemorion").count() == 1


@override_settings(AUTHELIA_DEV_FAKE_USER="fchemorion")
def test_middleware_uses_dev_fallback_when_no_header(db, factory, middleware):
    request = factory.get("/health/")  # no Remote-User header
    request.session = {}
    middleware(request)
    assert request.user.username == "fchemorion"


@override_settings(AUTHELIA_DEV_FAKE_USER=None)
def test_middleware_anonymous_when_no_header_and_no_fallback(db, factory, middleware):
    request = factory.get("/health/")
    request.session = {}
    middleware(request)
    assert request.user.is_anonymous
