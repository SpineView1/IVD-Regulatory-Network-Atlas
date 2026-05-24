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

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from celery import shared_task
from core.heartbeat import with_heartbeat
from core.ollama import OllamaClient, OllamaError
from extract.models import ExtractionRun, RawPPI
from extract.prompts import SUPPORTED_OLLAMA_MODELS, active_models
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


def _execute_run(run: ExtractionRun) -> str:
    """Shared extraction logic used by both run_ppi and smoke_all_models.

    Performs the full correct sequence for one (chunk × model) extraction:
    1. Mark status=running, set started_at, increment attempts.
    2. Render active prompt and call _ollama_generate.
    3. Parse + validate PPIExtractionResponse.
    4. bulk_create RawPPI rows (relation stored as string, relation_logprob set).
    5. Update Chunk.processed_by_models under select_for_update().
    6. Mark status=done.

    Returns "done" on success or "failed" on permanent (non-OllamaError) failure.

    OllamaError is intentionally NOT caught here — it is re-raised so that:
    - run_ppi (which has Celery retry machinery) can intercept and schedule retries.
    - smoke_all_models catches it inline and marks failed for that model.

    All other exceptions (JSONDecodeError, pydantic ValidationError, etc.) are
    caught, written as status=failed, and "failed" is returned.
    """
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
    except OllamaError:
        # Re-raise transient errors so run_ppi can schedule retries via
        # self.retry(). smoke_all_models catches this inline.
        raise
    except Exception as exc:
        # Permanent failures: JSONDecodeError, pydantic ValidationError, etc.
        run.status = ExtractionRun.Status.FAILED
        run.error = f"{type(exc).__name__}: {exc}"[:2000]
        run.finished_at = timezone.now()
        run.duration_ms = int((time.monotonic() - t0) * 1000)
        run.save(update_fields=["status", "error", "finished_at", "duration_ms", "updated_at"])
        logger.warning("_execute_run failed run_id=%d model=%s: %s", run.id, run.model_name, exc)
        return "failed"

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
        # Use select_for_update() so concurrent workers serialize their appends
        # and none are lost (Fix 2: prevent lost-update race).
        from papers.models import Chunk

        chunk = Chunk.objects.select_for_update().get(pk=run.chunk_id)
        if run.model_name not in chunk.processed_by_models:
            chunk.processed_by_models = list(chunk.processed_by_models) + [run.model_name]
            chunk.save(update_fields=["processed_by_models", "updated_at"])

    return "done"


def _provider_for_model(model_name: str) -> str:
    """Map model slug to rate-limit bucket provider string.

    Provider naming convention: ``ollama_<slug>`` where slug is the
    result of MODEL_TO_QUEUE mapping (same slugification as queue names).
    """
    slug = MODEL_TO_QUEUE.get(
        model_name, model_name.lower().replace(":", "_").replace(".", "_").replace("-", "_")
    )
    return f"ollama_{slug}"


