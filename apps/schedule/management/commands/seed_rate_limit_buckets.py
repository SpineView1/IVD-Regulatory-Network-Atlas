"""Management command: seed initial RateLimitBucket rows from YAML fixture."""

from __future__ import annotations

from pathlib import Path

import yaml
from django.core.management.base import BaseCommand

from schedule.models import RateLimitBucket


class Command(BaseCommand):
    help = "Seed RateLimitBucket rows from apps/schedule/fixtures/0001_buckets.yaml"

    def handle(self, *args: object, **options: object) -> None:
        fixture_path = Path(__file__).resolve().parents[2] / "fixtures" / "0001_buckets.yaml"
        data = yaml.safe_load(fixture_path.read_text())
        created = 0
        updated = 0
        for entry in data["buckets"]:
            bucket, was_created = RateLimitBucket.objects.update_or_create(
                provider=entry["provider"],
                defaults={
                    "capacity": entry["capacity"],
                    "refill_per_sec": entry["refill_per_sec"],
                    "current_tokens": entry["capacity"],
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1
        self.stdout.write(
            self.style.SUCCESS(f"Seeded {created} new buckets, updated {updated} existing.")
        )
