"""Tests for core.ollama.OllamaClient."""

from __future__ import annotations

import json

import pytest
from pytest_httpx import HTTPXMock

from core.ollama import OllamaAuthError, OllamaClient, OllamaResponseError


@pytest.fixture
def client(settings):
    settings.OLLAMA_BASE_URL = "https://ollama.example.com"
    settings.OLLAMA_AUTHELIA_BASE = "https://authelia.example.com"
    settings.OLLAMA_USER = "alice"
    settings.OLLAMA_PASSWORD = "s3cret"  # noqa: S105
    settings.OLLAMA_DEFAULT_TIMEOUT = 30.0
    settings.OLLAMA_KEEP_ALIVE = "2h"
    return OllamaClient()


def test_ollama_client_authenticates_via_authelia(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="POST",
        url="https://authelia.example.com/api/firstfactor",
        json={"status": "OK"},
        headers={"Set-Cookie": "authelia_session=abc123; Path=/"},
    )
    httpx_mock.add_response(
        method="POST",
        url="https://ollama.example.com/api/generate",
        json={"response": "hello world", "done": True},
    )
    result = client.generate(model="qwen3:8b", prompt="hi")
    assert result["response"] == "hello world"


def test_ollama_client_sends_session_cookie_on_generate(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="POST",
        url="https://authelia.example.com/api/firstfactor",
        json={"status": "OK"},
        headers={"Set-Cookie": "authelia_session=cookieval; Path=/"},
    )
    httpx_mock.add_response(
        method="POST",
        url="https://ollama.example.com/api/generate",
        json={"response": "x", "done": True},
    )
    client.generate(model="qwen3:8b", prompt="hi")
    second_request = httpx_mock.get_requests()[1]
    assert "authelia_session=cookieval" in second_request.headers.get("cookie", "")


def test_ollama_client_raises_on_authelia_401(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="POST",
        url="https://authelia.example.com/api/firstfactor",
        status_code=401,
        json={"status": "KO", "message": "bad credentials"},
    )
    with pytest.raises(OllamaAuthError):
        client.generate(model="qwen3:8b", prompt="hi")


def test_ollama_client_raises_on_ollama_5xx(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="POST",
        url="https://authelia.example.com/api/firstfactor",
        json={"status": "OK"},
        headers={"Set-Cookie": "authelia_session=ok; Path=/"},
    )
    httpx_mock.add_response(
        method="POST",
        url="https://ollama.example.com/api/generate",
        status_code=503,
        text="service unavailable",
    )
    with pytest.raises(OllamaResponseError):
        client.generate(model="qwen3:8b", prompt="hi")


def test_ollama_client_reuses_session_across_calls(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="POST",
        url="https://authelia.example.com/api/firstfactor",
        json={"status": "OK"},
        headers={"Set-Cookie": "authelia_session=once; Path=/"},
    )
    for _ in range(2):
        httpx_mock.add_response(
            method="POST",
            url="https://ollama.example.com/api/generate",
            json={"response": "y", "done": True},
        )
    client.generate(model="qwen3:8b", prompt="a")
    client.generate(model="qwen3:8b", prompt="b")
    auth_calls = [r for r in httpx_mock.get_requests() if "firstfactor" in str(r.url)]
    assert len(auth_calls) == 1


def test_ollama_client_format_constraint_passed_through(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="POST",
        url="https://authelia.example.com/api/firstfactor",
        json={"status": "OK"},
        headers={"Set-Cookie": "authelia_session=z; Path=/"},
    )
    httpx_mock.add_response(
        method="POST",
        url="https://ollama.example.com/api/generate",
        json={"response": '{"is_original": true}', "done": True},
    )
    schema = {"type": "object", "properties": {"is_original": {"type": "boolean"}}}
    client.generate(model="qwen3:8b", prompt="hi", format=schema)
    gen_request = [r for r in httpx_mock.get_requests() if "/api/generate" in str(r.url)][0]
    body = json.loads(gen_request.content)
    assert body["format"] == schema
    assert body["model"] == "qwen3:8b"
    assert body["prompt"] == "hi"


def test_ollama_client_chat_endpoint(client, httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        method="POST",
        url="https://authelia.example.com/api/firstfactor",
        json={"status": "OK"},
        headers={"Set-Cookie": "authelia_session=z; Path=/"},
    )
    httpx_mock.add_response(
        method="POST",
        url="https://ollama.example.com/api/chat",
        json={"message": {"role": "assistant", "content": "hello"}, "done": True},
    )
    result = client.chat(
        model="qwen3:8b",
        messages=[{"role": "user", "content": "hi"}],
    )
    assert result["message"]["content"] == "hello"
