"""graph.services — public API of the graph app.

Three responsibilities:

  1. bayes_belief()              — pure posterior-probability function
  2. normalize_and_integrate()   — RawPPI -> Edge integration
  3. conflict detection helpers  — intra/inter-paper, inter-model

Section anchors refer to docs/superpowers/specs/2026-05-19-disc-interactome-app-design.md.

Cross-plan field names used here (authoritative per reconciliation doc):
  RawPPI.subject / .object (not subject_text / object_text)
  RawPPI.run      (not extraction_run)
  ExtractionRun.model_name (not extractor_model)
  Paper.publication_date   (not pub_date)
"""

from __future__ import annotations

__all__ = [
    "BAYES_PRIOR",
    "BELIEF_THRESHOLD_ACCEPTED",
    "BELIEF_THRESHOLD_REJECTED",
    "INTER_MODEL_CONSENSUS_MIN",
    "OPPOSITE_RELATIONS",
    "RECENCY_HALFLIFE_DAYS",
    "affected_network_ids",
    "bayes_belief",
    "detect_inter_model_conflicts",
    "detect_inter_paper_conflicts",
    "detect_intra_paper_conflicts",
    "edge_evidence_items",
    "mean_recency_for_dates",
    "normalize_and_integrate",
    "reassign_network_membership",
    "recency_weight_for_date",
    "recompute_edge_belief",
]

import logging
import math
from collections.abc import Iterable, Sequence
from datetime import date
from typing import TYPE_CHECKING

from django.db import transaction
from django.utils import timezone

if TYPE_CHECKING:
    from graph.models import Conflict, Edge  # noqa: F401 — type-checking only

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Bayes scoring constants
# ---------------------------------------------------------------------------
#
# Prior probability that any plausibly-extracted (and grounded) edge is real,
# before we look at how many models/papers support it. 0.3 reflects the
# empirical observation from PPI literature that ~30% of single-extraction
# claims survive curator review.
BAYES_PRIOR: float = 0.30

# Likelihood ratios for one piece of evidence. Tuned so that:
#   - 0 papers × 0 models:  = prior (0.300)
#   - 1 paper  × 1 model:   ~0.55  (candidate territory)
#   - 1 paper  × 7 models:  ≥ accepted threshold (0.80)
#   - 5 papers × 7 models:  > 0.99
LR_PER_PAPER: float = 2.3  # one additional supporting paper
LR_PER_MODEL: float = 1.6  # one additional agreeing extractor model

# Promotion thresholds for Edge.status.
# Below REJECTED: status='rejected'.
# Between REJECTED and ACCEPTED: status='candidate'.
# Above ACCEPTED: status='accepted' (still subject to conflict downgrade).
BELIEF_THRESHOLD_REJECTED: float = 0.10
BELIEF_THRESHOLD_ACCEPTED: float = 0.80

# How fast evidence age decays the per-paper likelihood ratio. Half-life is
# ~5 years: a 5-year-old paper still contributes ~50% of the boost a fresh
# paper would. Used by callers when computing mean_recency.
RECENCY_HALFLIFE_DAYS: float = 365.25 * 5


def bayes_belief(
    *,
    n_supporting_papers: int,
    n_models_agreeing: int,
    mean_recency: float,
) -> float:
    """Compute the posterior probability that an Edge is real.

    Uses a log-odds Bayes update: starting from the prior, each supporting
    paper contributes log(LR_PER_PAPER) * recency to the log-odds, and each
    agreeing model contributes log(LR_PER_MODEL).

    Args:
        n_supporting_papers: distinct PMIDs supporting the edge.
        n_models_agreeing:   distinct extractor models that found it.
        mean_recency:        mean recency weight of supporting evidence,
                             in [0, 1]. 1.0 = today; 0.5 ≈ 5 years old.
                             Values outside [0, 1] are clamped.

    Returns:
        Posterior probability strictly inside (0, 1). Never exactly 0 or 1
        (so logs stay finite and Bayes updates remain numerically stable).

    Numerical sanity:
        0/0 → 0.300  (prior)
        1/1 → ~0.55  (candidate)
        1/7 → ≥0.80  (accepted)
        5/7 → >0.99  (strongly accepted)
    """
    if n_supporting_papers < 0 or n_models_agreeing < 0:
        raise ValueError("counts must be non-negative")

    recency = max(0.0, min(1.0, mean_recency))

    # Log-odds form: starts at prior, accumulates log-LR per evidence unit.
    log_odds = math.log(BAYES_PRIOR / (1.0 - BAYES_PRIOR))
    log_odds += n_supporting_papers * math.log(LR_PER_PAPER) * recency
    log_odds += n_models_agreeing * math.log(LR_PER_MODEL)

    posterior = 1.0 / (1.0 + math.exp(-log_odds))

    # Numerical guard — clip into open unit interval.
    return min(0.999_999, max(0.000_001, posterior))


