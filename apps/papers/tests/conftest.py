"""Shared pytest fixtures for the papers app."""

from __future__ import annotations

from datetime import date

import pytest

from corpus.models import Paper


@pytest.fixture
def paper(db) -> Paper:
    return Paper.objects.create(
        pmid=38000123,
        title="A study of NP cells under hypoxia",
        publication_date=date(2024, 5, 1),
    )
