"""Shared pytest fixtures for the core app."""

from __future__ import annotations

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor


@pytest.fixture
def db_executor() -> MigrationExecutor:
    """Allows tests to dynamically create models for abstract-base tests."""
    return MigrationExecutor(connection)