@shared_task(
    name="extract.tasks.run_ppi",
    bind=True,
    autoretry_for=(OllamaError,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
@with_heartbeat(interval_sec=30, fetch=_fetch_run)
def run_ppi(self: Any, row_id: int) -> str:
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
    run = _fetch_run(row_id)
    if run.status == ExtractionRun.Status.DONE:
        return "already_done"

    # Gate on per-model rate-limit bucket.
    provider = _provider_for_model(run.model_name)
    try:
        from schedule.models import RateLimitBucket

        try:
            bucket = RateLimitBucket.objects.get(provider=provider)
        except RateLimitBucket.DoesNotExist:
            # Bucket not yet seeded — proceed without gating.
            logger.warning("run_ppi: could not acquire rate-limit token for %s", provider)
        else:
            if not bucket.consume(1):
                retry_in = bucket.seconds_until_refill(1)
                # Re-enqueue with countdown instead of raising to avoid losing the task.
                run_ppi.apply_async(kwargs={"row_id": row_id}, countdown=int(retry_in) + 1)
                return "rate_limited"
    except ImportError:
        # schedule app not available — proceed without gating.
        logger.warning("run_ppi: schedule app not available, skipping rate-limit for %s", provider)

    # Transient Ollama errors: retry with exponential backoff before delegating
    # to _execute_run. We must intercept OllamaError here (before _execute_run)
    # because only the @shared_task context has self.retry().
    try:
        return _execute_run(run)
    except OllamaError as exc:
        # Transient Ollama error — retry with exponential backoff.
        # Explicitly call self.retry() so retries < max_retries leaves the
        # row in running state (not FAILED).  Only after retries are exhausted
        # (MaxRetriesExceededError) do we write status=failed.
        if self.request.retries < self.max_retries:
            # Raise Retry — row stays running; janitor handles stale running rows
            # if the worker dies between retries.
            raise self.retry(exc=exc, countdown=2**self.request.retries) from None
        # All retries exhausted: mark permanently failed (duplicate of _execute_run
        # failure path but needed here so we can inspect self.request.retries).
        run.refresh_from_db()
        run.status = ExtractionRun.Status.FAILED
        run.error = f"{type(exc).__name__}: {exc}"[:2000]
        run.finished_at = timezone.now()
        run.save(update_fields=["status", "error", "finished_at", "updated_at"])
        logger.warning("run_ppi failed (retries exhausted) run_id=%d: %s", row_id, run.error)
        return "failed"


@shared_task(name="extract.tasks.smoke_all_models")
def smoke_all_models(chunk_id: int) -> dict[str, int]:
    """Synchronously run one chunk through all 7 models in-process.

    Intended for operator smoke-testing and the live integration test.
    Bypasses the queue: it calls ``_execute_run`` directly (creating
    ExtractionRun rows and RawPPI rows) rather than dispatching to the
    per-model queues. This makes it usable from a shell or a test
    without requiring all workers to be running.

    Uses ``_execute_run`` (the shared helper) so processed_by_models is
    updated correctly for each model — preventing enqueue_pending_chunks
    from re-enqueuing chunks already handled by this task (Fix C-2).

    Returns ``{model_name: raw_ppi_count}`` for each model.
    """
    # Fix Q-4: call upsert first (which internally reads active_prompt_version),
    # then read version once — eliminates the double read / version-skew window.
    upsert_runs_for_chunk(chunk_id)
    version = active_prompt_version()

    counts: dict[str, int] = {}
    for model_name in SUPPORTED_OLLAMA_MODELS:
        try:
            run = ExtractionRun.objects.get(
                chunk_id=chunk_id,
                model_name=model_name,
                prompt_version=version,
            )
        except ExtractionRun.DoesNotExist:
            logger.warning("smoke_all_models: no run for model=%s chunk=%d", model_name, chunk_id)
            counts[model_name] = 0
            continue

        if run.status == ExtractionRun.Status.DONE:
            counts[model_name] = RawPPI.objects.filter(run=run).count()
            continue

        try:
            _execute_run(run)
        except Exception as exc:
            logger.warning("smoke_all_models run failed model=%s: %s", model_name, exc)
            counts[model_name] = 0
            continue

        n = RawPPI.objects.filter(run=run).count()
        counts[model_name] = n
        logger.info("smoke_all_models model=%s ppis=%d", model_name, n)

    return counts


@shared_task(name="extract.tasks.enqueue_pending_chunks")
def enqueue_pending_chunks(batch_size: int = 200) -> dict:
    """Beat-fired fan-out (every 5 min per spec §6 Beat schedule).

    Finds Chunks that haven't been run against every model with the
    active prompt, creates the missing ExtractionRun rows, and routes a
    Celery message per row to its model's queue.

    Short-circuits if INGESTION_PAUSED is set. Does NOT honour
    backpressure — when we *are* backpressured, this task is exactly
    what drains the queue.

    Selects only Results-section chunks. Skips chunks where all 7 models
    already appear in ``Chunk.processed_by_models`` for the active prompt
    version (done guard).

    Returns a dict ``{model_name: count_enqueued}`` for logging.
    """
    from monitoring import services as monitoring_services  # noqa: PLC0415 — lazy to avoid circular

    if monitoring_services.is_ingestion_paused():
        return {"skipped": True, "reason": "ingestion_paused"}
    return _do_enqueue_pending_chunks(batch_size=batch_size)


def _do_enqueue_pending_chunks(batch_size: int = 200) -> dict:
    """The original body of enqueue_pending_chunks — extracted to allow pause-flag wrapping."""
    from papers.models import Chunk

    version = active_prompt_version()
    models = active_models()
    enqueued: dict[str, int] = {m: 0 for m in models}

    # Find Results chunks not yet fully covered by all models for this version.
    # A chunk is "pending" if fewer than n_models ExtractionRun rows exist with
    # status in (done, running) for the active prompt_version.
    # The old .exclude() approach incorrectly excluded the whole chunk as soon
    # as ONE model finished — the count-annotation correctly tracks coverage.
    n_models = len(models)
    candidate_chunks = list(
        Chunk.objects.filter(section__doco_type="Results")
        .annotate(
            covered=Count(
                "extraction_runs",
                filter=Q(
                    extraction_runs__prompt_version=version,
                    extraction_runs__status__in=[
                        ExtractionRun.Status.DONE,
                        ExtractionRun.Status.RUNNING,
                    ],
                ),
            )
        )
        .filter(covered__lt=n_models)
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
