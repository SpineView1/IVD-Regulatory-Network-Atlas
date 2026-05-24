"""Tests for schedule.metrics — Prometheus custom collectors."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.test import Client
from django.utils import timezone


@pytest.fixture
def client():
    return Client()


@pytest.mark.django_db
def test_metrics_endpoint_returns_200(client):
    response = client.get("/metrics")
    assert response.status_code == 200


@pytest.mark.django_db
def test_metrics_endpoint_content_type_is_prometheus(client):
    response = client.get("/metrics")
    assert "text/plain" in response["Content-Type"]


@pytest.mark.django_db
def test_metrics_exposes_django_http_default_metric(client):
    client.get("/health/")  # produces a request the middleware will count
    response = client.get("/metrics")
    assert b"django_http_requests_total_by_method_total" in response.content


@pytest.mark.django_db
def test_metrics_exposes_celery_queue_depth(client):
    from schedule.metrics import CeleryQueueDepthCollector

    with patch.object(CeleryQueueDepthCollector, "_redis_llen", return_value=42):
        response = client.get("/metrics")
    assert b"interactome_celery_queue_depth" in response.content
    assert b"42" in response.content


@pytest.mark.django_db
def test_metrics_exposes_healthcheck_age(client):
    from schedule.models import HealthcheckState

    state = HealthcheckState.objects.get(id=1)
    state.last_run_at = timezone.now() - timedelta(seconds=37)
    state.save()

    response = client.get("/metrics")
    assert b"interactome_healthcheck_last_run_seconds_ago" in response.content
    # Tolerant assertion — body contains a number between 36 and 40
    body = response.content.decode()
    for line in body.splitlines():
        if line.startswith("interactome_healthcheck_last_run_seconds_ago "):
            value = float(line.split()[-1])
            assert 35 < value < 45
            break
    else:
        pytest.fail("healthcheck_last_run_seconds_ago metric not emitted")
