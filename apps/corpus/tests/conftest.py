"""Shared pytest fixtures for the corpus app."""

from __future__ import annotations

from datetime import date

import pytest

from corpus.models import Paper
from networks.models import Network


@pytest.fixture
def paper_minimal(db) -> Paper:
    return Paper.objects.create(
        pmid=38000123,
        title="A study of nucleus pulposus cells under hypoxia",
        abstract="Abstract goes here.",
        journal="Spine",
        publication_date=date(2024, 5, 1),
        entrez_date=date(2024, 5, 2),
        publication_types=["Journal Article"],
        mesh_terms=["Intervertebral Disc"],
        authors=[{"last": "Doe", "first": "Jane"}],
    )


@pytest.fixture
def nfkb_network(db) -> Network:
    return Network.objects.create(
        code="nfkb_axis",
        category="I",
        title="NF-κB Axis",
        keywords=["NF-kB", "RELA"],
        root_entity_aliases=["NFKB1", "RELA"],
    )
