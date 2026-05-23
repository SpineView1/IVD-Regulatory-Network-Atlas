"""extract Celery tasks.

  - ``run_ppi(row_id)``          — one per Ollama queue. Runs an
                                   ExtractionRun against its model and
                                   persists RawPPI rows.
  - ``enqueue_pending_chunks()`` — Beat-fired fan-out: find unprocessed
                                   (Chunk × Model) pairs and route each
                                   to its model's queue.

Per spec §4 / §6 / §8.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.heartbeat import with_heartbeat
from core.ollama import OllamaClient, OllamaError
from extract.models import ExtractionRun, RawPPI
from extract.prompts import SUPPORTED_OLLAMA_MODELS
from extract.routing import MODEL_TO_QUEUE, queue_for_model
from extract.schemas import PPI_JSON_SCHEMA, AllowedRelation, PPIExtractionResponse
from extract.services import active_prompt_version, build_prompt_text, upsert_runs_for_chunk

logger = logging.getLogger(__name__)

_ALLOWED_RELATIONS = tuple(r.value for r in AllowedRelation)


def _ollama_generate(
    *,
    model: str,
    prompt: str,
) -> tuple[str, float | None, int]:
    """Indirection so tests can patch the Ollama call cleanly.

    Constructs a fresh client per task because workers have
    concurrency=1 and tasks are infrequent enough that connection
    reuse across tasks isn't worth carrying global state.
    """
    client = OllamaClient(
        base_url=settings.OLLAMA_BASE_URL,
        authelia_base=settings.OLLAMA_AUTHELIA_BASE,
        username=settings.OLLAMA_USER,
        password=settings.OLLAMA_PASSWORD,
    )
    try:
        return client.generate_structured(
            model=model,
            prompt=prompt,
            json_schema=PPI_JSON_SCHEMA,
            allowed_relations=_ALLOWED_RELATIONS,
        )
    finally:
        client.close()


def _fetch_run(row_id: int) -> ExtractionRun:
    return ExtractionRun.objects.select_related("chunk").get(id=row_id)


def _provider_for_model(model_name: str) -> str:
    """Map model slug to rate-limit bucket provider string.

    Provider naming convention: ``ollama_<slug>`` where slug is the
    result of MODEL_TO_QUEUE mapping (same slugification as queue names).
    """
    slug = MODEL_TO_QUEUE.get(model_name, model_name.lower().replace(":", "_").replace(".", "_").replace("-", "_"))
    return f"ollama_{slug}"


@shared_task(
    name="extract.tasks.run_ppi",
    bind=False,
)
@with_heartbeat(interval_sec=30, fetch=_fetch_run)
def run_ppi(row_id: int) -> str:
    """Execute one (chunk × model) extraction.

    Idempotent: if ``status == 'done'`` the task short-circuits.

    Per spec §4:
    1. Load ExtractionRun (idempotency gate on status == 'done').
    2. Mark status='running', set heartbeat, increment attempts.
    3. Render active prompt with chunk text.
    4. Call OllamaClient.generate_structured(format=PPI_JSON_SCHEMA, logprobs).
    5. Parse → RawPPI bulk insert (with relation_logprob).
    6. Append model slug to Chunk.processed_by_models.
    7. Mark status='done'.
    On failure: status='failed' with error.
    """
    from schedule.ratelimit import RateLimitExceeded, require_token

    run = _fetch_run(row_id)
    if run.status == ExtractionRun.Status.DONE:
        return "already_done"

    # Gate on per-model rate-limit bucket.
    provider = _provider_for_model(run.model_name)
    try:
        from schedule.models import RateLimitBucket

        bucket = RateLimitBucket.objects.get(provider=provider)
        if not bucket.consume(1):
            retry_in = bucket.seconds_until_refill(1)
            # Re-enqueue with countdown instead of raising to avoid losing the task.
            run_ppi.apply_async(kwargs={"row_id": row_id}, countdown=int(retry_in) + 1)
            return "rate_limited"
    except Exception:
        # If bucket lookup fails (e.g. not seeded), proceed without gating.
        logger.warning("run_ppi: could not acquire rate-limit token for %s", provider)

    run.status = ExtractionRun.Status.RUNNING
    run.started_at = timezone.now()
    run.attempts = run.attempts + 1
    run.error = ""
    run.save(update_fields=["status", "started_at", "attempts", "error", "updated_at"])

    prompt_text = build_prompt_text(run.chunk.text)
    t0 = time.monotonic()
    try:
        response_text, relation_logprob, eval_count = _ollama_generate(
            model=run.model_name, prompt=prompt_text
        )
        parsed: dict[str, Any] = json.loads(response_text)
        validated = PPIExtractionResponse.model_validate(parsed)
    except Exception as exc:
        # Catches OllamaError, JSONDecodeError, pydantic ValidationError, etc.
        run.status = ExtractionRun.Status.FAILED
        run.error = f"{type(exc).__name__}: {exc}"[:2000]
        run.finished_at = timezone.now()
        run.duration_ms = int((time.monotonic() - t0) * 1000)
        run.save(update_fields=["status", "error", "finished_at", "duration_ms", "updated_at"])
        logger.warning("run_ppi failed run_id=%d: %s", row_id, run.error)
        return "failed"

    # Build RawPPI rows — store relation as STRING (ppi.relation is StrEnum
    # so str(ppi.relation) == ppi.relation.value e.g. "activates").
    raw_rows = [
        RawPPI(
            run=run,
            subject=ppi.subject,
            object=ppi.object,
            relation=str(ppi.relation),
            evidence_span=ppi.evidence_span,
            evidence_offset_start=ppi.evidence_offset_start,
            evidence_offset_end=ppi.evidence_offset_end,
            cell_type=ppi.cell_type,
            stimulus=ppi.stimulus,
            confidence=ppi.confidence,
            relation_logprob=relation_logprob,
        )
        for ppi in validated.ppis
    ]

    with transaction.atomic():
        if raw_rows:
            RawPPI.objects.bulk_create(raw_rows)

        run.status = ExtractionRun.Status.DONE
        run.finished_at = timezone.now()
        run.duration_ms = int((time.monotonic() - t0) * 1000)
        run.response_tokens = eval_count
        run.save(
            update_fields=[
                "status",
                "finished_at",
                "duration_ms",
                "response_tokens",
                "updated_at",
            ]
        )

        # Append model to Chunk.processed_by_models (Phase 1 reserved this field).
        # Use F-expression-free approach: fetch, modify, save with update_fields.
        from papers.models import Chunk

        chunk = Chunk.objects.get(pk=run.chunk_id)
        if run.model_name not in chunk.processed_by_models:
            chunk.processed_by_models = list(chunk.processed_by_models) + [run.model_name]
            chunk.save(update_fields=["processed_by_models", "updated_at"])

    return "done"


@shared_task(name="extract.tasks.enqueue_pending_chunks")
def enqueue_pending_chunks(batch_size: int = 200) -> dict[str, int]:
    """Beat-fired fan-out (every 5 min per spec §6 Beat schedule).

    Finds Chunks that haven't been run against every model with the
    active prompt, creates the missing ExtractionRun rows, and routes a
    Celery message per row to its model's queue.

    Selects only Results-section chunks. Skips chunks where all 7 models
    already appear in ``Chunk.processed_by_models`` for the active prompt
    version (done guard).

    Returns a dict ``{model_name: count_enqueued}`` for logging.
    """
    from papers.models import Chunk

    version = active_prompt_version()
    enqueued: dict[str, int] = {m: 0 for m in SUPPORTED_OLLAMA_MODELS}

    # Find Results chunks not yet fully processed for this prompt version.
    # A chunk is "pending" for a model if it has no ExtractionRun with
    # status in (done, running) for that model + version.
    candidate_chunks = list(
        Chunk.objects.filter(section__doco_type="Results")
        .exclude(
            extraction_runs__prompt_version=version,
            extraction_runs__status__in=[
                ExtractionRun.Status.DONE,
                ExtractionRun.Status.RUNNING,
            ],
        )
        .distinct()
        .order_by("id")[:batch_size]
    )

    for chunk in candidate_chunks:
        upsert_runs_for_chunk(chunk.id)
        runs = ExtractionRun.objects.filter(
            chunk=chunk,
            prompt_version=version,
            status=ExtractionRun.Status.QUEUED,
        )
        for run in runs:
            run_ppi.apply_async(
                kwargs={"row_id": run.id},
                queue=queue_for_model(run.model_name),
            )
            enqueued[run.model_name] += 1

    logger.info("enqueue_pending_chunks dispatched: %s", enqueued)
    return enqueued
