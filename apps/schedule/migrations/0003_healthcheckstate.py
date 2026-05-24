"""Add HealthcheckState singleton row.

Phase 7 — records the last successful run time of the monitoring.healthcheck
task so the Prometheus HealthcheckAgeCollector can expose it as a gauge
without touching the monitoring app directly.
"""

from __future__ import annotations

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("schedule", "0002_ollama_buckets"),
    ]

    operations = [
        migrations.CreateModel(
            name="HealthcheckState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True)),
                ("last_run_at", models.DateTimeField()),
                ("status", models.CharField(max_length=16, default="ok")),
            ],
            options={"db_table": "schedule_healthcheckstate"},
        ),
        migrations.RunSQL(
            sql="INSERT INTO schedule_healthcheckstate (id, last_run_at, status) VALUES (1, now(), 'ok');",
            reverse_sql="DELETE FROM schedule_healthcheckstate WHERE id = 1;",
        ),
    ]
