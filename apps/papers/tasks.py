"""papers.tasks — classify_original, fetch_fulltext, section_and_chunk.

Cheap-first classification per spec §4:
- Rule-based on PubMed publication types catches Reviews / Meta-Analyses
  / Systematic Reviews / Editorials (~70% per spec).
- LLM fallback (qwen3:8b) reads title+abstract and returns a structured
  JSON verdict.

The Beat schedule fires `classify_pending` every 15 minutes to sweep
any Paper with `ingest_status='ingested'`.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.transaction import on_commit

from celery import shared_task
from core.minio_client import MinioClient, paper_object_key
from core.ollama import OllamaClient
from corpus.clients.europepmc import EuropePmcClient, EuropePmcNotFound
from corpus.models import Paper
from papers.chunking import chunk_text
from papers.doco import DOCO_IRI_PREFIX
from papers.jats import parse_jats
from papers.models import Chunk, PaperClassification, Section

logger = logging.getLogger(__name__)

# PubTypes that unambiguously mean "not primary research".
NON_ORIGINAL_PUBTYPES = {
    "Review",
    "Meta-Analysis",
    "Systematic Review",
    "Editorial",
    "Comment",
    "News",
    "Practice Guideline",
    "Letter",
}

CLASSIFY_PROMPT = """You are classifying a biomedical paper as either
ORIGINAL primary research or a SECONDARY work (review, editorial,
commentary, opinion piece, guideline).

Title: {title}

Abstract: {abstract}

