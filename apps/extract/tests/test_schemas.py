"""Tests for extract.schemas — Pydantic models and JSON-schema export."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from extract.schemas import (
    PPI_JSON_SCHEMA,
    AllowedRelation,
    PPIExtractionResponse,
    PPITuple,
)


def test_valid_payload_parses(sample_ppi_payload):
    parsed = PPIExtractionResponse.model_validate(sample_ppi_payload)
    assert len(parsed.ppis) == 1
    assert parsed.ppis[0].subject == "IL1B"
    assert parsed.ppis[0].relation == AllowedRelation.ACTIVATES


def test_unknown_relation_rejected():
    bad = {
        "ppis": [
            {
                "subject": "A",
                "object": "B",
                "relation": "tickles",  # not in enum
                "evidence_span": "x",
                "evidence_offset_start": 0,
                "evidence_offset_end": 1,
                "cell_type": None,
                "stimulus": None,
                "confidence": 0.5,
            }
        ]
    }
    with pytest.raises(ValidationError):
        PPIExtractionResponse.model_validate(bad)


def test_confidence_must_be_between_0_and_1():
    bad = {
        "ppis": [
            {
                "subject": "A",
                "object": "B",
                "relation": "activates",
                "evidence_span": "x",
                "evidence_offset_start": 0,
                "evidence_offset_end": 1,
                "cell_type": None,
                "stimulus": None,
                "confidence": 1.4,
            }
        ]
    }
    with pytest.raises(ValidationError):
        PPIExtractionResponse.model_validate(bad)


def test_offset_end_must_be_strictly_greater_than_start():
    bad = {
        "ppis": [
            {
                "subject": "A",
                "object": "B",
                "relation": "activates",
                "evidence_span": "x",
                "evidence_offset_start": 5,
                "evidence_offset_end": 5,
                "cell_type": None,
                "stimulus": None,
                "confidence": 0.5,
            }
        ]
    }
    with pytest.raises(ValidationError):
        PPIExtractionResponse.model_validate(bad)


def test_empty_ppi_list_is_valid():
    """A chunk that contains no PPI is a legitimate response."""
    parsed = PPIExtractionResponse.model_validate({"ppis": []})
    assert parsed.ppis == []


def test_json_schema_has_required_top_level_key():
    assert PPI_JSON_SCHEMA["type"] == "object"
    assert "ppis" in PPI_JSON_SCHEMA["properties"]
    assert PPI_JSON_SCHEMA["properties"]["ppis"]["type"] == "array"


def test_json_schema_enumerates_relations():
    relation_schema = PPI_JSON_SCHEMA["properties"]["ppis"]["items"]["properties"]["relation"]
    assert "enum" in relation_schema
    assert set(relation_schema["enum"]) == {
        "activates",
        "inhibits",
        "binds",
        "phosphorylates",
        "dephosphorylates",
        "ubiquitinates",
        "deubiquitinates",
        "transcribes",
        "represses",
        "cleaves",
        "translocates",
    }


def test_tuple_model_serialises_round_trip(sample_ppi_payload):
    parsed = PPIExtractionResponse.model_validate(sample_ppi_payload)
    serialised = parsed.model_dump(mode="json")
    re_parsed = PPIExtractionResponse.model_validate(serialised)
    assert re_parsed == parsed


def test_ppi_tuple_is_directly_importable_and_constructable():
    """PPITuple is a canonical export — confirm direct import + construction."""
    t = PPITuple(
        subject="TNF",
        object="TNFR1",
        relation=AllowedRelation.BINDS,
        evidence_span="TNF binds TNFR1",
        evidence_offset_start=0,
        evidence_offset_end=16,
        cell_type=None,
        stimulus=None,
        confidence=0.85,
    )
    assert t.subject == "TNF"
    assert t.relation == AllowedRelation.BINDS
    assert t.confidence == 0.85
