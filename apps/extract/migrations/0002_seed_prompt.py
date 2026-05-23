"""Insert PROMPT_V1 as the first active PromptTemplate."""

from __future__ import annotations

from typing import Any

from django.db import migrations


def seed_prompt(apps: Any, schema_editor: Any) -> None:
    PromptTemplate = apps.get_model("extract", "PromptTemplate")
    from extract.prompts import PROMPT_V1_BODY, PROMPT_V1_VERSION

    PromptTemplate.objects.update_or_create(
        version=PROMPT_V1_VERSION,
        defaults={"body": PROMPT_V1_BODY, "is_active": True},
    )


def unseed_prompt(apps: Any, schema_editor: Any) -> None:
    PromptTemplate = apps.get_model("extract", "PromptTemplate")
    from extract.prompts import PROMPT_V1_VERSION

    PromptTemplate.objects.filter(version=PROMPT_V1_VERSION).delete()


class Migration(migrations.Migration):
    dependencies = [("extract", "0001_initial")]
    operations = [migrations.RunPython(seed_prompt, unseed_prompt)]
