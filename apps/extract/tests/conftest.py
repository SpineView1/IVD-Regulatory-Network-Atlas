"""Shared pytest fixtures for the extract app."""
from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture
def sample_ppi_payload() -> dict[str, Any]:
    """A minimal valid PPI extraction response body."""
    return {
        "ppis": [
            {
                "subject": "IL1B",
                "object": "MMP13",
                "relation": "activates",
                "evidence_span": "IL-1β robustly induced MMP13 transcription",
                "evidence_offset_start": 12,
                "evidence_offset_end": 56,
                "cell_type": "nucleus pulposus",
                "stimulus": "IL-1β stimulation",
                "confidence": 0.86,
            }
        ]
    }
