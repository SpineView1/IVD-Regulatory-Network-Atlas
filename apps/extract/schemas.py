"""Pydantic models for the PPI extraction response.

Single source of truth for:
  • the JSON schema we pass to Ollama via the ``format`` parameter
  • the validator that parses Ollama's response before persistence

Per spec §4 the prompt asks the LLM to emit
``{subject, object, relation, evidence_span, cell_type, stimulus, confidence}``;
we additionally require character offsets into the chunk so the graph
phase can recover the exact evidence text without re-scanning.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AllowedRelation(StrEnum):
    ACTIVATES = "activates"
    INHIBITS = "inhibits"
    BINDS = "binds"
    PHOSPHORYLATES = "phosphorylates"
    DEPHOSPHORYLATES = "dephosphorylates"
    UBIQUITINATES = "ubiquitinates"
    DEUBIQUITINATES = "deubiquitinates"
    TRANSCRIBES = "transcribes"
    REPRESSES = "represses"
    CLEAVES = "cleaves"
    TRANSLOCATES = "translocates"


class PPITuple(BaseModel):
    """One extracted protein-protein (or protein-RNA, protein-metabolite) interaction."""

    model_config = ConfigDict(extra="forbid", use_enum_values=False)

    subject: str = Field(min_length=1, max_length=128)
    object: str = Field(min_length=1, max_length=128)
    relation: AllowedRelation
    evidence_span: str = Field(min_length=1, max_length=2000)
    evidence_offset_start: int = Field(ge=0)
    evidence_offset_end: int = Field(ge=1)
    cell_type: str | None = Field(default=None, max_length=128)
    stimulus: str | None = Field(default=None, max_length=256)
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _check_offsets(self) -> PPITuple:
        if self.evidence_offset_end <= self.evidence_offset_start:
            raise ValueError(
                "evidence_offset_end must be strictly greater than evidence_offset_start"
            )
        return self


class PPIExtractionResponse(BaseModel):
    """Top-level wrapper. Ollama returns an object so that an empty list
    is encodable as ``{"ppis": []}`` instead of an ambiguous ``[]``.
    """

    model_config = ConfigDict(extra="forbid")

    ppis: list[PPITuple] = Field(default_factory=list, max_length=64)


def _build_json_schema() -> dict[str, Any]:
    """Return the schema dict in the exact shape Ollama's ``format`` wants.

    Ollama accepts the same JSON Schema dialect Pydantic emits, except
    that ``$defs`` and ``$ref`` are inlined to keep models from getting
    confused. We dereference here once at import time.
    """
    raw = PPIExtractionResponse.model_json_schema()
    defs = raw.pop("$defs", {})

    def inline(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                ref_name = node["$ref"].rsplit("/", 1)[-1]
                return inline(defs[ref_name])
            return {k: inline(v) for k, v in node.items()}
        if isinstance(node, list):
            return [inline(x) for x in node]
        return node

    return inline(raw)


PPI_JSON_SCHEMA: dict[str, Any] = _build_json_schema()
