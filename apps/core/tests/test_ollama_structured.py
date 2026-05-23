"""Tests for the Phase 2 extensions to core.ollama:

  • extract_relation_logprob (module-level function)
  • OllamaError (unified error class)
  • OllamaClient.generate_structured() with schema-constrained decoding,
    logprob extraction, and tenacity exponential backoff.

Phase 1 OllamaClient tests are in test_ollama.py and remain intact.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from pytest_httpx import HTTPXMock

from core.ollama import OllamaClient, OllamaError, extract_relation_logprob

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_response(payload: dict[str, Any], status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        request=httpx.Request("POST", "https://ollama.example.com/api/generate"),
        content=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )


@pytest.fixture
def structured_client(settings):
    settings.OLLAMA_BASE_URL = "https://ollama.example.com"
    settings.OLLAMA_AUTHELIA_BASE = "https://authelia.example.com"
    settings.OLLAMA_USER = "alice"
    settings.OLLAMA_PASSWORD = "s3cret"  # noqa: S105
    settings.OLLAMA_DEFAULT_TIMEOUT = 30.0
    settings.OLLAMA_KEEP_ALIVE = "2h"
    return OllamaClient()


@pytest.fixture
def success_payload() -> dict[str, Any]:
    """A minimal /api/generate JSON envelope with valid PPI content."""
    return {
        "model": "qwen3:8b",
        "response": json.dumps(
            {
                "ppis": [
                    {
                        "subject": "IL1B",
                        "object": "MMP13",
                        "relation": "activates",
                        "evidence_span": "IL-1β induced MMP13",
                        "evidence_offset_start": 0,
                        "evidence_offset_end": 19,
                        "cell_type": None,
                        "stimulus": None,
                        "confidence": 0.9,
                    }
                ]
            }
        ),
        "eval_count": 87,
        "logprobs": [
            {"token": "{", "logprob": -0.01, "top_logprobs": []},
            {"token": '"ppis"', "logprob": -0.02, "top_logprobs": []},
            {
                "token": "activates",
                "logprob": -0.13,
                "top_logprobs": [
                    {"token": "activates", "logprob": -0.13},
                    {"token": "inhibits", "logprob": -2.1},
                ],
            },
        ],
    }


# ---------------------------------------------------------------------------
# extract_relation_logprob tests
# ---------------------------------------------------------------------------


def test_extract_relation_logprob_finds_first_relation_token(success_payload):
    lp = extract_relation_logprob(
        success_payload["logprobs"],
        allowed_relations=("activates", "inhibits", "binds"),
    )
    # Renormalised over (activates=-0.13, inhibits=-2.1) ≈ -0.130 ± 0.01
    assert lp == pytest.approx(-0.13, abs=0.01)


def test_extract_relation_logprob_returns_none_if_no_match():
    logprobs = [{"token": "junk", "logprob": -0.5, "top_logprobs": []}]
    assert extract_relation_logprob(logprobs, allowed_relations=("activates",)) is None


def test_extract_relation_logprob_returns_none_for_empty_list():
    assert extract_relation_logprob([], allowed_relations=("activates",)) is None


def test_extract_relation_logprob_renormalises_over_enum():
    logprobs = [
        {
            "token": "activates",
            "logprob": -1.0,
            "top_logprobs": [
                {"token": "activates", "logprob": -1.0},
                {"token": "inhibits", "logprob": -1.0},
                {"token": "junk", "logprob": -0.1},  # not in enum, must be dropped
            ],
        }
    ]
    lp = extract_relation_logprob(
        logprobs,
        allowed_relations=("activates", "inhibits"),
    )
    # both -1.0, so renormalised log-prob of 'activates' should be log(0.5) ≈ -0.693
    assert lp == pytest.approx(-0.6931, abs=1e-3)


# ---------------------------------------------------------------------------
# OllamaError is importable and is an error class
# ---------------------------------------------------------------------------


def test_ollama_error_is_importable():
    assert issubclass(OllamaError, Exception)


def test_ollama_error_is_compatible_with_response_error():
    # OllamaError must be raise-able and catchable as OllamaError.
    with pytest.raises(OllamaError):
        raise OllamaError("something failed")


# ---------------------------------------------------------------------------
# generate_structured() — schema-constrained decoding + logprob + backoff
# ---------------------------------------------------------------------------


def test_generate_structured_returns_text_logprob_and_eval_count(
    structured_client, success_payload, httpx_mock: HTTPXMock
):
    httpx_mock.add_response(
        method="POST",
        url="https://authelia.example.com/api/firstfactor",
        json={"status": "OK"},
        headers={"Set-Cookie": "authelia_session=tok; Path=/"},
    )
    httpx_mock.add_response(
        method="POST",
        url="https://ollama.example.com/api/generate",
        json=success_payload,
    )
    response_text, relation_logprob, eval_count = structured_client.generate_structured(
        model="qwen3:8b",
        prompt="prompt text",
        json_schema={"type": "object"},
        allowed_relations=("activates", "inhibits", "binds"),
    )
    assert "IL1B" in response_text
    # Renormalised logprob: approx -0.13 (renorm over activates/inhibits)
    assert relation_logprob == pytest.approx(-0.13, abs=0.01)
    assert eval_count == 87


def test_generate_structured_passes_schema_and_logprobs_in_body(
    structured_client, success_payload, httpx_mock: HTTPXMock
):
    httpx_mock.add_response(
        method="POST",
        url="https://authelia.example.com/api/firstfactor",
        json={"status": "OK"},
        headers={"Set-Cookie": "authelia_session=tok; Path=/"},
    )
    httpx_mock.add_response(
        method="POST",
        url="https://ollama.example.com/api/generate",
        json=success_payload,
    )
    schema = {"type": "object", "properties": {"ppis": {"type": "array"}}}
    structured_client.generate_structured(
        model="qwen3:8b",
        prompt="p",
        json_schema=schema,
        allowed_relations=("activates",),
    )
    gen_request = [r for r in httpx_mock.get_requests() if "/api/generate" in str(r.url)][0]
    body = json.loads(gen_request.content)
    assert body["format"] == schema
    assert body["options"]["logprobs"] is True


def test_generate_structured_retries_on_503_then_succeeds(
    structured_client, success_payload, httpx_mock: HTTPXMock
):
    httpx_mock.add_response(
        method="POST",
        url="https://authelia.example.com/api/firstfactor",
        json={"status": "OK"},
        headers={"Set-Cookie": "authelia_session=tok; Path=/"},
    )
    httpx_mock.add_response(
        method="POST",
        url="https://ollama.example.com/api/generate",
        status_code=503,
        text="overloaded",
    )
    httpx_mock.add_response(
        method="POST",
        url="https://ollama.example.com/api/generate",
        json=success_payload,
    )
    # Patch sleep so the test doesn't actually wait
    with patch("core.ollama.time.sleep"):
        response_text, _, _ = structured_client.generate_structured(
            model="qwen3:8b",
            prompt="p",
            json_schema={},
            allowed_relations=("activates",),
        )
    assert "IL1B" in response_text


def test_generate_structured_raises_after_exhausting_retries(
    structured_client, httpx_mock: HTTPXMock
):
    httpx_mock.add_response(
        method="POST",
        url="https://authelia.example.com/api/firstfactor",
        json={"status": "OK"},
        headers={"Set-Cookie": "authelia_session=tok; Path=/"},
    )
    for _ in range(6):  # max_structured_retries (5) + 1
        httpx_mock.add_response(
            method="POST",
            url="https://ollama.example.com/api/generate",
            status_code=503,
            text="overloaded",
        )
    with patch("core.ollama.time.sleep"), pytest.raises(OllamaError):
        structured_client.generate_structured(
            model="qwen3:8b",
            prompt="p",
            json_schema={},
            allowed_relations=("activates",),
        )


def test_generate_structured_reauths_on_401(
    structured_client, success_payload, httpx_mock: HTTPXMock
):
    """A 401 from Ollama during structured generation triggers re-auth."""
    # Initial auth
    httpx_mock.add_response(
        method="POST",
        url="https://authelia.example.com/api/firstfactor",
        json={"status": "OK"},
        headers={"Set-Cookie": "authelia_session=stale; Path=/"},
    )
    # First generate → 401
    httpx_mock.add_response(
        method="POST",
        url="https://ollama.example.com/api/generate",
        status_code=401,
        text="Unauthorized",
    )
    # Re-auth
    httpx_mock.add_response(
        method="POST",
        url="https://authelia.example.com/api/firstfactor",
        json={"status": "OK"},
        headers={"Set-Cookie": "authelia_session=fresh; Path=/"},
    )
    # Retry succeeds
    httpx_mock.add_response(
        method="POST",
        url="https://ollama.example.com/api/generate",
        json=success_payload,
    )
    with patch("core.ollama.time.sleep"):
        response_text, _, _ = structured_client.generate_structured(
            model="qwen3:8b",
            prompt="p",
            json_schema={},
            allowed_relations=("activates",),
        )
    assert "IL1B" in response_text


def test_generate_structured_401_does_not_consume_retry_slot(
    structured_client, success_payload, httpx_mock: HTTPXMock
):
    """A 401 mid-generation re-auths immediately without burning a retry slot.

    With max_retries=1: if 401 consumed a slot we would exhaust retries before
    the final success response. The test passes only when 401 is slot-free.
    """
    # Initial auth
    httpx_mock.add_response(
        method="POST",
        url="https://authelia.example.com/api/firstfactor",
        json={"status": "OK"},
        headers={"Set-Cookie": "authelia_session=stale; Path=/"},
    )
    # First generate → 401 (session expiry, not a transient error)
    httpx_mock.add_response(
        method="POST",
        url="https://ollama.example.com/api/generate",
        status_code=401,
        text="Unauthorized",
    )
    # Re-auth after 401
    httpx_mock.add_response(
        method="POST",
        url="https://authelia.example.com/api/firstfactor",
        json={"status": "OK"},
        headers={"Set-Cookie": "authelia_session=fresh; Path=/"},
    )
    # Second generate → transient 503 (this consumes the 1 real retry slot)
    httpx_mock.add_response(
        method="POST",
        url="https://ollama.example.com/api/generate",
        status_code=503,
        text="overloaded",
    )
    # Third generate → success (retry slot for 503 is still available because
    # the 401 did not consume one)
    httpx_mock.add_response(
        method="POST",
        url="https://ollama.example.com/api/generate",
        json=success_payload,
    )
    with patch("core.ollama.time.sleep"):
        response_text, _, _ = structured_client.generate_structured(
            model="qwen3:8b",
            prompt="p",
            json_schema={},
            allowed_relations=("activates",),
            max_retries=1,  # tight budget: would fail if 401 consumed a slot
        )
    assert "IL1B" in response_text
