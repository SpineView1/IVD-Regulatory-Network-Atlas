"""Tests for monitoring.models."""
from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from monitoring.models import FeatureFlag, HealthAlert


def test_feature_flag_singleton_per_name(db):
    FeatureFlag.objects.create(name="INGESTION_PAUSED", value=False)
    with pytest.raises(Exception):  # IntegrityError, but stays portable
        FeatureFlag.objects.create(name="INGESTION_PAUSED", value=True)


def test_feature_flag_defaults_to_false(db):
    flag = FeatureFlag.objects.create(name="EXTRACT_PAUSED")
    assert flag.value is False


def test_feature_flag_records_change_metadata(db):
    flag = FeatureFlag.objects.create(name="INGESTION_PAUSED", value=False)
    flag.value = True
    flag.last_changed_by = "fchemorion"
    flag.last_changed_reason = "cluster maintenance"
    flag.save()
    flag.refresh_from_db()
    assert flag.last_changed_by == "fchemorion"
    assert flag.last_changed_reason == "cluster maintenance"


def test_healthalert_severity_choices(db):
    a = HealthAlert.objects.create(
        check_name="corpus.refresh_pubmed_stale",
        severity="error",
        message="No successful refresh in 3h",
    )
    assert a.severity == "error"


def test_healthalert_resolved_at_defaults_null(db):
    a = HealthAlert.objects.create(
        check_name="ollama_unreachable",
        severity="critical",
        message="Connection refused",
    )
    assert a.resolved_at is None
    assert a.is_open is True


def test_healthalert_mark_resolved(db):
    a = HealthAlert.objects.create(
        check_name="ollama_unreachable",
        severity="critical",
        message="Connection refused",
    )
    a.resolve(by="fchemorion", note="restarted ollama container")
    a.refresh_from_db()
    assert a.is_open is False
    assert a.resolved_at is not None
    assert (timezone.now() - a.resolved_at) < timedelta(seconds=5)
    assert a.resolved_by == "fchemorion"
    assert a.resolution_note == "restarted ollama container"


def test_healthalert_audit_trail_append_only(db):
    """Same check_name firing twice produces two rows, never an UPDATE."""
    HealthAlert.objects.create(check_name="x", severity="warning", message="m1")
    HealthAlert.objects.create(check_name="x", severity="warning", message="m2")
    assert HealthAlert.objects.filter(check_name="x").count() == 2
