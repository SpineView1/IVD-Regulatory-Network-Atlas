"""End-to-end stack verification tests (Task 19).

These tests validate the Phase 2 compose/settings without requiring a live
cluster. They serve as the machine-checkable analogue of the manual e2e
procedure documented in docs/superpowers/plans/2026-05-19-phase-2-extraction.md
§ Task 19.

Live cluster procedure (run on the SIMBIOsys cluster after docker-compose up -d):

  1. docker compose ps
     → Expect 15+ services Up: caddy, web, beat, worker_io, worker_fast,
       postgres, redis, minio, grobid, plus 7 worker_extract_* services.

  2. docker compose exec web python manage.py showmigrations extract
     → [X] 0001_initial, [X] 0002_seed_prompt

  3. docker compose exec web python manage.py shell -c
       "from extract.models import PromptTemplate; print(PromptTemplate.objects.get(is_active=True).version)"
     → 1.0.0

  4. docker compose logs worker_extract_qwen3_8b 2>&1 | grep -m1 "Connected to redis"
     → One line per worker confirming queue consumption.

  5. docker compose exec web pytest apps/extract/tests/test_smoke_all_models.py -m live -v -s
     → test_smoke_all_seven_models_produce_results PASSED
       models_with_at_least_one >= 5

  6. Wait 5 min; check beat fires:
     docker compose logs beat 2>&1 | grep "enqueue_pending_chunks"

  7. docker compose down  (volumes preserved)
"""

from __future__ import annotations

import subprocess

import pytest
from django.conf import settings


def test_compose_file_is_valid():
    """docker compose config exits 0 — compose file parses without error.

    Skipped when docker is not available (e.g. inside a test container).
    The compose file is also validated by the host-side scripts/verify.sh gate.
    """
    try:
        result = subprocess.run(  # noqa: S603
            [  # noqa: S607
                "docker",
                "compose",
                "-f",
                "docker-compose.yml",
                "config",
                "--services",
            ],
            capture_output=True,
            text=True,
        )
        services = result.stdout.splitlines()
        worker_extract = [s for s in services if s.startswith("worker_extract_")]
        assert (
            len(worker_extract) == 7
        ), f"Expected 7 worker_extract_* services, found {len(worker_extract)}: {worker_extract}"
    except FileNotFoundError:
        pytest.skip("docker not available in this environment; validated by scripts/verify.sh")


def test_seven_worker_extract_services_in_settings():
    """Verify CELERY_TASK_ROUTES has extract routes and no static run_ppi."""
    routes = settings.CELERY_TASK_ROUTES
    assert "extract.tasks.enqueue_pending_chunks" in routes
    assert "extract.tasks.smoke_all_models" in routes
    assert "extract.tasks.run_ppi" not in routes


def test_all_seven_model_queues_covered():
    """Every model in SUPPORTED_OLLAMA_MODELS has a corresponding q.extract.* queue."""
    from extract.prompts import SUPPORTED_OLLAMA_MODELS
    from extract.routing import MODEL_TO_QUEUE, queue_for_model

    assert len(SUPPORTED_OLLAMA_MODELS) == 7
    for model in SUPPORTED_OLLAMA_MODELS:
        slug = MODEL_TO_QUEUE[model]
        assert slug, f"No slug for model {model}"
        queue = queue_for_model(model)
        assert queue.startswith("q.extract."), f"Queue {queue} should start with q.extract."


def test_ollama_env_vars_present_in_settings():
    """OLLAMA_* and AUTHELIA_SVC_* settings are present in base.py."""
    assert hasattr(settings, "OLLAMA_BASE_URL")
    assert hasattr(settings, "OLLAMA_AUTHELIA_BASE")
    assert hasattr(settings, "OLLAMA_USER")
    assert hasattr(settings, "OLLAMA_PASSWORD")
    assert hasattr(settings, "OLLAMA_KEEP_ALIVE")
    assert hasattr(settings, "OLLAMA_SESSION_COOKIE"), (
        "OLLAMA_SESSION_COOKIE must be a Django setting; .env.example documents it "
        "but base.py lacked the corresponding os.environ.get() assignment."
    )
    assert hasattr(settings, "AUTHELIA_SVC_USER")
    assert hasattr(settings, "AUTHELIA_SVC_PASSWORD")


@pytest.mark.django_db
def test_active_prompt_template_exists_after_migration():
    """The seed migration 0002_seed_prompt must create an active PromptTemplate."""
    from extract.models import PromptTemplate

    active = PromptTemplate.objects.filter(is_active=True).first()
    assert active is not None, "No active PromptTemplate; check 0002_seed_prompt migration"
    assert active.version == "1.0.0"
