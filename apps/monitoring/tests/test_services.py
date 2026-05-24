"""Tests for monitoring.services."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from monitoring import services
from monitoring.models import FeatureFlag


@pytest.mark.django_db
class TestIngestionPauseFlag:
    def test_unset_flag_returns_false(self):
        assert services.is_ingestion_paused() is False

    def test_set_and_read_paused(self):
        services.set_ingestion_paused(True, by="fchemorion", reason="testing")
        assert services.is_ingestion_paused() is True

    def test_set_paused_persists_audit_info(self):
        services.set_ingestion_paused(True, by="fchemorion", reason="cluster maintenance")
        flag = FeatureFlag.objects.get(name="INGESTION_PAUSED")
        assert flag.last_changed_by == "fchemorion"
        assert flag.last_changed_reason == "cluster maintenance"

    def test_toggle_back_to_false(self):
        services.set_ingestion_paused(True, by="x", reason="y")
        services.set_ingestion_paused(False, by="x", reason="resumed")
        assert services.is_ingestion_paused() is False


@pytest.mark.django_db
class TestQueueDepth:
    @patch("monitoring.services._extract_queue_depth")
    def test_queue_depth_returns_int(self, mock_depth):
        mock_depth.return_value = 1234
        assert services.extract_queue_depth() == 1234

    @patch("monitoring.services._extract_queue_depth")
    def test_backpressure_at_threshold(self, mock_depth):
        mock_depth.return_value = 10_000
        assert services.is_backpressured(threshold=10_000) is True

    @patch("monitoring.services._extract_queue_depth")
    def test_below_threshold_no_backpressure(self, mock_depth):
        mock_depth.return_value = 9_999
        assert services.is_backpressured(threshold=10_000) is False