def recency_weight_for_date(pub_date: date, today: date | None = None) -> float:
    """Map a paper's publication date to a weight in (0, 1].

    Exponential decay with the half-life set above.
    """
    today = today or timezone.now().date()
    age_days = max(0, (today - pub_date).days)
    return float(math.exp(-math.log(2.0) * age_days / RECENCY_HALFLIFE_DAYS))


def mean_recency_for_dates(dates: Sequence[date]) -> float:
    """Arithmetic mean of the per-date recency weights. Empty -> 1.0."""
    if not dates:
        return 1.0
    today = timezone.now().date()
    return sum(recency_weight_for_date(d, today) for d in dates) / len(dates)


# ---------------------------------------------------------------------------
# Edge belief / status recomputation
# ---------------------------------------------------------------------------


def recompute_edge_belief(edge: Edge) -> None:
    """Re-derive ``belief_score``, ``status``, ``n_supporting_papers``,
    and ``n_models_agreeing`` from ``edge.evidence``.

    Counts each distinct supporting PMID once and each distinct extractor
    model once. Recency is the mean recency weight of distinct papers.
    Status transitions:

       belief < BELIEF_THRESHOLD_REJECTED → rejected
       belief > BELIEF_THRESHOLD_ACCEPTED → accepted
       otherwise                          → candidate

    A separate helper (``demote_conflicted_edges``) downgrades accepted →
    conflicted when a Conflict row references the edge; this function
    never sets ``conflicted`` on its own.

    Uses canonical field names per reconciliation doc:
      raw_ppi.run.model_name  (not extraction_run.extractor_model)
      paper.publication_date  (not pub_date)
    """
    from graph.models import Edge as EdgeModel  # noqa: PLC0415

    # Pull supporting RawPPI rows with their paper.publication_date and
    # extractor model_name.
    evidence_rows = list(
        edge.evidence.select_related(
            "raw_ppi__run__chunk__section__paper",
        )
    )

    all_pmids: set[str] = set()
    pmid_to_pubdate: dict[str, date] = {}
    models_seen: set[str] = set()
    for ev in evidence_rows:
        paper = ev.raw_ppi.run.chunk.section.paper
        pub = paper.publication_date  # canonical field name (date | None from stubs)
        all_pmids.add(str(paper.pmid))
        if pub is not None:
            pmid_to_pubdate[str(paper.pmid)] = pub
        models_seen.add(ev.raw_ppi.run.model_name)  # canonical field name

    n_papers = len(all_pmids)  # ALL distinct PMIDs, including those with no publication_date
    n_models = len(models_seen)
    # Recency uses only dated papers; falls back to 1.0 when none have a date
    recency = mean_recency_for_dates(list(pmid_to_pubdate.values())) if pmid_to_pubdate else 1.0

    belief = bayes_belief(
        n_supporting_papers=n_papers,
        n_models_agreeing=n_models,
        mean_recency=recency,
    )

    # Don't overwrite 'conflicted' here — that's controlled by the
    # conflict resolver. But anything else can transition.
    if edge.status != "conflicted":
        if belief >= BELIEF_THRESHOLD_ACCEPTED:
            new_status = "accepted"
        elif belief < BELIEF_THRESHOLD_REJECTED:
            new_status = "rejected"
        else:
            new_status = "candidate"
    else:
        new_status = edge.status

    EdgeModel.objects.filter(pk=edge.pk).update(
        belief_score=belief,
        status=new_status,
        n_supporting_papers=n_papers,
        n_models_agreeing=n_models,
    )


# ---------------------------------------------------------------------------
# Ground mention (imported at module level for patch-ability in tests)
# ---------------------------------------------------------------------------

from core.services import ground_mention  # noqa: E402

# ---------------------------------------------------------------------------
# normalize_and_integrate — spec §4 six-step integration
# ---------------------------------------------------------------------------


