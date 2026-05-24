"""Tests for verify.emails — event-type -> (subject, body) rendering."""

from __future__ import annotations

import pytest

from verify.emails import render_event_email


def test_render_stale_email(network):
    subject, body = render_event_email(
        event_type="network_stale",
        network=network,
        message="12 new disagreements",
        user=None,
    )
    assert network.title in subject
    assert "stale" in body.lower() or "disagreement" in body.lower()
    assert network.code in body


def test_render_disagreements_email(network):
    subject, body = render_event_email(
        event_type="network_disagreements",
        network=network,
        message="3 open conflicts",
        user=None,
    )
    assert network.title in subject
    assert "3 open conflicts" in body


def test_render_signed_off_email(network):
    subject, body = render_event_email(
        event_type="network_signed_off",
        network=network,
        message="signed off as v1.0.0",
        user=None,
    )
    assert "signed off" in subject.lower()
    assert "verified" in body.lower()


def test_render_new_version_email(network):
    subject, body = render_event_email(
        event_type="new_version",
        network=network,
        message="v0.3.3 published",
        user=None,
    )
    assert "new version" in subject.lower()
    assert "v0.3.3 published" in body


def test_render_unknown_event_raises(network):
    with pytest.raises(ValueError):
        render_event_email(event_type="not_an_event", network=network, message="x", user=None)
