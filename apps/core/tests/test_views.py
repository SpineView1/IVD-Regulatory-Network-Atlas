"""Tests for core.views."""

from __future__ import annotations

import pytest
from django.test import Client


@pytest.fixture
def client_with_remote_user() -> Client:
    return Client(HTTP_REMOTE_USER="fchemorion")


def test_health_endpoint_returns_200(db, client_with_remote_user):
    response = client_with_remote_user.get("/health/")
    assert response.status_code == 200


def test_health_endpoint_includes_user(db, client_with_remote_user):
    response = client_with_remote_user.get("/health/")
    payload = response.json()
    assert payload["user"] == "fchemorion"


def test_health_endpoint_reports_db_ok(db, client_with_remote_user):
    response = client_with_remote_user.get("/health/")
    payload = response.json()
    assert payload["database"] == "ok"


def test_health_endpoint_returns_json(db, client_with_remote_user):
    response = client_with_remote_user.get("/health/")
    assert response["Content-Type"].startswith("application/json")


def test_health_endpoint_works_without_remote_user_in_dev(db):
    # In dev, AUTHELIA_DEV_FAKE_USER kicks in
    client = Client()
    response = client.get("/health/")
    assert response.status_code == 200
    assert response.json()["user"] == "fchemorion"
