"""Tests for extract.prompts — versioned PPI prompt text and renderer."""
from __future__ import annotations

import pytest

from extract.prompts import (
    PROMPT_V1_BODY,
    PROMPT_V1_VERSION,
    SUPPORTED_OLLAMA_MODELS,
    render_prompt,
)


def test_prompt_version_is_semver_string():
    assert isinstance(PROMPT_V1_VERSION, str)
    parts = PROMPT_V1_VERSION.split(".")
    assert len(parts) == 3
    assert all(p.isdigit() for p in parts)


def test_prompt_body_mentions_all_required_fields():
    body = PROMPT_V1_BODY.lower()
    for field in ("subject", "object", "relation", "evidence_span",
                  "cell_type", "stimulus", "confidence"):
        assert field in body, f"prompt missing field: {field}"


def test_prompt_body_lists_intervertebral_disc_context():
    """The prompt must orient the model to the IVD biology domain
    (spec §0 — domain-specific scope) so out-of-domain entities aren't
    over-extracted from off-topic text."""
    assert "intervertebral disc" in PROMPT_V1_BODY.lower()


def test_render_prompt_substitutes_chunk_text():
    rendered = render_prompt("BMP2 phosphorylates SMAD1 in NP cells.")
    assert "BMP2 phosphorylates SMAD1 in NP cells." in rendered


def test_render_prompt_no_unfilled_placeholders():
    rendered = render_prompt("any text")
    # double-brace marker we use for placeholders
    assert "{{" not in rendered
    assert "}}" not in rendered


def test_render_prompt_includes_relation_enum():
    rendered = render_prompt("x")
    for relation in ("activates", "inhibits", "binds", "phosphorylates"):
        assert relation in rendered


def test_supported_models_is_exactly_seven():
    assert len(SUPPORTED_OLLAMA_MODELS) == 7
    assert set(SUPPORTED_OLLAMA_MODELS) == {
        "medgemma:27b",
        "phi4:14b",
        "qwen3:8b",
        "gemma3:12b",
        "deepseek-r1:32b",
        "devstral:24b",
        "llama3.1:8b",
    }
