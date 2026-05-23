"""corpus.tasks — refresh_pubmed, ingest_paper, triage_relevance, ...

Each task is idempotent: first line short-circuits if work is already
done (per spec §8 resumability pattern).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from django.utils import timezone

from celery import shared_task
from core.ollama import OllamaClient
from corpus.clients.ncbi import NcbiClient
from corpus.clients.pubtator import PubtatorClient
from corpus.models import IngestRun, Paper, PaperRelevance
from corpus.pubmed_query import MASTER_IDD_QUERY, build_incremental_query
from networks.models import Network
from schedule.ratelimit import RateLimitExceeded
from schedule.watermarks import advance_watermark, get_watermark

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Task 24: refresh_pubmed
# ---------------------------------------------------------------------------


@shared_task(
    name="corpus.tasks.refresh_pubmed",
    bind=True,
    autoretry_for=(RateLimitExceeded,),
    retry_backoff=True,
    max_retries=5,
)
def refresh_pubmed(self: Any) -> dict:
    """Incremental PubMed sweep. Enqueues ingest_paper for each new PMID."""
    wm = get_watermark("pubmed")
    query = build_incremental_query(since=wm.last_entrez_date)
    client = NcbiClient()
    run = IngestRun.objects.create(source="pubmed", query=query)
    try:
        pmids = client.esearch(query=query, retmax=10000)
        existing = set(Paper.objects.filter(pmid__in=pmids).values_list("pmid", flat=True))
        new_pmids = [p for p in pmids if p not in existing]
        for pmid in new_pmids:
            ingest_paper.delay(pmid)
        run.n_pmids_seen = len(pmids)
        run.n_papers_created = 0  # incremented later by ingest_paper itself
        run.finished_at = timezone.now()
        run.save()
        if pmids:
            advance_watermark("pubmed", last_pmid_seen=max(pmids))
        return {
            "n_pmids_seen": len(pmids),
            "n_new": len(new_pmids),
        }
    except Exception as exc:
        run.error = str(exc)[:4000]
        run.finished_at = timezone.now()
        run.save()
        raise


@shared_task(
    name="corpus.tasks.refresh_pubmed_full",
    bind=True,
    autoretry_for=(RateLimitExceeded,),
    retry_backoff=True,
    max_retries=5,
)
def refresh_pubmed_full(self: Any) -> dict:
    """Weekly full re-sweep with the unbounded master query.

    Re-finds papers that may have been missed by incremental runs.
    (per spec §6: weekly Sunday 03:00 UTC)
    """
    client = NcbiClient()
    run = IngestRun.objects.create(source="pubmed_full", query=MASTER_IDD_QUERY)
    try:
        pmids = client.esearch(query=MASTER_IDD_QUERY, retmax=100000)
        existing = set(Paper.objects.filter(pmid__in=pmids).values_list("pmid", flat=True))
        new_pmids = [p for p in pmids if p not in existing]
        for pmid in new_pmids:
            ingest_paper.delay(pmid)
        run.n_pmids_seen = len(pmids)
        run.finished_at = timezone.now()
        run.save()
        return {"n_pmids_seen": len(pmids), "n_new": len(new_pmids)}
    except Exception as exc:
        run.error = str(exc)[:4000]
        run.finished_at = timezone.now()
        run.save()
        raise


# ---------------------------------------------------------------------------
# Task 25: ingest_paper
# ---------------------------------------------------------------------------


@shared_task(
    name="corpus.tasks.ingest_paper",
    bind=True,
    autoretry_for=(RateLimitExceeded,),
    retry_backoff=True,
    max_retries=5,
)
def ingest_paper(self: Any, pmid: int) -> str:
    """Fetch metadata + PubTator annotations for one PMID; upsert Paper row."""
    paper, _created = Paper.objects.get_or_create(
        pmid=pmid, defaults={"title": "", "ingest_status": "pending"}
    )
    if paper.ingest_status in {
        "ingested",
        "classified",
        "fetched",
        "chunked",
        "done",
    }:
        return paper.ingest_status

    paper.ingest_status = "running"
    paper.ingest_attempts += 1
    paper.ingest_heartbeat = timezone.now()
    paper.save(update_fields=["ingest_status", "ingest_attempts", "ingest_heartbeat"])

    try:
        ncbi = NcbiClient()
        results = ncbi.efetch(pmids=[pmid])
        if not results:
            paper.ingest_status = "ingest_failed"
            paper.ingest_error = "efetch returned no records"
            paper.save(update_fields=["ingest_status", "ingest_error", "updated_at"])
            return "ingest_failed"
        meta = results[0]
        paper.title = meta.title
        paper.abstract = meta.abstract
        paper.journal = meta.journal
        paper.doi = meta.doi
        paper.pmcid = meta.pmcid
        paper.publication_date = meta.publication_date
        paper.entrez_date = meta.entrez_date
        paper.publication_types = meta.publication_types
        paper.mesh_terms = meta.mesh_terms
        paper.authors = meta.authors

        try:
            pubtator = PubtatorClient()
            paper.pubtator_entities = pubtator.get_annotations(pmid=pmid)
        except Exception as pt_exc:
            logger.warning("PubTator fetch failed for %s: %s", pmid, pt_exc)
            paper.pubtator_entities = []

        paper.ingest_status = "ingested"
        paper.ingest_error = ""
        paper.save()
        # Hand off to the classifier — wired in Task 26.
        from papers.tasks import classify_original  # noqa: PLC0415

        classify_original.delay(pmid)
        return "ingested"
    except Exception as exc:
        paper.ingest_status = "ingest_failed"
        paper.ingest_error = str(exc)[:4000]
        paper.save(update_fields=["ingest_status", "ingest_error", "updated_at"])
        raise


# ---------------------------------------------------------------------------
# Task 29: triage_relevance (two-pass)
# ---------------------------------------------------------------------------

TRIAGE_PROMPT = """You are deciding whether a biomedical paper provides
primary experimental evidence relevant to a specific regulatory network
of the intervertebral disc.

