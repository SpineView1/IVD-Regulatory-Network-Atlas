"""Tests for the paper_ingested signal wiring."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from corpus.signals import paper_ingested


@pytest.mark.django_db
def test_signal_handler_enqueues_detect_affected_networks():
    with patch("graph.tasks.detect_affected_networks.delay") as mock_delay:
        paper_ingested.send(
            sender=None,
            paper_id=42,
            pmid="99999999",
            relevance_scores={1: 0.8, 2: 0.3},
        )
        mock_delay.assert_called_once_with(42)
