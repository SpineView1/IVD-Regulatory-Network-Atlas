"""Tests for corpus.tasks.triage_relevance_cheap and _llm."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from corpus.models import Paper, PaperRelevance
from corpus.tasks import (
    triage_pending,
    triage_relevance_cheap,
    triage_relevance_llm,
)
from networks.models import Network


@pytest.fixture(autouse=True)
def _eager(settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True


@pytest.fixture
def nfkb(db):
    return Network.objects.create(
        code="nfkb_axis",
        category="I",
        title="NF-κB Axis",
        keywords=["NF-kB", "RELA", "p65"],
        root_entity_aliases=["NFKB1", "RELA"],
    )


@pytest.fixture
def mech(db):
    return Network.objects.create(
        code="mechano_piezo",
        category="VIII",
        title="Piezo channels",
        keywords=["Piezo1", "Piezo2", "mechanosensitive"],
        root_entity_aliases=["PIEZO1", "PIEZO2"],
    )


def test_cheap_pass_matches_keyword_in_abstract(db, nfkb):
    p = Paper.objects.create(
        pmid=1,
        title="x",
        abstract="NF-kB upregulated in NP cells.",
        ingest_status="chunked",
        is_original=True,
    )
    with patch("corpus.tasks.triage_relevance_llm.delay"):
        triage_relevance_cheap.delay(1).get(timeout=2)
    rel = PaperRelevance.objects.filter(paper=p, network=nfkb).first()
    assert rel is not None
    assert rel.classified_by == "cheap_keyword"
    assert rel.score >= 0.5


def test_cheap_pass_matches_pubtator_root_alias(db, nfkb):
    p = Paper.objects.create(
        pmid=2,
        title="x",
        abstract="no mention",
        pubtator_entities=[{"text": "RELA", "type": "Gene"}],
        ingest_status="chunked",
        is_original=True,
    )
    with patch("corpus.tasks.triage_relevance_llm.delay"):
        triage_relevance_cheap.delay(2).get(timeout=2)
    rel = PaperRelevance.objects.filter(paper=p, network=nfkb).first()
    assert rel is not None
    assert rel.classified_by == "cheap_pubtator"


def test_cheap_pass_no_match_skips_llm(db, nfkb, mech):
    Paper.objects.create(
        pmid=3,
        title="x",
        abstract="some unrelated topic",
        pubtator_entities=[],
        ingest_status="chunked",
        is_original=True,
    )
    with patch("corpus.tasks.triage_relevance_llm.delay") as mock_llm:
        triage_relevance_cheap.delay(3).get(timeout=2)
    mock_llm.assert_not_called()
    assert PaperRelevance.objects.filter(paper__pmid=3).count() == 0


def test_cheap_pass_enqueues_llm_for_borderline(db, nfkb):
    # When the cheap pass matches a keyword AND we want a second check,
    # the LLM pass refines. (Implementation: any cheap match enqueues LLM
    # to refine to a confidence score.)
    Paper.objects.create(
        pmid=4,
        title="x",
        abstract="NF-kB and RELA are upregulated.",
        ingest_status="chunked",
        is_original=True,
    )
    with patch("corpus.tasks.triage_relevance_llm.delay") as mock_llm:
        triage_relevance_cheap.delay(4).get(timeout=2)
    enqueued = {(c.args[0], c.args[1]) for c in mock_llm.call_args_list}
    assert (4, nfkb.pk) in enqueued


def test_cheap_pass_iterates_all_active_networks(db, nfkb, mech):
    Paper.objects.create(
        pmid=5,
        title="x",
        abstract="Piezo1 channels respond to compression in NP cells.",
        pubtator_entities=[{"text": "PIEZO1", "type": "Gene"}],
        ingest_status="chunked",
        is_original=True,
    )
    with patch("corpus.tasks.triage_relevance_llm.delay"):
        triage_relevance_cheap.delay(5).get(timeout=2)
    matched_codes = {r.network.code for r in PaperRelevance.objects.filter(paper__pmid=5)}
    assert "mechano_piezo" in matched_codes
    assert "nfkb_axis" not in matched_codes  # no NF-kB keyword


def test_llm_pass_updates_relevance_score(db, nfkb):
    p = Paper.objects.create(
        pmid=6,
        title="x",
        abstract="NF-kB and RELA are upregulated.",
        ingest_status="chunked",
        is_original=True,
    )
    PaperRelevance.objects.create(paper=p, network=nfkb, score=0.5, classified_by="cheap_keyword")
    fake_resp = {
        "response": json.dumps(
            {"relevant": True, "confidence": 0.92, "reason": "primary IL-1 study"}
        )
    }
    with patch("corpus.tasks.OllamaClient") as M:
        M.return_value.generate.return_value = fake_resp
        triage_relevance_llm.delay(6, nfkb.pk).get(timeout=2)
    rel = PaperRelevance.objects.get(paper=p, network=nfkb)
    assert rel.classified_by == "llm:qwen3:8b"
    assert rel.score == pytest.approx(0.92, abs=0.01)


def test_llm_pass_irrelevant_downgrades_score(db, nfkb):
    p = Paper.objects.create(
        pmid=7,
        title="x",
        abstract="NF-kB mention in a different tissue.",
        ingest_status="chunked",
        is_original=True,
    )
    PaperRelevance.objects.create(paper=p, network=nfkb, score=0.5, classified_by="cheap_keyword")
    fake_resp = {
        "response": json.dumps(
            {
                "relevant": False,
                "confidence": 0.85,
                "reason": "pancreatic cells, off-tissue",
            }
        )
    }
    with patch("corpus.tasks.OllamaClient") as M:
        M.return_value.generate.return_value = fake_resp
        triage_relevance_llm.delay(7, nfkb.pk).get(timeout=2)
    rel = PaperRelevance.objects.get(paper=p, network=nfkb)
    assert rel.score < 0.5


def test_triage_pending_enqueues_chunked_papers(db, nfkb):
    Paper.objects.create(pmid=8, title="x", ingest_status="chunked", is_original=True)
    Paper.objects.create(pmid=9, title="y", ingest_status="fetched", is_original=True)
    with patch("corpus.tasks.triage_relevance_cheap.delay") as mock_enq:
        triage_pending.delay().get(timeout=2)
    enqueued = {c.args[0] for c in mock_enq.call_args_list}
    assert 8 in enqueued
    assert 9 not in enqueued
