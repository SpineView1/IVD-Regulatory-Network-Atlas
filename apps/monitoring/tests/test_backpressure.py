"""Tests verifying pause flag and backpressure short-circuit Beat tasks."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from monitoring import services


@pytest.mark.django_db
class TestRefreshPubmedHonoursPauseFlag:
    @patch("corpus.tasks._do_refresh_pubmed")
    def test_paused_short_circuits(self, mock_do):
        services.set_ingestion_paused(True, by="t", reason="t")
        from corpus.tasks import refresh_pubmed

        result = refresh_pubmed()

        assert mock_do.called is False
        assert result == {"skipped": True, "reason": "ingestion_paused"}

    @patch("corpus.tasks._do_refresh_pubmed", return_value={"n_pmids_seen": 0, "n_new": 0})
    def test_not_paused_runs_normally(self, mock_do):
        from corpus.tasks import refresh_pubmed

        result = refresh_pubmed()

        assert mock_do.called is True
        assert result == {"n_pmids_seen": 0, "n_new": 0}


@pytest.mark.django_db
class TestRefreshPubmedHonoursBackpressure:
    @patch("corpus.tasks._do_refresh_pubmed")
    @patch("monitoring.services._extract_queue_depth", return_value=10_001)
    def test_backpressured_short_circuits(self, _depth, mock_do):
        from corpus.tasks import refresh_pubmed

        result = refresh_pubmed()

        assert mock_do.called is False
        assert result == {"skipped": True, "reason": "backpressured"}


@pytest.mark.django_db
class TestEnqueuePendingChunksHonoursPauseFlag:
    @patch("extract.tasks._do_enqueue_pending_chunks")
    def test_paused_short_circuits(self, mock_do):
        services.set_ingestion_paused(True, by="t", reason="t")
        from extract.tasks import enqueue_pending_chunks

        result = enqueue_pending_chunks()

        assert mock_do.called is False
        assert result == {"skipped": True, "reason": "ingestion_paused"}

    @patch(
        "extract.tasks._do_enqueue_pending_chunks",
        return_value={"medgemma:27b": 0},
    )
    def test_not_paused_runs_normally(self, mock_do):
        from extract.tasks import enqueue_pending_chunks

        enqueue_pending_chunks()

        assert mock_do.called is True