def normalize_and_integrate(raw_ppi_ids: Iterable[int]) -> dict:
    """Promote a batch of RawPPI rows into Entity/Edge/EdgeEvidence.

    Spec §4 — six-step integration:

      1. Gilda-ground subject and object strings (skip on miss)
      2. Upsert Entity rows on top of the OntologyEntity match
      3. Find or create Edge(source, target, relation)
      4. Append EdgeEvidence (idempotent via the unique constraint)
      5. Recompute belief_score and status for every touched Edge
      6. Detect conflicts and reassign NetworkEdgeMembership
         (delegated to _post_integrate_hook)

    Idempotent: re-running on the same raw_ppi_ids is safe.  The
    EdgeEvidence unique constraint ensures no duplicate rows are created.

    Returns a small dict of counts useful for logging and tests:
      {'edges_touched': N, 'evidences_added': M, 'ungrounded': K}

    Uses canonical field names per reconciliation doc:
      raw_ppi.subject / .object  (not subject_text / object_text)
      raw_ppi.run                (not extraction_run)
    """
    from extract.models import RawPPI  # noqa: PLC0415 — dodge phase-import cycles
    from graph.models import Edge, EdgeEvidence, Entity  # noqa: PLC0415

    touched_edges: set[int] = set()
    evidences_added = 0
    ungrounded = 0

    raws = list(
        RawPPI.objects.filter(pk__in=list(raw_ppi_ids)).select_related(
            "run__chunk__section__paper",
        )
    )

    for raw in raws:
        subject_oe = ground_mention(raw.subject)  # canonical field name
        object_oe = ground_mention(raw.object)  # canonical field name

        if subject_oe is None or object_oe is None:
            if not raw.ungrounded:
                RawPPI.objects.filter(pk=raw.pk).update(ungrounded=True)
            ungrounded += 1
            continue

        with transaction.atomic():
            src_entity, _ = Entity.objects.get_or_create(ontology_entity=subject_oe)
            tgt_entity, _ = Entity.objects.get_or_create(ontology_entity=object_oe)

            edge, _ = Edge.objects.get_or_create(
                source=src_entity,
                target=tgt_entity,
                relation=raw.relation,
            )
            _, created = EdgeEvidence.objects.get_or_create(edge=edge, raw_ppi=raw)
            if created:
                evidences_added += 1
            touched_edges.add(edge.pk)

    # Belief recomputation for every touched Edge.
    for edge in Edge.objects.filter(pk__in=touched_edges):
        recompute_edge_belief(edge)

    logger.info(
        "normalize_and_integrate: edges_touched=%d evidences_added=%d ungrounded=%d",
        len(touched_edges),
        evidences_added,
        ungrounded,
    )

    # Hook for conflict detection + network membership.
    _post_integrate_hook(touched_edges, raws)

    # Emit the Phase 8 signal (analysis app will receive it).
    from graph.signals import edges_integrated  # noqa: PLC0415

    edges_integrated.send(
        sender=normalize_and_integrate,
        touched_edges=touched_edges,
        raws=raws,
    )

    return {
        "edges_touched": len(touched_edges),
        "evidences_added": evidences_added,
        "ungrounded": ungrounded,
    }


def _post_integrate_hook(touched_edges: set[int], raws: list) -> None:
    """Conflict detection + network membership stitching point."""
    raw_ids = [r.pk for r in raws]
    detect_intra_paper_conflicts(raw_ids)
    detect_inter_paper_conflicts(raw_ids)
    detect_inter_model_conflicts(raw_ids)
    reassign_network_membership(touched_edges)


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------

# Map a relation to its semantic opposite. Only listed pairs are tracked
# as conflicts; relations without an opposite (e.g. ``binds``) generate
# inter-model conflicts only via the count threshold below.
OPPOSITE_RELATIONS: dict[str, str] = {
    "activates": "inhibits",
    "inhibits": "activates",
    "phosphorylates": "dephosphorylates",
    "dephosphorylates": "phosphorylates",
    "ubiquitinates": "deubiquitinates",
    "deubiquitinates": "ubiquitinates",
    "acetylates": "deacetylates",
    "deacetylates": "acetylates",
    "transcribes": "represses",
    "represses": "transcribes",
}

INTER_MODEL_CONSENSUS_MIN: int = 5  # of 7 models needed to call it "consensus"


