"""Tests for the dashboard health-alerts HTMX panel (Task 11).

Verifies:
- GET /dashboard/health-alerts/ renders without errors
- Open alerts appear in the response
- Resolved alerts are excluded
- The pause panel template is included in base.html
"""

from __future__ import annotations

import pytest
from django.test import Client

from monitoring.models import HealthAlert


@pytest.mark.django_db
class TestHealthAlertsPanel:
    def test_empty_state_shows_all_clear_message(self):
        c = Client(HTTP_REMOTE_USER="curator")
        r = c.get("/dashboard/health-alerts/")
        assert r.status_code == 200
        assert "All systems normal" in r.content.decode()

    def test_lists_recent_open_alerts(self):
        HealthAlert.objects.create(
            check_name="ollama_unreachable",
            severity="critical",
            message="Connection refused",
        )
        c = Client(HTTP_REMOTE_USER="curator")
        r = c.get("/dashboard/health-alerts/")
        body = r.content.decode()
        assert r.status_code == 200
        assert "ollama_unreachable" in body
        assert "Connection refused" in body

    def test_excludes_resolved_alerts(self):
        a = HealthAlert.objects.create(check_name="resolved_x", severity="info", message="m")
        a.resolve(by="ops")
        c = Client(HTTP_REMOTE_USER="curator")
        r = c.get("/dashboard/health-alerts/")
        body = r.content.decode()
        assert "resolved_x" not in body

    def test_shows_multiple_open_alerts(self):
        HealthAlert.objects.create(
            check_name="pubmed_refresh_stale", severity="error", message="No refresh"
        )
        HealthAlert.objects.create(
            check_name="postgres_slow", severity="warning", message="Latency 500ms"
        )
        c = Client(HTTP_REMOTE_USER="curator")
        r = c.get("/dashboard/health-alerts/")
        body = r.content.decode()
        assert "pubmed_refresh_stale" in body
        assert "postgres_slow" in body


@pytest.mark.django_db
def test_base_html_includes_pause_panel():
    """dashboard/base.html must include the monitoring/pause_panel.html fragment."""
    c = Client(HTTP_REMOTE_USER="curator")
    # Grid view uses base.html — check for pause panel structural markers
    r = c.get("/")
    assert r.status_code == 200
    body = r.content.decode()
    # The pause panel template contains 'monitoring-pause-panel' id
    assert "monitoring-pause-panel" in body


@pytest.mark.django_db
def test_base_html_includes_health_alerts_widget():
    """dashboard/base.html must include the health-alerts HTMX widget."""
    c = Client(HTTP_REMOTE_USER="curator")
    r = c.get("/")
    assert r.status_code == 200
    body = r.content.decode()
    # The health-alerts div is loaded via HTMX — at minimum the hx-get URL is present
    assert "health-alerts" in body
