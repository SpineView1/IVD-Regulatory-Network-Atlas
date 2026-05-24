"""Tests for core.observability."""

from __future__ import annotations

import json
import logging
import logging.config
from unittest.mock import patch

from core import observability


def test_sentry_init_no_dsn_is_noop(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN_WEB", raising=False)
    with patch("sentry_sdk.init") as mock_init:
        observability.sentry_init(service="web")
    mock_init.assert_not_called()


def test_sentry_init_with_dsn_calls_init(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN_WEB", "https://k@sentry.io/1")
    monkeypatch.setenv("SENTRY_RELEASE", "v1.0.0-test")
    with patch("sentry_sdk.init") as mock_init:
        observability.sentry_init(service="web")
    mock_init.assert_called_once()
    kwargs = mock_init.call_args.kwargs
    assert kwargs["dsn"] == "https://k@sentry.io/1"
    assert kwargs["release"] == "v1.0.0-test"
    assert kwargs["environment"] in {"production", "dev", "test"}


def test_sentry_init_picks_worker_dsn_for_worker(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN_WORKER", "https://w@sentry.io/2")
    monkeypatch.delenv("SENTRY_DSN_WEB", raising=False)
    with patch("sentry_sdk.init") as mock_init:
        observability.sentry_init(service="worker")
    assert mock_init.call_args.kwargs["dsn"] == "https://w@sentry.io/2"


def test_sentry_init_attaches_django_and_celery_integrations(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN_WEB", "https://k@sentry.io/1")
    with patch("sentry_sdk.init") as mock_init:
        observability.sentry_init(service="web")
    integration_classes = {type(i).__name__ for i in mock_init.call_args.kwargs["integrations"]}
    assert "DjangoIntegration" in integration_classes
    assert "CeleryIntegration" in integration_classes


def test_sentry_init_release_falls_back_to_git_sha(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN_WEB", "https://k@sentry.io/1")
    monkeypatch.delenv("SENTRY_RELEASE", raising=False)
    with (
        patch("sentry_sdk.init") as mock_init,
        patch("subprocess.check_output", return_value=b"abcdef0\n"),
    ):
        observability.sentry_init(service="web")
    assert mock_init.call_args.kwargs["release"] == "abcdef0"


def test_configure_log_file_adds_rotating_handler(tmp_path):
    log_path = tmp_path / "app.jsonl"
    logging_dict = {
        "version": 1,
        "disable_existing_loggers": False,
        "handlers": {"console": {"class": "logging.StreamHandler"}},
        "root": {"handlers": ["console"], "level": "INFO"},
    }
    out = observability.configure_log_file(logging_dict, str(log_path))
    assert "file" in out["handlers"]
    assert out["handlers"]["file"]["class"] == "logging.handlers.RotatingFileHandler"
    assert out["handlers"]["file"]["filename"] == str(log_path)
    assert "file" in out["root"]["handlers"]


def test_configure_log_file_creates_parent_dir(tmp_path):
    log_path = tmp_path / "nested" / "deeper" / "app.jsonl"
    observability.configure_log_file(
        {"version": 1, "handlers": {}, "root": {"handlers": [], "level": "INFO"}},
        str(log_path),
    )
    assert log_path.parent.exists()


def test_configure_log_file_writes_json_lines(tmp_path):
    log_path = tmp_path / "app.jsonl"
    cfg = observability.configure_log_file(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "handlers": {},
            "root": {"handlers": [], "level": "INFO"},
        },
        str(log_path),
    )
    logging.config.dictConfig(cfg)
    logging.getLogger("test").info("hello", extra={"key": "value"})
    for h in logging.getLogger().handlers:
        h.flush()
    content = log_path.read_text().strip()
    # Each line must parse as JSON
    for line in content.splitlines():
        assert json.loads(line)