Network: {network_title}
Network description: {network_description}

Paper title: {title}
Paper abstract: {abstract}

Reply ONLY with a JSON object:
{{"relevant": true|false, "confidence": 0.0..1.0, "reason": "short"}}
"""

TRIAGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "relevant": {"type": "boolean"},
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["relevant", "confidence"],
}


@shared_task(name="corpus.tasks.triage_pending")
def triage_pending() -> dict:
    """Beat entrypoint — sweep chunked papers without a relevance record."""
    queued = 0
    # An "untriaged" paper has zero PaperRelevance rows.
    qs = (
        Paper.objects.filter(ingest_status="chunked", is_original=True)
        .exclude(relevances__isnull=False)
        .values_list("pmid", flat=True)
    )
    for pmid in qs:
        triage_relevance_cheap.delay(pmid)
        queued += 1
    return {"queued": queued}


def _keyword_matches(keyword: str, haystack: str) -> bool:
    """True if keyword appears as a whole word (or phrase) in haystack.

    Uses word-boundary regex so that "RELA" does NOT match "unrelated"
    but DOES match "RELA is upregulated".  The keyword itself may contain
    spaces/hyphens (e.g. "NF-kB"), so we use ``\\b`` only at the outer
    edges of the pattern.
    """
    # Escape the keyword for regex, then wrap in word boundaries.
    pattern = r"\b" + re.escape(keyword.lower()) + r"\b"
    return bool(re.search(pattern, haystack))


@shared_task(name="corpus.tasks.triage_relevance_cheap")
def triage_relevance_cheap(paper_id: int) -> dict:
    """Cheap pass: keyword + PubTator alias matching against every active network."""
    paper = Paper.objects.get(pmid=paper_id)
    haystack = f"{paper.title}\n{paper.abstract or ''}".lower()
    pubtator_texts = {(e.get("text") or "").upper() for e in (paper.pubtator_entities or [])}
    matched = 0
    for network in Network.objects.filter(is_active=True):
        keyword_hit = any(_keyword_matches(kw, haystack) for kw in (network.keywords or []))
        alias_hit = any(
            alias.upper() in pubtator_texts for alias in (network.root_entity_aliases or [])
        )
        if not keyword_hit and not alias_hit:
            continue
        classified_by = "cheap_keyword" if keyword_hit else "cheap_pubtator"
        PaperRelevance.objects.update_or_create(
            paper=paper,
            network=network,
            defaults={
                "score": 0.5,
                "classified_by": classified_by,
                "reason": f"keyword_hit={keyword_hit}, alias_hit={alias_hit}",
            },
        )
        triage_relevance_llm.delay(paper_id, network.pk)
        matched += 1
    return {"matched_networks": matched}


@shared_task(
    name="corpus.tasks.triage_relevance_llm",
    bind=True,
    autoretry_for=(RateLimitExceeded,),
    retry_backoff=True,
    max_retries=3,
)
def triage_relevance_llm(self: Any, paper_id: int, network_id: int) -> dict:
    """Expensive pass: refine cheap-pass score using qwen3:8b verdict."""
    paper = Paper.objects.get(pmid=paper_id)
    network = Network.objects.get(pk=network_id)
    prompt = TRIAGE_PROMPT.format(
        network_title=network.title,
        network_description=(network.description or "")[:500],
        title=paper.title[:500],
        abstract=(paper.abstract or "")[:3000],
    )
    relevant = True
    confidence = 0.5
    reason = ""
    llm_parse_failed = False
    try:
        client = OllamaClient()
        raw = client.generate(
            model="qwen3:8b",
            prompt=prompt,
            format=TRIAGE_SCHEMA,
            options={"temperature": 0.0},
        )
        payload = json.loads(raw.get("response", ""))
        relevant = bool(payload["relevant"])
        confidence = float(payload.get("confidence", 0.5))
        reason = str(payload.get("reason", ""))[:500]
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
        logger.warning(
            "triage LLM fallback for paper=%s network=%s: %s",
            paper_id,
            network_id,
            exc,
        )
        llm_parse_failed = True

    if llm_parse_failed:
        # Do NOT downgrade: preserve the existing cheap-pass score (>= 0.5) so
        # the paper is not silently dropped from the corpus on an LLM malfunction.
        existing = PaperRelevance.objects.filter(paper=paper, network=network).first()
        existing_score = existing.score if existing else 0.5
        return {"score": existing_score, "relevant": True, "llm_parse_failed": True}

    final_score = confidence if relevant else (1.0 - confidence)
    PaperRelevance.objects.update_or_create(
        paper=paper,
        network=network,
        defaults={
            "score": final_score,
            "classified_by": "llm:qwen3:8b",
            "reason": reason,
        },
    )
    return {"score": final_score, "relevant": relevant}