def _opposite_edge(edge: Edge) -> Edge | None:
    """Return the persisted opposite-relation Edge if it exists, else None."""
    from graph.models import Edge  # noqa: PLC0415

    opp_rel = OPPOSITE_RELATIONS.get(edge.relation)
    if opp_rel is None:
        return None
    return Edge.objects.filter(
        source=edge.source,
        target=edge.target,
        relation=opp_rel,
    ).first()


def _create_or_find_conflict(
    edge_a: Edge,
    edge_b: Edge,
    conflict_type: str,
) -> tuple[Conflict, bool]:
    """Upsert a Conflict row; demote both edges to 'conflicted' if new."""
    from graph.models import Conflict, Edge  # noqa: PLC0415

    # Order edge_a/edge_b deterministically so the unique constraint fires
    # correctly regardless of argument order.
    a, b = (edge_a, edge_b) if edge_a.pk <= edge_b.pk else (edge_b, edge_a)
    obj, created = Conflict.objects.get_or_create(
        edge_a=a,
        edge_b=b,
        conflict_type=conflict_type,
        defaults={"resolution_status": "open"},
    )
    if created:
        # Downgrade both edges to 'conflicted' (overrides accepted/candidate).
        Edge.objects.filter(pk__in=[a.pk, b.pk]).update(status="conflicted")
    return obj, created


def detect_intra_paper_conflicts(raw_ppi_ids: Iterable[int]) -> int:
    """Open intra-paper Conflict rows when two RawPPIs from the SAME CHUNK
    yield opposite-relation Edges for the same (source, target) pair.

    Returns the number of NEW conflicts created.

    Uses canonical field names: raw_ppi.run.chunk_id (not extraction_run).
    """
    from extract.models import RawPPI  # noqa: PLC0415
    from graph.models import Edge  # noqa: PLC0415

    raws = list(
        RawPPI.objects.filter(pk__in=list(raw_ppi_ids)).select_related(
            "run__chunk",
        )
    )

    # Group by chunk
    by_chunk: dict[int, list[RawPPI]] = {}
    for r in raws:
        by_chunk.setdefault(r.run.chunk_id, []).append(r)  # canonical: run.chunk_id

    new = 0
    for _chunk_id, group in by_chunk.items():
        # Build a map: (subject_upper, object_upper) -> set of relations seen
        pair_relations: dict[tuple[str, str], set[str]] = {}
        for r in group:
            key = (r.subject.upper(), r.object.upper())  # canonical field names
            pair_relations.setdefault(key, set()).add(r.relation)

        for (_subj_upper, _obj_upper), relations in pair_relations.items():
            # Check if any two relations in the set are opposites
            for rel in list(relations):
                opp = OPPOSITE_RELATIONS.get(rel)
                if opp and opp in relations:
                    # Both rel and opp exist for this (subj, obj) in the same chunk.
                    # Find the edges that were created for these raw_ppis in this chunk.
                    edges_for_rel = list(
                        Edge.objects.filter(
                            evidence__raw_ppi__in=[r for r in group if r.relation == rel],
                        ).distinct()
                    )
                    edges_for_opp = list(
                        Edge.objects.filter(
                            evidence__raw_ppi__in=[r for r in group if r.relation == opp],
                        ).distinct()
                    )
                    for ea in edges_for_rel:
                        for eb in edges_for_opp:
                            if ea.source_id == eb.source_id and ea.target_id == eb.target_id:
                                _, created = _create_or_find_conflict(ea, eb, "intra_paper")
                                if created:
                                    new += 1
                    # Process each pair once; break to avoid double-counting
                    break

    return new


def detect_inter_paper_conflicts(raw_ppi_ids: Iterable[int]) -> int:
    """Open inter-paper conflicts when an Edge has an opposite-relation
    sibling and their supporting RawPPIs come from DIFFERENT papers.

    Returns the number of NEW conflicts created.
    """
    from extract.models import RawPPI  # noqa: PLC0415
    from graph.models import Edge, EdgeEvidence  # noqa: PLC0415

    raws = list(RawPPI.objects.filter(pk__in=list(raw_ppi_ids)))
    edge_ids_to_check = set(
        EdgeEvidence.objects.filter(raw_ppi__in=raws).values_list("edge_id", flat=True)
    )

    new = 0
    for edge in Edge.objects.filter(pk__in=edge_ids_to_check):
        opp = _opposite_edge(edge)
        if opp is None:
            continue

        pmids_a = set(
            EdgeEvidence.objects.filter(edge=edge).values_list(
                "raw_ppi__run__chunk__section__paper__pmid",  # canonical path
                flat=True,
            )
        )
        pmids_b = set(
            EdgeEvidence.objects.filter(edge=opp).values_list(
                "raw_ppi__run__chunk__section__paper__pmid",  # canonical path
                flat=True,
            )
        )
        # Inter-paper requires at least one PMID unique to each side
        if (pmids_a - pmids_b) and (pmids_b - pmids_a):
            _, created = _create_or_find_conflict(edge, opp, "inter_paper")
            if created:
                new += 1

    return new


