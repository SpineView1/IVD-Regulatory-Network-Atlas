"""Tests for verify.state_machine — pure transition rules."""

from __future__ import annotations

import pytest

from verify.state_machine import (
    InvalidTransition,
    NetworkStatus,
    transition,
)


def test_idle_to_stale_on_new_corpus():
    assert transition(NetworkStatus.IDLE, "new_corpus") == NetworkStatus.STALE


def test_stale_to_refreshing_on_integration_start():
    assert transition(NetworkStatus.STALE, "integration_start") == NetworkStatus.REFRESHING


def test_refreshing_to_version_draft_on_regenerate_done():
    assert transition(NetworkStatus.REFRESHING, "regenerate_done") == NetworkStatus.VERSION_DRAFT


def test_version_draft_to_verified_on_signoff():
    assert transition(NetworkStatus.VERSION_DRAFT, "signoff") == NetworkStatus.VERIFIED


def test_verified_to_stale_on_new_evidence():
    assert transition(NetworkStatus.VERIFIED, "new_corpus") == NetworkStatus.STALE


def test_cannot_signoff_from_idle():
    with pytest.raises(InvalidTransition):
        transition(NetworkStatus.IDLE, "signoff")


def test_cannot_signoff_from_stale():
    with pytest.raises(InvalidTransition):
        transition(NetworkStatus.STALE, "signoff")


def test_unknown_event_raises():
    with pytest.raises(InvalidTransition):
        transition(NetworkStatus.VERSION_DRAFT, "magic_event")


def test_all_statuses_present_in_enum():
    """Spec §7 lists five states; the enum must match exactly."""
    expected = {"idle", "refreshing", "stale", "version_draft", "verified"}
    assert {s.value for s in NetworkStatus} == expected


def test_transition_accepts_string_status():
    """transition() should coerce string values from DB to NetworkStatus."""
    result = transition("version_draft", "signoff")
    assert result == NetworkStatus.VERIFIED


def test_stale_to_stale_is_idempotent():
    """new_corpus on already-STALE is a no-op transition (idempotent)."""
    result = transition(NetworkStatus.STALE, "new_corpus")
    assert result == NetworkStatus.STALE
