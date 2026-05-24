"""Tests for schedule.tasks.assert_beat_alive.

Verifies:
  - The task creates a Watermark row with the correct source key on first run.
  - Subsequent calls bump updated_at (heartbeat is fresh).
  - The healthcheck's beat_scheduler_stale probe fires when the row is missing
    and when the row is older than BEAT_HEARTBEAT_STALE_MINUTES.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from monitoring.models import HealthAlert
from monitoring.tasks import BEAT_HEARTBEAT_STALE_MINUTES, healthcheck
from schedule.tasks import BEAT_HEARTBEAT_SOURCE, assert_beat_alive


@pytest.mark.django_db
class TestAssertBeatAliveTask:
    def test_creates_watermark_row_on_first_run(self, db):
        from schedule.models import Watermark

        assert not Watermark.objects.filter(source=BEAT_HEARTBEAT_SOURCE).exists()
        result = assert_beat_alive()
        assert result["created"] is True
        assert Watermark.objects.filter(source=BEAT_HEARTBEAT_SOURCE).exists()

    def test_second_call_updates_not_creates(self, db):
        from schedule.models import Watermark

        assert_beat_alive()
        assert_beat_alive()
        assert Watermark.objects.filter(source=BEAT_HEARTBEAT_SOURCE).count() == 1

    def test_repeated_call_bumps_updated_at(self, db):
        from schedule.models import Watermark

        assert_beat_alive()
        wm = Watermark.objects.get(source=BEAT_HEARTBEAT_SOURCE)
        # Force updated_at to a stale value.
        Watermark.objects.filter(pk=wm.pk).update(updated_at=timezone.now() - timedelta(minutes=10))
        wm.refresh_from_db()
        old_updated_at = wm.updated_at

        assert_beat_alive()
        wm.refresh_from_db()
        assert wm.updated_at > old_updated_at


@pytest.mark.django_db
class TestHealthcheckBeatLivenessProbe:
    @patch("monitoring.tasks._probe_ollama", return_value=True)
    @patch("monitoring.tasks._probe_postgres_latency", return_value=10.0)
    def test_missing_heartbeat_row_emits_critical_alert(self, _pg, _oll, db):
        # Ensure there is a recent pubmed watermark so that probe is green.
        from schedule.models import Watermark

        Watermark.objects.update_or_create(source="pubmed", defaults={})
        Watermark.objects.filter(source="pubmed").update(
            updated_at=timezone.now() - timedelta(minutes=30)
        )
        # No beat heartbeat row.
        result = healthcheck()
        assert result["beat_scheduler_stale"] is True
        alerts = HealthAlert.objects.filter(check_name="beat_scheduler_stale")
        assert alerts.count() == 1
        assert alerts.get().severity == "critical"

    @patch("monitoring.tasks._probe_ollama", return_value=True)
    @patch("monitoring.tasks._probe_postgres_latency", return_value=10.0)
    def test_stale_heartbeat_emits_critical_alert(self, _pg, _oll, db):
        from schedule.models import Watermark

        Watermark.objects.update_or_create(source="pubmed", defaults={})
        Watermark.objects.filter(source="pubmed").update(
            updated_at=timezone.now() - timedelta(minutes=30)
        )
        # Create a stale beat heartbeat row.
        wm, _ = Watermark.objects.get_or_create(source=BEAT_HEARTBEAT_SOURCE)
        Watermark.objects.filter(pk=wm.pk).update(
            updated_at=timezone.now() - timedelta(minutes=BEAT_HEARTBEAT_STALE_MINUTES + 1)
        )

        result = healthcheck()
        assert result["beat_scheduler_stale"] is True
        alerts = HealthAlert.objects.filter(check_name="beat_scheduler_stale")
        assert alerts.count() == 1

    @patch("monitoring.tasks._probe_ollama", return_value=True)
    @patch("monitoring.tasks._probe_postgres_latency", return_value=10.0)
    def test_fresh_heartbeat_emits_no_alert(self, _pg, _oll, db):
        from schedule.models import Watermark

        Watermark.objects.update_or_create(source="pubmed", defaults={})
        Watermark.objects.filter(source="pubmed").update(
            updated_at=timezone.now() - timedelta(minutes=30)
        )
        # Create a fresh beat heartbeat row.
        wm, _ = Watermark.objects.get_or_create(source=BEAT_HEARTBEAT_SOURCE)
        Watermark.objects.filter(pk=wm.pk).update(updated_at=timezone.now() - timedelta(minutes=1))

        result = healthcheck()
        assert result["beat_scheduler_stale"] is False
        assert not HealthAlert.objects.filter(check_name="beat_scheduler_stale").exists()