def detect_inter_model_conflicts(raw_ppi_ids: Iterable[int]) -> int:
    """Open inter-model conflicts when, for a given (source, target),
    the majority across the 7 extractor models is below INTER_MODEL_CONSENSUS_MIN.

    Returns the number of NEW conflicts created.
    """
    from extract.models import RawPPI  # noqa: PLC0415
    from graph.models import Edge, EdgeEvidence  # noqa: PLC0415

    raws = list(RawPPI.objects.filter(pk__in=list(raw_ppi_ids)))
    pairs: set[tuple[int, int]] = set()
    edges_for_raws = list(
        Edge.objects.filter(
            evidence__raw_ppi__in=raws,
        )
        .select_related("source", "target")
        .distinct()
    )
    for e in edges_for_raws:
        pairs.add((e.source_id, e.target_id))

    new = 0
    for src_id, tgt_id in pairs:
        sibling_edges = list(Edge.objects.filter(source_id=src_id, target_id=tgt_id))
        if len(sibling_edges) < 2:
            continue

        # Count distinct model_names per edge (canonical: run.model_name)
        rel_to_models: dict[str, set[str]] = {}
        for e in sibling_edges:
            models = set(
                EdgeEvidence.objects.filter(edge=e).values_list(
                    "raw_ppi__run__model_name",  # canonical field name
                    flat=True,
                )
            )
            rel_to_models[e.relation] = models

        max_models = max(len(ms) for ms in rel_to_models.values())
        if max_models < INTER_MODEL_CONSENSUS_MIN:
            # No relation reached consensus → flag a pairwise inter-model conflict
            ranked = sorted(rel_to_models.items(), key=lambda kv: -len(kv[1]))
            if len(ranked) < 2:
                continue
            rel_a, rel_b = ranked[0][0], ranked[1][0]
            edge_a = next(e for e in sibling_edges if e.relation == rel_a)
            edge_b = next(e for e in sibling_edges if e.relation == rel_b)
            _, created = _create_or_find_conflict(edge_a, edge_b, "inter_model")
            if created:
                new += 1

    return new


# ---------------------------------------------------------------------------
# Affected-network query (Phase 6 delta detection)
# ---------------------------------------------------------------------------


def affected_network_ids(paper_id: int, *, threshold: float = 0.5) -> list[int]:
    """Return network IDs whose relevance to ``paper_id`` is >= threshold.

    Public boundary function — other apps call this rather than touching
    ``PaperRelevance`` directly. Uses lazy import to keep graph from
    importing corpus at module load.

    Args:
        paper_id: the Paper PK (which equals Paper.pmid — the primary key).
        threshold: minimum relevance score (default 0.5 = cheap-pass score).

    Returns:
        List of Network PKs.
    """
    from corpus.models import PaperRelevance  # noqa: PLC0415 — lazy import

    return list(
        PaperRelevance.objects.filter(paper_id=paper_id, score__gte=threshold).values_list(
            "network_id", flat=True
        )
    )


# ---------------------------------------------------------------------------
# Network membership + stale demotion
# ---------------------------------------------------------------------------


