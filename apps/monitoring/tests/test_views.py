"""Tests for monitoring.views — pause/resume admin endpoints."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client

from monitoring import services
from monitoring.models import FeatureFlag

User = get_user_model()


@pytest.fixture
def curator_client(db) -> Client:
    user, _ = User.objects.get_or_create(username="curator", defaults={"email": "c@x.com"})
    group, _ = Group.objects.get_or_create(name="curators")
    user.groups.add(group)
    return Client(HTTP_REMOTE_USER="curator", HTTP_REMOTE_GROUPS="curators")


@pytest.fixture
def non_curator_client(db) -> Client:
    User.objects.get_or_create(username="visitor")
    return Client(HTTP_REMOTE_USER="visitor")


def test_pause_endpoint_requires_curator_group(non_curator_client):
    r = non_curator_client.post("/admin/monitoring/pause/", data={"reason": "test"})
    assert r.status_code == 403


def test_pause_endpoint_sets_flag(curator_client):
    r = curator_client.post("/admin/monitoring/pause/", data={"reason": "cluster maintenance"})
    assert r.status_code == 200
    assert services.is_ingestion_paused() is True
    flag = FeatureFlag.objects.get(name="INGESTION_PAUSED")
    assert flag.last_changed_by == "curator"
    assert flag.last_changed_reason == "cluster maintenance"


def test_resume_endpoint_clears_flag(curator_client):
    services.set_ingestion_paused(True, by="curator", reason="setup")
    r = curator_client.post("/admin/monitoring/resume/", data={"reason": "all clear"})
    assert r.status_code == 200
    assert services.is_ingestion_paused() is False


def test_pause_endpoint_requires_post(curator_client):
    r = curator_client.get("/admin/monitoring/pause/")
    assert r.status_code == 405


def test_pause_endpoint_returns_htmx_partial(curator_client):
    r = curator_client.post("/admin/monitoring/pause/", data={"reason": "x"})
    assert "Ingestion paused" in r.content.decode()