Reply ONLY with a JSON object of the form:
{{"is_original": true|false, "confidence": 0.0..1.0, "reason": "short reason"}}
"""

CLASSIFY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "is_original": {"type": "boolean"},
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["is_original", "confidence"],
}

# Sections we slice into chunks. Results is primary; Conclusions is aux.
CHUNKABLE_DOCO_LABELS = {"Results", "Conclusion", "Abstract"}


# ---------------------------------------------------------------------------
# Task 26: classify_original
# ---------------------------------------------------------------------------


@shared_task(name="papers.tasks.classify_pending")
def classify_pending() -> dict:
    """Beat entrypoint — enqueue classify_original for unclassified papers."""
    queued = 0
    for pmid in Paper.objects.filter(
        ingest_status="ingested", is_original__isnull=True
    ).values_list("pmid", flat=True):
        classify_original.delay(pmid)
        queued += 1
    return {"queued": queued}


@shared_task(name="papers.tasks.classify_original")
def classify_original(pmid: int) -> str:
    """Classify one paper as original vs review/secondary."""
    paper = Paper.objects.get(pmid=pmid)
    if paper.is_original is not None:
        return "already_classified"

    pubtypes = set(paper.publication_types or [])
    matched = pubtypes & NON_ORIGINAL_PUBTYPES
    if matched:
        _save_classification(
            paper,
            is_original=False,
            confidence=1.0,
            classifier="rule:pubtype",
            reason=f"publication_types contains {sorted(matched)}",
        )
        return "rule:non_original"

    # Expensive path: LLM
    prompt = CLASSIFY_PROMPT.format(
        title=paper.title[:500],
        abstract=(paper.abstract or "")[:3000],
    )
    is_original = True
    confidence = 0.5
    reason = "default"
    classifier = "rule:pubtype"
    try:
        client = OllamaClient()
        raw = client.generate(
            model="qwen3:8b",
            prompt=prompt,
            format=CLASSIFY_SCHEMA,
            options={"temperature": 0.0},
        )
        text = raw.get("response", "")
        payload = json.loads(text)
        is_original = bool(payload["is_original"])
        confidence = float(payload.get("confidence", 0.5))
        reason = str(payload.get("reason", "")).strip()[:500]
        classifier = "llm:qwen3:8b"
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
        logger.warning("LLM classify fell back to rule for pmid=%s: %s", pmid, exc)
        is_original = True  # conservative — keep in pipeline
        reason = f"llm_fallback: {exc}"
    except Exception as exc:
        # Network/Ollama errors: log with pmid, keep paper retryable at
        # ingest_status='ingested' (do NOT save any state), then re-raise so
        # Celery can retry.
        logger.warning(
            "LLM classify raised unexpected error for pmid=%s (%s: %s); re-raising for retry",
            pmid,
            type(exc).__name__,
            exc,
        )
        raise

    _save_classification(
        paper,
        is_original=is_original,
        confidence=confidence,
        classifier=classifier,
        reason=reason,
    )
    return classifier


def _save_classification(
    paper: Paper,
    *,
    is_original: bool,
    confidence: float,
    classifier: str,
    reason: str,
) -> None:
    PaperClassification.objects.update_or_create(
        paper=paper,
        defaults={
            "is_original": is_original,
            "confidence": confidence,
            "classifier": classifier,
            "reason": reason,
        },
    )
    paper.is_original = is_original
    paper.classification_confidence = confidence
    paper.classification_reason = reason
    paper.ingest_status = "classified"
    paper.save(
        update_fields=[
            "is_original",
            "classification_confidence",
            "classification_reason",
            "ingest_status",
            "updated_at",
        ]
    )
    # Hand off to fulltext fetcher.
    fetch_fulltext.delay(paper.pmid)


# ---------------------------------------------------------------------------
# Task 27: fetch_fulltext
# ---------------------------------------------------------------------------


@shared_task(name="papers.tasks.fetch_fulltext_pending")
def fetch_fulltext_pending() -> dict:
    """Beat entrypoint — enqueue fetch_fulltext for classified originals."""
    queued = 0
    for pmid in Paper.objects.filter(
        ingest_status="classified",
        is_original=True,
        full_text_status__in=["none", "fetch_failed"],
    ).values_list("pmid", flat=True):
        fetch_fulltext.delay(pmid)
        queued += 1
    return {"queued": queued}


@shared_task(name="papers.tasks.fetch_fulltext")
def fetch_fulltext(pmid: int) -> str:
    """Fetch full text for one paper (Europe PMC JATS or abstract fallback)."""
    paper = Paper.objects.get(pmid=pmid)
    if paper.full_text_status in {"pmc_jats", "grobid_tei"}:
        return "already_fetched"

    if not paper.pmcid:
        paper.full_text_status = "abstract_only"
        paper.ingest_status = "fetched"
        paper.save(update_fields=["full_text_status", "ingest_status", "updated_at"])
        section_and_chunk.delay(pmid)
        return "abstract_only"

    try:
        epc = EuropePmcClient()
        xml = epc.get_jats_for_pmcid(paper.pmcid)
    except EuropePmcNotFound:
        paper.full_text_status = "abstract_only"
        paper.ingest_status = "fetched"
        paper.fulltext_fetch_error = "europepmc:idDoesNotExist"
        paper.save(
            update_fields=[
                "full_text_status",
                "ingest_status",
                "fulltext_fetch_error",
                "updated_at",
            ]
        )
        section_and_chunk.delay(pmid)
        return "abstract_only"
    except Exception as exc:
        paper.full_text_status = "fetch_failed"
        paper.fulltext_fetch_error = str(exc)[:4000]
        paper.save(update_fields=["full_text_status", "fulltext_fetch_error", "updated_at"])
        raise

    key = paper_object_key(pmid, "xml")
    minio = MinioClient()
    minio.put_object(
        bucket=settings.MINIO_BUCKET_PAPERS,
        key=key,
        body=xml,
        content_type="application/xml",
    )
    paper.fulltext_s3_key = key
    paper.full_text_status = "pmc_jats"
    paper.fulltext_fetch_error = ""
    paper.ingest_status = "fetched"
    paper.save(
        update_fields=[
            "fulltext_s3_key",
            "full_text_status",
            "fulltext_fetch_error",
            "ingest_status",
            "updated_at",
        ]
    )
    section_and_chunk.delay(pmid)
    return "pmc_jats"


# ---------------------------------------------------------------------------
# Task 28: section_and_chunk
# ---------------------------------------------------------------------------


@shared_task(name="papers.tasks.section_pending")
def section_pending() -> dict:
    """Beat entrypoint — enqueue section_and_chunk for fetched papers."""
    queued = 0
    for pmid in Paper.objects.filter(ingest_status="fetched", is_original=True).values_list(
        "pmid", flat=True
    ):
        section_and_chunk.delay(pmid)
        queued += 1
    return {"queued": queued}


@shared_task(name="papers.tasks.section_and_chunk")
def section_and_chunk(pmid: int) -> str:
    """Parse XML/abstract into Section rows and Chunk rows for one paper."""
    paper = Paper.objects.get(pmid=pmid)
    if paper.ingest_status == "chunked":
        return "already_chunked"

    if paper.full_text_status == "abstract_only":
        return _section_abstract_only(paper)

    if paper.full_text_status == "pmc_jats" and paper.fulltext_s3_key:
        return _section_from_jats(paper)

    if paper.full_text_status == "grobid_tei" and paper.fulltext_s3_key:
        # Phase 1 punts on TEI parsing; treat like abstract until Phase 2
        # adds the TEI parser. Mark chunked with abstract for now.
        return _section_abstract_only(paper)

    # Nothing usable — mark chunked-empty so we don't loop.
    paper.ingest_status = "chunked"
    paper.save(update_fields=["ingest_status", "updated_at"])
    return "no_content"


@transaction.atomic
def _section_abstract_only(paper: Paper) -> str:
    text = paper.abstract or ""
    if not text.strip():
        paper.ingest_status = "chunked"
        paper.save(update_fields=["ingest_status", "updated_at"])
        return "empty_abstract"
    section = Section.objects.create(
        paper=paper,
        order_index=0,
        doco_type="Abstract",
        doco_iri=f"{DOCO_IRI_PREFIX}Abstract",
        heading="Abstract",
        body_text=text,
        token_count=len(text.split()),
    )
    _persist_chunks(section, text)
    paper.ingest_status = "chunked"
    paper.save(update_fields=["ingest_status", "updated_at"])
    # Enqueue triage after commit to avoid the Celery-in-transaction race.
    from corpus.tasks import triage_relevance_cheap  # noqa: PLC0415

    _pmid = paper.pmid
    on_commit(lambda: triage_relevance_cheap.delay(_pmid))
    return "chunked_abstract"


@transaction.atomic
def _section_from_jats(paper: Paper) -> str:
    minio = MinioClient()
    xml = minio.get_object(
        bucket=settings.MINIO_BUCKET_PAPERS,
        key=paper.fulltext_s3_key,
    )
    parsed = parse_jats(xml)
    if not parsed:
        return _section_abstract_only(paper)

    for ps in parsed:
        section = Section.objects.create(
            paper=paper,
            order_index=ps.order_index,
            doco_type=ps.doco_label,
            doco_iri=ps.doco_iri,
            heading=ps.heading,
            body_text=ps.body_text,
            token_count=len(ps.body_text.split()),
        )
        if ps.doco_label in CHUNKABLE_DOCO_LABELS:
            _persist_chunks(section, ps.body_text)
    paper.ingest_status = "chunked"
    paper.save(update_fields=["ingest_status", "updated_at"])
    # Enqueue triage after commit to avoid the Celery-in-transaction race.
    from corpus.tasks import triage_relevance_cheap  # noqa: PLC0415

    _pmid = paper.pmid
    on_commit(lambda: triage_relevance_cheap.delay(_pmid))
    return "chunked_jats"


def _persist_chunks(section: Section, text: str) -> int:
    records = chunk_text(text, max_tokens=1800, overlap_tokens=200)
    objs = [
        Chunk(
            section=section,
            paper_id=section.paper_id,
            chunk_index=r.chunk_index,
            text=r.text,
            token_count=r.token_count,
            char_offset_start=r.char_offset_start,
            char_offset_end=r.char_offset_end,
        )
        for r in records
    ]
    Chunk.objects.bulk_create(objs)
    return len(objs)
