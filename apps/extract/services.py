"""extract — public service API.

Other apps must call these functions for writes; never reach into
``extract.models`` directly. This is the boundary discipline of spec §2.
"""

from __future__ import annotations

from django.db import transaction

from extract.models import ExtractionRun, PromptTemplate
from extract.prompts import SUPPORTED_OLLAMA_MODELS


def active_prompt_version() -> str:
    """Return the version string of the currently-active PromptTemplate.

    Raises ``RuntimeError`` if no active prompt exists; the seed
    migration ``0002_seed_prompt`` ensures this can only happen if an
    operator manually deactivated every prompt without activating a new
    one.
    """
    try:
        return PromptTemplate.objects.values_list("version", flat=True).get(is_active=True)
    except PromptTemplate.DoesNotExist as exc:
        raise RuntimeError("no active PromptTemplate; check seed migration") from exc


def build_prompt_text(chunk_text: str) -> str:
    """Render the active prompt with the given chunk text."""
    active = PromptTemplate.objects.get(is_active=True)
    return active.body.replace("{{CHUNK_TEXT}}", chunk_text)


@transaction.atomic
def upsert_runs_for_chunk(chunk_id: int) -> int:
    """Create the seven ExtractionRun rows for ``chunk_id`` if missing.

    Returns the count of rows that exist after the operation (always 7,
    barring a row that already advanced to ``done`` under an earlier
    prompt version — those are left untouched). The operation is
    idempotent: re-running it never creates duplicates.
    """
    version = active_prompt_version()
    for model_name in SUPPORTED_OLLAMA_MODELS:
        ExtractionRun.objects.get_or_create(
            chunk_id=chunk_id,
            model_name=model_name,
            prompt_version=version,
        )
    return ExtractionRun.objects.filter(chunk_id=chunk_id, prompt_version=version).count()
