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

Phase 2 additions:
  • ``OllamaError`` — unified error alias for ``OllamaResponseError``
  • ``extract_relation_logprob()`` — renormalised logprob over a relation enum
  • ``OllamaClient.generate_structured()`` — schema-constrained decoding
    (``format``=JSON schema), logprob capture, and manual exponential
    backoff on 5xx / timeouts.

Settings:
    OLLAMA_BASE_URL — Ollama gateway URL (https://ollama.<cluster>)
    OLLAMA_AUTHELIA_BASE — Authelia URL (https://authelia.<cluster>)
    OLLAMA_USER / OLLAMA_PASSWORD — env-injected credentials
    OLLAMA_DEFAULT_TIMEOUT — seconds (default 120)
    OLLAMA_KEEP_ALIVE — Ollama model-keep-alive hint (default "2h")
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Sequence
from typing import Any

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

_RETRYABLE_STATUSES = {408, 425, 429, 500, 502, 503, 504}
_MAX_STRUCTURED_RETRIES = 5
_INITIAL_BACKOFF_SEC = 2.0


class OllamaAuthError(RuntimeError):
    """Authelia rejected the username/password."""


class OllamaResponseError(RuntimeError):
    """Ollama returned a non-2xx outside the auth domain."""


# Unified error alias used by Phase 2+ code and consumers.
OllamaError = OllamaResponseError


def extract_relation_logprob(
    logprobs: list[dict[str, Any]] | None,
    *,
    allowed_relations: Sequence[str],
) -> float | None:
    """Find the first per-token logprob step whose token matches a relation
    string, then renormalise the top_logprobs over the allowed enum.

    Returns ``None`` if no step matches (e.g. the response was empty or
    the model went off-prompt before emitting a relation field).

    The approach mirrors the medgemma-validated logprob pipeline used in the
    NFBC IDD LLM probe.
    """
    if not logprobs:
        return None

    allowed = set(allowed_relations)
    for step in logprobs:
        token = step.get("token", "")
        for rel in allowed:
            if token == rel or token.startswith(rel):
                top = step.get("top_logprobs") or []
                # Restrict to candidates that map to an allowed relation.
                candidates: list[tuple[str, float]] = []
                for entry in top:
                    cand_tok = entry.get("token", "")
                    for cand_rel in allowed:
                        if cand_tok == cand_rel or cand_tok.startswith(cand_rel):
                            candidates.append((cand_rel, float(entry["logprob"])))
                            break
                if not candidates:
                    # Fall back to the chosen step's raw logprob.
                    return float(step.get("logprob", 0.0))
                # Renormalise: log-sum-exp denominator over enum candidates.
                lp_self = next(
                    (lp for r, lp in candidates if r == rel),
                    float(step.get("logprob", 0.0)),
                )
                denom = math.log(sum(math.exp(lp) for _, lp in candidates))
                return lp_self - denom

    return None


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

    # ---- Phase 2: schema-constrained decoding + logprob + backoff ----------

    def generate_structured(
        self,
        *,
        model: str,
        prompt: str,
        json_schema: dict[str, Any],
        allowed_relations: Sequence[str],
        max_retries: int = _MAX_STRUCTURED_RETRIES,
        initial_backoff_sec: float = _INITIAL_BACKOFF_SEC,
    ) -> tuple[str, float | None, int]:
        """Schema-constrained generation with exponential backoff.

        Passes ``json_schema`` as Ollama's ``format`` parameter (schema-
        constrained decoding) and requests ``logprobs=True`` so we can
        extract a calibrated relation-level logprob.

        Returns ``(response_text, relation_logprob, eval_count)``where:
          • ``response_text`` — raw string from Ollama (caller validates)
          • ``relation_logprob`` — renormalised logprob over the enum,
            or ``None`` if the response lacks logprob data
          • ``eval_count`` — number of generated tokens
        """
        self._ensure_authenticated()
        url = f"{self.base_url}/api/generate"
        payload: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": json_schema,
            "keep_alive": self.keep_alive,
            "options": {
                "logprobs": True,
                "top_logprobs": 5,
                "temperature": 0.0,
            },
        }

        attempt = 0
        backoff = initial_backoff_sec
        last_error: str = ""

        while attempt <= max_retries:
            try:
                response = self._client.post(url, json=payload, headers=self._cookie_header())
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = f"network: {exc}"
                logger.warning(
                    "ollama generate_structured network error attempt=%d: %s", attempt, exc
                )
            else:
                if response.status_code == 401:
                    # Auth/session-expiry event: immediate re-auth, no retry
                    # slot consumed, no backoff sleep (matches _post_with_auth
                    # 401 policy). If _login() itself returns 401 it raises
                    # OllamaAuthError, which is the correct terminal behaviour.
                    self._authenticated = False
                    self._session_cookie = None
                    self._login()
                    continue  # immediate re-auth: no attempt increment, no backoff sleep

                if response.status_code in _RETRYABLE_STATUSES:
                    last_error = f"http {response.status_code}: {response.text[:200]}"
                    logger.warning(
                        "ollama generate_structured retryable status=%d attempt=%d",
                        response.status_code,
                        attempt,
                    )
                elif response.status_code >= 400:
                    raise OllamaResponseError(
                        f"ollama permanent error {response.status_code}: {response.text[:500]}"
                    )
                else:
                    body_out = response.json()
                    response_text: str = body_out.get("response", "")
                    eval_count: int = int(body_out.get("eval_count", 0))
                    rel_lp = extract_relation_logprob(
                        body_out.get("logprobs"),
                        allowed_relations=allowed_relations,
                    )
                    return response_text, rel_lp, eval_count

            attempt += 1
            if attempt <= max_retries:
                time.sleep(backoff)
                backoff *= 2

        raise OllamaResponseError(
            f"ollama generate_structured failed after {max_retries} retries;"
            f" last_error={last_error}"
        )

    def close(self) -> None:
        self._client.close()


def refresh_authelia_session(
    *,
    authelia_url: str,
    username: str,
    password: str,
    timeout_sec: float = 15.0,
) -> str:
    """Re-authenticate against Authelia ``/api/firstfactor`` and return
    the new ``authelia_session`` cookie value.

    This is a thin stateless helper that wraps the same auth flow as
    ``OllamaClient._login()``. It exists so external callers (management
    commands, periodic tasks) can mint a fresh session cookie without
    constructing a full ``OllamaClient`` instance.

    ``OllamaClient`` already self-refreshes on 401 responses via
    ``_post_with_auth`` and ``generate_structured``; this helper is the
    standalone variant for use cases outside the client lifecycle.

    Raises ``OllamaError`` (alias ``OllamaResponseError``) on non-200 or
    when Authelia returns 200 but omits the cookie.
    """
    response = httpx.post(
        f"{authelia_url.rstrip('/')}/api/firstfactor",
        json={"username": username, "password": password, "keepMeLoggedIn": True},
        timeout=timeout_sec,
    )
    if response.status_code != 200:
        raise OllamaError(f"authelia refresh failed: {response.status_code} {response.text[:200]}")
    set_cookie = response.headers.get("Set-Cookie", "")
    for part in set_cookie.split(";"):
        part = part.strip()
        if part.startswith("authelia_session="):
            return part.split("=", 1)[1]
    raise OllamaError("authelia refresh succeeded but no authelia_session cookie returned")
