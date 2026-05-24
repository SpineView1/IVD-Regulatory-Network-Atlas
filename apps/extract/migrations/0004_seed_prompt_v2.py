"""Activate PROMPT_V2 (adds species + deg_status) as the live prompt.

Deactivates the prior active template and inserts V2 active, mirroring
0002_seed_prompt. New ExtractionRuns are keyed on the active version, so
this triggers re-extraction under the V2 schema while leaving V1 rows valid.
"""

from __future__ import annotations

from typing import Any

from django.db import migrations


def seed_prompt_v2(apps: Any, schema_editor: Any) -> None:
    PromptTemplate = apps.get_model("extract", "PromptTemplate")
    from extract.prompts import PROMPT_V2_BODY, PROMPT_V2_VERSION

    PromptTemplate.objects.filter(is_active=True).update(is_active=False)
    PromptTemplate.objects.update_or_create(
        version=PROMPT_V2_VERSION,
        defaults={"body": PROMPT_V2_BODY, "is_active": True},
    )


def unseed_prompt_v2(apps: Any, schema_editor: Any) -> None:
    PromptTemplate = apps.get_model("extract", "PromptTemplate")
    from extract.prompts import PROMPT_V1_VERSION, PROMPT_V2_VERSION

    PromptTemplate.objects.filter(version=PROMPT_V2_VERSION).delete()
    PromptTemplate.objects.filter(version=PROMPT_V1_VERSION).update(is_active=True)


class Migration(migrations.Migration):
    dependencies = [("extract", "0003_rawppi_curation_fields")]
    operations = [migrations.RunPython(seed_prompt_v2, unseed_prompt_v2)]
