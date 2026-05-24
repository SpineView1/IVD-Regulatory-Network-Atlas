"""Add prompt-V2 curation fields (species, deg_status) to RawPPI."""

from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("extract", "0002_seed_prompt")]

    operations = [
        migrations.AddField(
            model_name="rawppi",
            name="species",
            field=models.CharField(blank=True, max_length=16, null=True),
        ),
        migrations.AddField(
            model_name="rawppi",
            name="deg_status",
            field=models.CharField(blank=True, max_length=8, null=True),
        ),
    ]
