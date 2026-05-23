"""Seed per-model Ollama RateLimitBucket rows.

Per spec §6 (rate limits): every outbound provider gets a token-bucket
persisted in Postgres. Phase 1 introduced the model and the NCBI /
Europe PMC / PubTator3 buckets; Phase 2 adds per-model Ollama buckets.

Phase 1 fixture (0001_buckets.yaml) seeds ``ollama_qwen3_8b``.
This migration seeds the remaining 6 Ollama model buckets and also
ensures all 7 are present for test environments which don't load
YAML fixtures.

Capacity 4 / refill 2.0 per second (matching the Phase 1 qwen3_8b
fixture value):
  - Concurrency 1 per model worker means at most 1 in-flight request.
  - Burst of 4 gives headroom for quick successive enqueuing.
"""

from __future__ import annotations

from django.db import migrations

_OLLAMA_MODEL_BUCKETS = [
    "ollama_qwen3_8b",
    "ollama_medgemma_27b",
    "ollama_phi4_14b",
    "ollama_gemma3_12b",
    "ollama_deepseek_r1_32b",
    "ollama_devstral_24b",
    "ollama_llama3_1_8b",
]

_CAPACITY = 4
_REFILL_PER_SEC = 2.0


def seed(apps, schema_editor) -> None:
    Bucket = apps.get_model("schedule", "RateLimitBucket")
    for provider in _OLLAMA_MODEL_BUCKETS:
        Bucket.objects.get_or_create(
            provider=provider,
            defaults={
                "capacity": _CAPACITY,
                "refill_per_sec": _REFILL_PER_SEC,
                "current_tokens": float(_CAPACITY),
            },
        )


def unseed(apps, schema_editor) -> None:
    Bucket = apps.get_model("schedule", "RateLimitBucket")
    Bucket.objects.filter(provider__in=_OLLAMA_MODEL_BUCKETS).delete()


class Migration(migrations.Migration):
    dependencies = [("schedule", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
