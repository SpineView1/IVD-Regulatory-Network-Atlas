"""Management command: load Network taxonomy from YAML fixture."""

from __future__ import annotations

from pathlib import Path

import yaml
from django.core.management.base import BaseCommand

from networks.models import Network


class Command(BaseCommand):
    help = "Load Network rows from apps/networks/fixtures/0001_taxonomy.yaml (idempotent)."

    def handle(self, *args: object, **options: object) -> None:
        fixture_path = Path(__file__).resolve().parents[2] / "fixtures" / "0001_taxonomy.yaml"
        data = yaml.safe_load(fixture_path.read_text())
        created = 0
        updated = 0
        for entry in data["networks"]:
            _, was_created = Network.objects.update_or_create(
                code=entry["code"],
                defaults={
                    "category": entry["category"],
                    "title": entry["title"],
                    "description": entry.get("description", ""),
                    "keywords": entry.get("keywords", []),
                    "root_entity_aliases": entry.get("root_entity_aliases", []),
                    "is_active": entry.get("is_active", True),
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1
        self.stdout.write(
            self.style.SUCCESS(f"Loaded {created} new networks, updated {updated} existing.")
        )
