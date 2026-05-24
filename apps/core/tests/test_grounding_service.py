"""Tests for core.services.ground_mention.

The grounding service wraps Gilda for entity normalization. All tests use a
stub grounder so they never download Gilda's term resource at test time.

Injection mechanism: ``ground_mention`` accepts an optional ``grounder``
keyword argument (default: the real ``gilda`` module, accessed lazily).
Tests pass a ``MagicMock`` that mimics the Gilda API surface:
  mock_grounder.ground(text) -> list[ScoredMatch]
  match.term.db, match.term.id, match.term.entry_name, match.score
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.models import Identifier, OntologyEntity
from core.services import GROUND_SCORE_THRESHOLD, ground_mention


@pytest.fixture
def make_match():
    """Factory for a fake gilda ScoredMatch."""

    def _make(db: str, id_: str, name: str, score: float) -> MagicMock:
        m = MagicMock()
        m.term.db = db
        m.term.id = id_
        m.term.entry_name = name
        m.score = score
        return m

    return _make


@pytest.fixture
def stub_grounder(make_match):
    """A grounder stub that returns one high-confidence IL1B match by default."""
    g = MagicMock()
    g.ground.return_value = [make_match("HGNC", "5992", "IL1B", 0.95)]
    return g


def test_ground_mention_returns_entity_on_high_score(db, stub_grounder):
    entity = ground_mention("IL-1β", grounder=stub_grounder)
    assert entity is not None
    assert entity.preferred_label == "IL1B"
    assert entity.entity_type == "protein"
    assert entity.identifiers.filter(scheme="HGNC", value="5992").exists()


def test_ground_mention_returns_none_below_threshold(db, make_match):
    grounder = MagicMock()
    grounder.ground.return_value = [
        make_match("HGNC", "5992", "IL1B", GROUND_SCORE_THRESHOLD - 0.01),
    ]
    assert ground_mention("ambiguous-thing", grounder=grounder) is None


def test_ground_mention_returns_none_on_empty_match_list(db):
    grounder = MagicMock()
    grounder.ground.return_value = []
    assert ground_mention("unknownium", grounder=grounder) is None


def test_ground_mention_falls_back_to_alias(db, make_match):
    """A colloquial mention that fails raw grounding is recovered via its
    alias: 'Collagen II' grounds nowhere, but 'COL2A1' does."""
    col2a1 = make_match("HGNC", "2200", "COL2A1", 0.97)

    def fake_ground(text):
        return [col2a1] if text == "COL2A1" else []

    grounder = MagicMock()
    grounder.ground.side_effect = fake_ground

    entity = ground_mention("Collagen II", grounder=grounder)
    assert entity is not None
    assert entity.preferred_label == "COL2A1"
    # Raw text was tried first, then the alias.
    assert grounder.ground.call_args_list[0].args[0] == "Collagen II"
    assert "COL2A1" in [c.args[0] for c in grounder.ground.call_args_list]


def test_ground_mention_prefers_raw_match_over_alias(db, make_match):
    """When the raw mention grounds, the alias path is never consulted."""
    grounder = MagicMock()
    grounder.ground.return_value = [make_match("HGNC", "2200", "COL2A1", 0.95)]
    entity = ground_mention("Collagen II", grounder=grounder)
    assert entity is not None
    # Only one grounding call — the raw one — since it succeeded.
    assert grounder.ground.call_count == 1
    assert grounder.ground.call_args_list[0].args[0] == "Collagen II"


def test_ground_mention_none_when_neither_raw_nor_alias_grounds(db):
    grounder = MagicMock()
    grounder.ground.return_value = []
    assert ground_mention("Collagen II", grounder=grounder) is None


def test_ground_mention_is_idempotent(db, stub_grounder):
    e1 = ground_mention("IL1B", grounder=stub_grounder)
    e2 = ground_mention("IL-1B", grounder=stub_grounder)
    assert e1 is not None
    assert e2 is not None
    assert e1.pk == e2.pk
    assert OntologyEntity.objects.count() == 1
    assert Identifier.objects.filter(scheme="HGNC", value="5992").count() == 1


def test_ground_mention_uses_entity_type_hint_when_provided(db, make_match):
    grounder = MagicMock()
    grounder.ground.return_value = [make_match("MIRBASE", "MIMAT0000076", "miR-21", 0.92)]
    entity = ground_mention("miR-21", entity_type_hint="mirna", grounder=grounder)
    assert entity is not None
    assert entity.entity_type == "mirna"


def test_ground_mention_blank_input_returns_none(db):
    grounder = MagicMock()
    assert ground_mention("", grounder=grounder) is None
    assert ground_mention("   ", grounder=grounder) is None
    grounder.ground.assert_not_called()


def test_ground_mention_chooses_top_score(db, make_match):
    grounder = MagicMock()
    grounder.ground.return_value = [
        make_match("HGNC", "5992", "IL1B", 0.95),
        make_match("HGNC", "5993", "IL1A", 0.85),
    ]
    entity = ground_mention("IL-1", grounder=grounder)
    assert entity is not None
    assert entity.identifiers.filter(value="5992").exists()
    assert not entity.identifiers.filter(value="5993").exists()


def test_ground_mention_gracefully_handles_grounder_exception(db):
    grounder = MagicMock()
    grounder.ground.side_effect = RuntimeError("network unavailable")
    # Should not raise; should return None
    result = ground_mention("IL1B", grounder=grounder)
    assert result is None


def test_http_grounder_used_when_url_set(db, settings, httpx_mock):
    """When GILDA_GROUNDING_URL is set, ground_mention uses the web service
    (no local gilda import) and maps the JSON to an OntologyEntity."""
    from core.services import ground_mention

    settings.GILDA_GROUNDING_URL = "https://grounding.example/ground"
    httpx_mock.add_response(
        method="POST",
        url="https://grounding.example/ground",
        json=[{"score": 1.0, "term": {"db": "HGNC", "id": "11892", "entry_name": "TNF"}}],
    )
    oe = ground_mention("TNF-alpha")
    assert oe is not None
    assert oe.preferred_label == "TNF"
    assert oe.identifiers.filter(scheme="HGNC", value="11892").exists()


def test_http_grounder_below_threshold_returns_none(db, settings, httpx_mock):
    from core.services import ground_mention

    settings.GILDA_GROUNDING_URL = "https://grounding.example/ground"
    httpx_mock.add_response(
        method="POST",
        url="https://grounding.example/ground",
        json=[{"score": 0.4, "term": {"db": "HGNC", "id": "99", "entry_name": "X"}}],
    )
    assert ground_mention("ambiguous") is None
