"""Tests for core.models."""

from __future__ import annotations

import time

import pytest
from django.db import connection, models

from core.models import TimestampedModel


class _ConcreteTimestamped(TimestampedModel):
    """A throwaway concrete subclass to exercise the abstract base."""

    name: models.CharField[str, str] = models.CharField(max_length=32)

    class Meta:
        app_label = "core"


@pytest.fixture(autouse=True)
def _create_concrete_table(db):
    with connection.schema_editor() as schema_editor:
        schema_editor.create_model(_ConcreteTimestamped)
    yield
    with connection.schema_editor() as schema_editor:
        schema_editor.delete_model(_ConcreteTimestamped)


def test_timestamped_model_sets_created_at_on_insert(db):
    instance = _ConcreteTimestamped.objects.create(name="alpha")  # type: ignore[attr-defined]
    assert instance.created_at is not None


def test_timestamped_model_sets_updated_at_on_insert(db):
    instance = _ConcreteTimestamped.objects.create(name="alpha")  # type: ignore[attr-defined]
    assert instance.updated_at is not None


def test_timestamped_model_updates_updated_at_on_save(db):
    instance = _ConcreteTimestamped.objects.create(name="alpha")  # type: ignore[attr-defined]
    original_updated_at = instance.updated_at
    time.sleep(0.01)
    instance.name = "beta"
    instance.save()
    assert instance.updated_at > original_updated_at


def test_timestamped_model_does_not_change_created_at_on_save(db):
    instance = _ConcreteTimestamped.objects.create(name="alpha")  # type: ignore[attr-defined]
    original_created_at = instance.created_at
    instance.name = "beta"
    instance.save()
    assert instance.created_at == original_created_at
