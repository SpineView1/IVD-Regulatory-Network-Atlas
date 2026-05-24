"""Tests for monitoring.tasks.healthcheck."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from monitoring.models import HealthAlert
from monitoring.tasks import healthcheck


@pytest.fixture
def watermark_recent(db):
    from schedule.models import Watermark

    wm, _ = Watermark.objects.get_or_create(source="pubmed")
    # Force updated_at to 30 minutes ago (well within 2h threshold).
    Watermark.objects.filter(pk=wm.pk).update(updated_at=timezone.now() - timedelta(minutes=30))


@pytest.fixture
def watermark_stale(db):
    from schedule.models import Watermark

    wm, _ = Watermark.objects.get_or_create(source="pubmed")
    # Force updated_at to 3 hours ago (beyond the 2h threshold).
    Watermark.objects.filter(pk=wm.pk).update(updated_at=timezone.now() - timedelta(hours=3))


@pytest.mark.django_db
class TestPubMedFreshnessCheck:
    @patch("monitoring.tasks._probe_ollama", return_value=True)
    @patch("monitoring.tasks._probe_postgres_latency", return_value=10.0)
    def test_recent_pubmed_emits_no_alert(self, _pg, _oll, watermark_recent):
        healthcheck()
        assert not HealthAlert.objects.filter(check_name="pubmed_refresh_stale").exists()

    @patch("monitoring.tasks._probe_ollama", return_value=True)
    @patch("monitoring.tasks._probe_postgres_latency", return_value=10.0)
    def test_stale_pubmed_emits_alert(self, _pg, _oll, watermark_stale):
        healthcheck()
        alerts = HealthAlert.objects.filter(check_name="pubmed_refresh_stale")
        assert alerts.count() == 1
        alert = alerts.get()
        assert alert.severity == "error"


@pytest.mark.django_db
class TestOllamaReachabilityCheck:
    @patch("monitoring.tasks._probe_ollama", return_value=False)
    @patch("monitoring.tasks._probe_postgres_latency", return_value=10.0)
    def test_ollama_unreachable_emits_critical_alert(self, _pg, _oll, watermark_recent):
        healthcheck()
        alerts = HealthAlert.objects.filter(check_name="ollama_unreachable")
        assert alerts.count() == 1
        alert = alerts.get()
        assert alert.severity == "critical"


@pytest.mark.django_db
class TestPostgresLatencyCheck:
    @patch("monitoring.tasks._probe_ollama", return_value=True)
    @patch("monitoring.tasks._probe_postgres_latency", return_value=350.0)
    def test_slow_postgres_emits_warning(self, _pg, _oll, watermark_recent):
        healthcheck()
        alerts = HealthAlert.objects.filter(check_name="postgres_slow")
        assert alerts.count() == 1
        alert = alerts.get()
        assert alert.severity == "warning"

    @patch("monitoring.tasks._probe_ollama", return_value=True)
    @patch("monitoring.tasks._probe_postgres_latency", return_value=50.0)
    def test_fast_postgres_emits_no_alert(self, _pg, _oll, watermark_recent):
        healthcheck()
        assert not HealthAlert.objects.filter(check_name="postgres_slow").exists()


@pytest.mark.django_db
class TestHealthcheckNotifiesAdmins:
    @patch("monitoring.tasks.notify_admins")
    @patch("monitoring.tasks._probe_ollama", return_value=False)
    @patch("monitoring.tasks._probe_postgres_latency", return_value=10.0)
    def test_critical_alert_triggers_admin_notification(
        self, _pg, _oll, mock_notify, watermark_recent
    ):
        healthcheck()
        assert mock_notify.called
        call_args = mock_notify.call_args[1]
        assert call_args["severity"] == "critical"
