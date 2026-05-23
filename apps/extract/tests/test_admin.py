"""Tests for extract admin registrations.

TDD tests for Task 16: verify all three models are registered in
Django admin with the expected list_display fields and filters.
"""

from __future__ import annotations

from django.contrib import admin as django_admin

from extract.models import ExtractionRun, PromptTemplate, RawPPI


def _get_model_admin(model):  # noqa: ANN001
    """Return the registered ModelAdmin for a model, or None."""
    try:
        return django_admin.site._registry[model]
    except KeyError:
        return None


def test_prompt_template_is_registered():
    admin = _get_model_admin(PromptTemplate)
    assert admin is not None, "PromptTemplate must be registered in Django admin"


def test_extraction_run_is_registered():
    admin = _get_model_admin(ExtractionRun)
    assert admin is not None, "ExtractionRun must be registered in Django admin"


def test_raw_ppi_is_registered():
    admin = _get_model_admin(RawPPI)
    assert admin is not None, "RawPPI must be registered in Django admin"


def test_prompt_template_admin_list_display():
    admin = _get_model_admin(PromptTemplate)
    assert admin is not None
    assert "version" in admin.list_display
    assert "is_active" in admin.list_display


def test_extraction_run_admin_list_display():
    admin = _get_model_admin(ExtractionRun)
    assert admin is not None
    assert "id" in admin.list_display
    assert "model_name" in admin.list_display
    assert "status" in admin.list_display


def test_raw_ppi_admin_list_display():
    admin = _get_model_admin(RawPPI)
    assert admin is not None
    assert "subject" in admin.list_display
    assert "relation" in admin.list_display
    assert "confidence" in admin.list_display
