"""Shared pytest fixtures for the dashboard app."""

from __future__ import annotations

from datetime import date

import pytest
from django.test import Client

from corpus.models import Paper, PaperRelevance
from networks.models import Network


@pytest.fixture
def client():
    return Client(HTTP_REMOTE_USER="fchemorion")


@pytest.fixture
def seed(db):
    n = Network.objects.create(code="nfkb_axis", category="I", title="NF-κB Axis")
    Paper.objects.create(
        pmid=1,
        title="2024 paper A",
        journal="Spine",
        publication_date=date(2024, 1, 1),
        is_original=True,
        full_text_status="pmc_jats",
        mesh_terms=["Intervertebral Disc", "Hypoxia"],
        ingest_status="chunked",
    )
    Paper.objects.create(
        pmid=2,
        title="2024 paper B",
        journal="JOR",
        publication_date=date(2024, 6, 1),
        is_original=True,
        full_text_status="abstract_only",
        mesh_terms=["Intervertebral Disc"],
        ingest_status="chunked",
    )
    Paper.objects.create(
        pmid=3,
        title="2023 review",
        journal="Spine",
        publication_date=date(2023, 1, 1),
        is_original=False,
        full_text_status="none",
        ingest_status="classified",
    )
    PaperRelevance.objects.create(paper_id=1, network=n, score=0.9, classified_by="llm:qwen3:8b")
    return n