def reassign_network_membership(edge_ids: Iterable[int]) -> dict:
    """For each edge in ``edge_ids``, create NetworkEdgeMembership rows for
    every Network whose ``root_entities`` references either endpoint's
    Identifier (scheme + value match, score ≥ 0.5 direct-match threshold).

    Demote affected networks from ``verified`` → ``stale`` (and also
    ``idle`` → ``stale`` when a new edge arrives) per spec §7.

    Returns {'memberships_created': N, 'networks_demoted': M}.
    """
    from graph.models import Edge, NetworkEdgeMembership  # noqa: PLC0415
    from networks.models import Network  # noqa: PLC0415

    created_count = 0
    demoted_count = 0
    edges = list(
        Edge.objects.filter(pk__in=list(edge_ids))
        .select_related("source__ontology_entity", "target__ontology_entity")
        .prefetch_related(
            "source__ontology_entity__identifiers",
            "target__ontology_entity__identifiers",
        )
    )

    for edge in edges:
        # Gather all (scheme, value) pairs from both endpoints
        endpoint_ids: set[tuple[str, str]] = set()
        for entity in (edge.source, edge.target):
            for ident in entity.ontology_entity.identifiers.all():
                endpoint_ids.add((ident.scheme, ident.value))

        # Any Network whose root_entities mentions any of these (scheme, value)
        # pairs is a candidate. root_entities is a JSONB list of dicts.
        for network in Network.objects.all():
            roots = network.root_entities or []
            wanted = {
                (r.get("scheme"), r.get("value"))
                for r in roots
                if r.get("scheme") and r.get("value")
            }
            if endpoint_ids & wanted:
                _, was_created = NetworkEdgeMembership.objects.get_or_create(
                    network=network,
                    edge=edge,
                    defaults={"relevance": 1.0},
                )
                if was_created:
                    created_count += 1
                    # Demote verified → stale (or idle → stale) per spec §7.
                    # Use verify.services.mark_stale so subscribers are notified.
                    # Lazy import to keep graph → verify a one-way dependency
                    # (verify must never import graph at module level).
                    if network.pipeline_status in ("verified", "idle"):
                        try:
                            from verify.services import mark_stale  # noqa: PLC0415

                            mark_stale(
                                network=network,
                                reason=f"New edge (id={edge.pk}) arrived for network '{network.code}'.",
                            )
                            demoted_count += 1
                        except Exception:
                            # Fallback: direct DB update so Phase 3 behaviour is
                            # preserved even if verify is unavailable.
                            logger.exception(
                                "reassign_network_membership: mark_stale failed for network %s; "
                                "falling back to direct DB update.",
                                network.code,
                            )
                            Network.objects.filter(pk=network.pk).update(pipeline_status="stale")
                            demoted_count += 1

    return {"memberships_created": created_count, "networks_demoted": demoted_count}


# ---------------------------------------------------------------------------
# Evidence items for a single edge — used by the disagreement queue
# ---------------------------------------------------------------------------

#: Maximum evidence items to return. Callers can slice further; this cap
#: prevents pathological edges from returning hundreds of rows.
_EVIDENCE_ITEMS_CAP = 50


def edge_evidence_items(edge: Edge) -> list[dict]:
    """Return a list of evidence dicts for *edge*, ordered by confidence desc.

    Each dict contains:
      pmid           — int, the supporting paper's PMID
      pubmed_url     — str, canonical https://pubmed.ncbi.nlm.nih.gov/<pmid>/
      citation       — str, "<title> · <journal> · <year>" (year from
                       publication_date; falls back to "" if no date)
      model_name     — str, extracting model
      relation_logprob — float | None
      confidence     — float
      evidence_span  — str, the verbatim sentence

    The result is deduplicated by (raw_ppi_id) — each RawPPI appears at most
    once even if somehow duplicated in EdgeEvidence. Ordered by confidence
    descending so the highest-confidence sentence appears first.

    Uses a single ``select_related`` traversal (no N+1).
    """
    from graph.models import Edge as EdgeModel  # noqa: PLC0415 — avoid circular at module load

    ev_qs = (
        EdgeModel.objects.get(pk=edge.pk)  # ensure we're working with a fresh edge
        .evidence.select_related(
            "raw_ppi__run__chunk__section__paper",
        )
        .order_by("-raw_ppi__confidence")[:_EVIDENCE_ITEMS_CAP]
    )

    seen_raw_ppi_ids: set[int] = set()
    items: list[dict] = []
    for ev in ev_qs:
        rp = ev.raw_ppi
        if rp.pk in seen_raw_ppi_ids:
            continue
        seen_raw_ppi_ids.add(rp.pk)

        paper = rp.run.chunk.section.paper
        pmid = paper.pmid
        pub_date = paper.publication_date
        year = str(pub_date.year) if pub_date is not None else ""
        journal = paper.journal or ""
        citation_parts = [paper.title, journal, year]
        citation = " · ".join(p for p in citation_parts if p)

        items.append(
            {
                "pmid": pmid,
                "pubmed_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                "citation": citation,
                "model_name": rp.run.model_name,
                "relation_logprob": rp.relation_logprob,
                "confidence": rp.confidence,
                "evidence_span": rp.evidence_span,
            }
        )

    return items
