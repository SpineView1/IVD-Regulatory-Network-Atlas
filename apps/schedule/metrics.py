"""Custom Prometheus collectors for the interactome stack.

django-prometheus auto-registers any module imported during startup that
defines a subclass of ``prometheus_client.registry.Collector``. To make
the import side-effect explicit, this module is imported from
``apps/schedule/apps.py:ScheduleConfig.ready``.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

from django.utils import timezone
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import REGISTRY, Collector
from redis import Redis

CELERY_QUEUES = (
    "q.io",
    "q.fast",
    "q.extract.medgemma_27b",
    "q.extract.phi4_14b",
    "q.extract.qwen3_8b",
    "q.extract.gemma3_12b",
    "q.extract.deepseek_r1_32b",
    "q.extract.devstral_24b",
    "q.extract.llama3_1_8b",
)


class CeleryQueueDepthCollector(Collector):
    """Reports the LLEN of each known Celery queue list in Redis."""

    def __init__(self) -> None:
        self._redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

    def _redis_llen(self, queue: str) -> int:
        client = Redis.from_url(self._redis_url, socket_timeout=2)
        try:
            return int(client.llen(queue) or 0)  # type: ignore[arg-type]
        finally:
            client.close()

    def collect(self) -> Iterator[GaugeMetricFamily]:
        g = GaugeMetricFamily(
            "interactome_celery_queue_depth",
            "Number of pending messages in each Celery queue.",
            labels=["queue"],
        )
        for queue in CELERY_QUEUES:
            try:
                g.add_metric([queue], self._redis_llen(queue))
            except Exception:  # noqa: BLE001 — never blow up the scrape
                g.add_metric([queue], -1.0)
        yield g


class HealthcheckAgeCollector(Collector):
    """Seconds elapsed since the last successful ``schedule.healthcheck`` run."""

    def collect(self) -> Iterator[GaugeMetricFamily]:
        from schedule.models import HealthcheckState  # noqa: PLC0415 — lazy import

        g = GaugeMetricFamily(
            "interactome_healthcheck_last_run_seconds_ago",
            "Wall-clock seconds since the schedule.healthcheck task last completed.",
        )
        try:
            state = HealthcheckState.objects.get(id=1)
            delta = (timezone.now() - state.last_run_at).total_seconds()
            g.add_metric([], float(delta))
        except Exception:  # noqa: BLE001
            g.add_metric([], -1.0)
        yield g


_registered = False


def register_collectors() -> None:
    """Idempotent — safe to call multiple times during test runs."""
    global _registered
    if _registered:
        return
    REGISTRY.register(CeleryQueueDepthCollector())
    REGISTRY.register(HealthcheckAgeCollector())
    _registered = True
