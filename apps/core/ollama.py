"""Ollama HTTP client with Authelia first-factor authentication.

Flow:
1. ``_login()`` POSTs ``{username, password}`` to
   ``{AUTHELIA_BASE}/api/firstfactor``. Authelia returns 200 plus a
   ``Set-Cookie: authelia_session=...`` cookie on success.
2. The ``authelia_session`` cookie value is captured and added explicitly
   to every subsequent Ollama API call (cross-domain forwarding).
3. ``generate()`` and ``chat()`` POST against the Ollama API,
   automatically including the cookie header. A 401 (cookie expired)
   triggers one re-login attempt before raising.

Settings:
    OLLAMA_BASE_URL — Ollama gateway URL (https://ollama.<cluster>)
    OLLAMA_AUTHELIA_BASE — Authelia URL (https://authelia.<cluster>)
    OLLAMA_USER / OLLAMA_PASSWORD — env-injected credentials
    OLLAMA_DEFAULT_TIMEOUT — seconds (default 120)
    OLLAMA_KEEP_ALIVE — Ollama model-keep-alive hint (default "2h")
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)


class OllamaAuthError(RuntimeError):
    """Authelia rejected the username/password."""


class OllamaResponseError(RuntimeError):
    """Ollama returned a non-2xx outside the auth domain."""


class OllamaClient:
    """One instance per worker process is the intended use.

    Reuses a single httpx.Client with HTTP/2 + cookie persistence so we
    don't redo the Authelia handshake on every call.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        authelia_base: str | None = None,
        username: str | None = None,
        password: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.authelia_base = (authelia_base or settings.OLLAMA_AUTHELIA_BASE).rstrip("/")
        self.username = username or settings.OLLAMA_USER
        self.password = password or settings.OLLAMA_PASSWORD
        self.timeout = timeout if timeout is not None else settings.OLLAMA_DEFAULT_TIMEOUT
        self.keep_alive = settings.OLLAMA_KEEP_ALIVE
        self._client = httpx.Client(
            http2=True,
            timeout=self.timeout,
            follow_redirects=True,
        )
        self._authenticated = False
        self._session_cookie: str | None = None  # authelia_session value

    # ------------------------- auth -------------------------

    def _login(self) -> None:
        url = f"{self.authelia_base}/api/firstfactor"
        response = self._client.post(
            url,
            json={
                "username": self.username,
                "password": self.password,
                "keepMeLoggedIn": True,
            },
        )
        if response.status_code != 200:
            raise OllamaAuthError(
                f"Authelia /api/firstfactor returned {response.status_code}: "
                f"{response.text[:200]}"
            )
        # Extract authelia_session cookie for explicit cross-domain forwarding.
        self._session_cookie = response.cookies.get("authelia_session")
        self._authenticated = True

    def _ensure_authenticated(self) -> None:
        if not self._authenticated:
            self._login()

    def _cookie_header(self) -> dict[str, str]:
        if self._session_cookie:
            return {"cookie": f"authelia_session={self._session_cookie}"}
        return {}

    # ------------------------- API --------------------------

    def generate(
        self,
        *,
        model: str,
        prompt: str,
        format: dict | str | None = None,
        options: dict | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": stream,
            "keep_alive": self.keep_alive,
        }
        if format is not None:
            payload["format"] = format
        if options is not None:
            payload["options"] = options
        return self._post_with_auth("/api/generate", payload)

    def chat(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        format: dict | str | None = None,
        options: dict | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "keep_alive": self.keep_alive,
        }
        if format is not None:
            payload["format"] = format
        if options is not None:
            payload["options"] = options
        return self._post_with_auth("/api/chat", payload)

    # ------------------------- internals -------------------

    def _post_with_auth(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_authenticated()
        url = f"{self.base_url}{path}"
        response = self._client.post(url, json=payload, headers=self._cookie_header())

        if response.status_code == 401:
            # Cookie expired; re-login once and retry.
            self._authenticated = False
            self._session_cookie = None
            self._login()
            response = self._client.post(url, json=payload, headers=self._cookie_header())

        if not response.is_success:
            raise OllamaResponseError(
                f"Ollama {path} returned {response.status_code}: " f"{response.text[:200]}"
            )
        return response.json()

    def close(self) -> None:
        self._client.close()
