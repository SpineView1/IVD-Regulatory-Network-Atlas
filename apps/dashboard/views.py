"""Dashboard views — read-only stats, paper detail, grid, network detail, queue."""

from __future__ import annotations

from collections import Counter
from typing import Any

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db.models import Count, Q
from django.db.models.functions import ExtractYear
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from corpus.models import Paper
from graph.models import Edge

_TOP_MESH_CACHE_KEY = "dashboard:top_mesh"
_TOP_MESH_TTL = 3600  # seconds


def stats(request: HttpRequest) -> HttpResponse:
    total = Paper.objects.count()
    by_year = list(
        Paper.objects.exclude(publication_date__isnull=True)
        .annotate(year=ExtractYear("publication_date"))
        .values("year")
        .annotate(n=Count("pmid"))
        .order_by("-year")
    )
    by_journal = list(
        Paper.objects.exclude(journal="")
        .values("journal")
        .annotate(n=Count("pmid"))
        .order_by("-n")[:25]
    )
    fulltext_breakdown = list(Paper.objects.values("full_text_status").annotate(n=Count("pmid")))
    agg = Paper.objects.aggregate(
        original=Count("pmid", filter=Q(is_original=True)),
        review_or_secondary=Count("pmid", filter=Q(is_original=False)),
        unclassified=Count("pmid", filter=Q(is_original__isnull=True)),
    )
    original_breakdown = {
        "original": agg["original"],
        "review_or_secondary": agg["review_or_secondary"],
        "unclassified": agg["unclassified"],
    }
    top_mesh: list[tuple[str, int]] | None = cache.get(_TOP_MESH_CACHE_KEY)
    if top_mesh is None:
        mesh_counter: Counter[str] = Counter()
        for terms in Paper.objects.values_list("mesh_terms", flat=True):
            if terms:
                mesh_counter.update(terms)
        top_mesh = mesh_counter.most_common(25)
        cache.set(_TOP_MESH_CACHE_KEY, top_mesh, _TOP_MESH_TTL)

    context: dict[str, Any] = {
        "total": total,
        "by_year": by_year,
        "by_journal": by_journal,
        "fulltext_breakdown": fulltext_breakdown,
        "original_breakdown": original_breakdown,
        "top_mesh": top_mesh,
    }
    return render(request, "dashboard/stats.html", context)


def paper_detail(request: HttpRequest, pmid: int) -> HttpResponse:
    paper = get_object_or_404(Paper, pmid=pmid)
    relevances = list(paper.relevances.select_related("network").order_by("-score"))
    return render(
        request,
        "dashboard/paper_detail.html",
        {"paper": paper, "relevances": relevances},
    )


# ---------------------------------------------------------------------------
# Task 9: Top-level network grid
# ---------------------------------------------------------------------------

# The 17 category codes used in the taxonomy fixture (spec Appendix A)
_CATEGORY_LABELS: dict[str, str] = {
    "I": "Core Signaling Pathway Networks",
    "II": "Transcription Factor Networks",
    "III": "Epigenetic Regulatory Networks",
    "IV": "Non-Coding RNA Networks",
    "V": "ECM / Matrix Remodeling Networks",
    "VI": "Growth Factor / Cytokine Networks",
    "VII": "Metabolic Regulatory Networks",
    "VIII": "Mechanobiology Networks",
    "IX": "Cell Type-Specific Networks",
    "X": "Neurovascular Networks",
    "XI": "Cell Fate / Differentiation Networks",
    "XII": "Inter-Tissue / Systemic Crosstalk Networks",
    "XIII": "GWAS / Genetic Regulatory Networks",
    "XIV": "Disease-Specific Regulatory Networks",
    "XV": "Therapeutic / Regenerative Networks",
    "XVI": "Proteostasis / UPR Networks",
    "XVII": "Multi-Omics Integration Networks",
}


def grid(request: HttpRequest) -> HttpResponse:
    """Top-level network grid — 17 category sections, each listing networks."""
    from graph.models import Conflict, NetworkEdgeMembership
    from networks.models import Network

    networks = list(
        Network.objects.filter(is_active=True)
        .prefetch_related("edge_memberships")
        .order_by("category", "code")
    )

    # Build per-network edge count: one aggregation query.
    edge_counts: dict[int, int] = {
        row["network_id"]: row["cnt"]
        for row in NetworkEdgeMembership.objects.values("network_id").annotate(cnt=Count("id"))
    }

    # Build per-network open-conflict count in O(1) queries (no per-network loop).
    # Strategy:
    #   (a) Fetch network_id → set-of-edge-ids via NetworkEdgeMembership (one query).
    #   (b) Aggregate open Conflicts per edge_a / edge_b via two annotated querysets,
    #       then merge into a per-network dict (two queries total).
    _mem_qs = NetworkEdgeMembership.objects.values_list("network_id", "edge_id")
    _network_to_edges: dict[int, set[int]] = {}
    for nid, eid in _mem_qs:
        _network_to_edges.setdefault(nid, set()).add(eid)

    # All open conflicts touching any edge we know about.
    _all_edge_ids: set[int] = set()
    for eids in _network_to_edges.values():
        _all_edge_ids.update(eids)

    # Build edge_id → list[network_id] reverse index.
    _edge_to_networks: dict[int, list[int]] = {}
    for nid, eids in _network_to_edges.items():
        for eid in eids:
            _edge_to_networks.setdefault(eid, []).append(nid)

    # One query: fetch all open Conflict (edge_a_id, edge_b_id) pairs.
    _open_conflicts = list(
        Conflict.objects.filter(
            Q(edge_a_id__in=_all_edge_ids) | Q(edge_b_id__in=_all_edge_ids),
            resolution_status="open",
        ).values_list("id", "edge_a_id", "edge_b_id")
    )

    open_conflict_counts: dict[int, int] = {n.pk: 0 for n in networks}
    _counted: set[tuple[int, int]] = set()  # (conflict_id, network_id) to avoid double-counting
    for cid, ea_id, eb_id in _open_conflicts:
        touching_nets: set[int] = set()
        touching_nets.update(_edge_to_networks.get(ea_id, []))
        touching_nets.update(_edge_to_networks.get(eb_id, []))
        for nid in touching_nets:
            if (cid, nid) not in _counted and nid in open_conflict_counts:
                open_conflict_counts[nid] += 1
                _counted.add((cid, nid))

    # Group by category
    categories: list[dict[str, Any]] = []
    seen: set[str] = set()
    for cat_code in _CATEGORY_LABELS:
        cat_networks = [n for n in networks if n.category == cat_code]
        if cat_code not in seen:
            seen.add(cat_code)
            categories.append(
                {
                    "code": cat_code,
                    "label": _CATEGORY_LABELS.get(cat_code, cat_code),
                    "networks": cat_networks,
                }
            )

    # Also include any categories not in the fixed list
    extra_cats: dict[str, list[Any]] = {}
    for n in networks:
        if n.category not in _CATEGORY_LABELS:
            extra_cats.setdefault(n.category, []).append(n)
    for cat_code, cat_networks in sorted(extra_cats.items()):
        categories.append(
            {
                "code": cat_code,
                "label": cat_code,
                "networks": cat_networks,
            }
        )

    context: dict[str, Any] = {
        "categories": categories,
        "edge_counts": edge_counts,
        "open_conflict_counts": open_conflict_counts,
        "total_networks": len(networks),
    }
    return render(request, "dashboard/grid.html", context)


# ---------------------------------------------------------------------------
# Task 10: Per-network drill-down
# ---------------------------------------------------------------------------


def network_detail(request: HttpRequest, code: str) -> HttpResponse:
    """Per-network detail: Cytoscape.js graph + ModelVersion panel + a
    per-edge Evidence & References table so a biologist sees the source
    sentences and PMIDs without leaving the network page."""
    from graph.models import NetworkEdgeMembership
    from graph.services import edge_evidence_items
    from networks.models import Network
    from sbml.models import ModelVersion

    network = get_object_or_404(Network, code=code)
    versions = list(
        ModelVersion.objects.filter(network=network)
        .filter(frozen_at__isnull=False)
        .order_by("-created_at")
    )

    # Edges in this network, each with its supporting evidence (PMID, verbatim
    # sentence, model, confidence). edge_evidence_items fetches the full
    # evidence chain in one query per edge; prefetch keeps the node labels cheap.
    memberships = (
        NetworkEdgeMembership.objects.filter(network=network, edge__isnull=False)
        .select_related("edge__source__ontology_entity", "edge__target__ontology_entity")
        .order_by("-edge__belief_score")
    )
    edges_with_evidence = []
    for m in memberships:
        edge = m.edge
        if edge is None:  # pending-only membership (no concrete edge yet)
            continue
        items = edge_evidence_items(edge)
        edges_with_evidence.append(
            {
                "edge": edge,
                "source": edge.source.ontology_entity.preferred_label,
                "target": edge.target.ontology_entity.preferred_label,
                "evidence": items,
                "evidence_count": len(items),
            }
        )

    edges_json_url = f"/graph/dev/networks/{code}/edges.json"
    context: dict[str, Any] = {
        "network": network,
        "versions": versions,
        "edges_json_url": edges_json_url,
        "edges_with_evidence": edges_with_evidence,
    }
    return render(request, "dashboard/network_detail.html", context)


def network_curation_csv(request: HttpRequest, code: str) -> HttpResponse:
    """Download one network's interactions in the biologist curation format:
    STIMULI / RELATION / RESPONSE / PATHWAY INVOLVED / TYPE OF CELLS /
    DEG/NON-DEG / COMMENTS / REFERENCE — one row per (edge, supporting paper).
    """
    from django.utils.text import slugify  # noqa: PLC0415

    from graph.curation_export import write_network_curation_csv  # noqa: PLC0415
    from networks.models import Network  # noqa: PLC0415

    network = get_object_or_404(Network, code=code)
    payload = write_network_curation_csv(network)
    filename = f"{slugify(network.code)}-curation.csv"
    response = HttpResponse(payload, content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


# ---------------------------------------------------------------------------
# Task 11: Disagreement queue
# ---------------------------------------------------------------------------


def disagreement_queue(request: HttpRequest, code: str) -> HttpResponse:
    """List open Conflicts for a network with an HTMX resolution form.

    Evidence chain is prefetched for edge_a and edge_b of every conflict so
    the conflict_card template can render supporting sentences + references
    with a bounded number of queries (no N+1 across conflicts or evidence).
    """
    from django.db.models import Prefetch  # noqa: PLC0415

    from graph.models import Conflict, EdgeEvidence, NetworkEdgeMembership  # noqa: PLC0415
    from networks.models import Network  # noqa: PLC0415

    network = get_object_or_404(Network, code=code)
    edge_ids = NetworkEdgeMembership.objects.filter(network=network).values_list(
        "edge_id", flat=True
    )

    # Prefetch the full evidence chain for both edges so the template render
    # is O(fixed) queries rather than O(conflicts * 2).
    _evidence_qs = EdgeEvidence.objects.select_related(
        "raw_ppi__run__chunk__section__paper",
    ).order_by("-raw_ppi__confidence")

    # Two Prefetches with different to_attr names avoid mypy's [no-redef] error
    # that fires when both prefetches use the same attribute name.
    conflicts = list(
        Conflict.objects.filter(
            Q(edge_a_id__in=edge_ids) | Q(edge_b_id__in=edge_ids),
            resolution_status="open",
        )
        .select_related(
            "edge_a__source__ontology_entity",
            "edge_a__target__ontology_entity",
            "edge_b__source__ontology_entity",
            "edge_b__target__ontology_entity",
        )
        .prefetch_related(
            Prefetch(
                "edge_a__evidence",
                queryset=_evidence_qs,
                to_attr="edge_a_evidence_prefetched",
            ),
            Prefetch(
                "edge_b__evidence",
                queryset=_evidence_qs,
                to_attr="edge_b_evidence_prefetched",
            ),
        )
        .order_by("created_at")
    )

    # Build per-conflict evidence item lists from the prefetched data so we
    # do not hit the DB again in the template.
    _EVIDENCE_CAP = 5  # show first N sentences; template notes "+M more"
    conflict_evidence: dict[int, dict[str, Any]] = {}
    for conflict in conflicts:
        conflict_evidence[conflict.pk] = {
            "edge_a": _evidence_items_from_prefetch(
                conflict.edge_a.edge_a_evidence_prefetched,  # type: ignore[attr-defined]
                cap=_EVIDENCE_CAP,
            ),
            "edge_b": _evidence_items_from_prefetch(
                conflict.edge_b.edge_b_evidence_prefetched,  # type: ignore[attr-defined]
                cap=_EVIDENCE_CAP,
            ),
        }

    context: dict[str, Any] = {
        "network": network,
        "conflicts": conflicts,
        "conflict_evidence": conflict_evidence,
    }
    return render(request, "dashboard/disagreement_queue.html", context)


def _evidence_items_from_prefetch(
    evidence_prefetched: list,
    *,
    cap: int = 5,
) -> dict[str, Any]:
    """Convert a pre-fetched list of EdgeEvidence rows into a display dict.

    Returns:
      {
        "items": [list of evidence item dicts, capped at ``cap``],
        "total": int (total count before cap),
        "extra": int (total - len(items), i.e. how many are hidden),
      }
    """
    seen_raw_ppi_ids: set[int] = set()
    all_items: list[dict[str, Any]] = []
    for ev in evidence_prefetched:
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
        all_items.append(
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

    total = len(all_items)
    visible = all_items[:cap]
    return {
        "items": visible,
        "total": total,
        "extra": total - len(visible),
    }


# ---------------------------------------------------------------------------
# Task 12: Audit trail for a single edge
# ---------------------------------------------------------------------------


def audit_trail(request: HttpRequest, pk: int) -> HttpResponse:
    """Full provenance tree for a single edge + review history.

    Provenance chain traversed:
    Edge → EdgeEvidence → RawPPI → ExtractionRun → Chunk → Section → Paper
    Reviews fetched with select_related(reviewer) to avoid N+1.
    Evidence uses select_related/prefetch_related so all 6 joins happen in
    the minimum query count regardless of how many RawPPIs back the edge.
    """
    edge = get_object_or_404(
        Edge.objects.select_related(
            "source__ontology_entity",
            "target__ontology_entity",
        ),
        pk=pk,
    )

    # Traverse the provenance chain with a single compound select_related/
    # prefetch chain to avoid N+1 (spec requirement from reviewer).
    evidence_qs = edge.evidence.select_related(
        "raw_ppi__run__chunk__section__paper",
    ).order_by("raw_ppi__run__chunk__section__paper__pmid")

    reviews = list(edge.reviews.select_related("reviewer").order_by("created_at"))

    context: dict[str, Any] = {
        "edge": edge,
        "evidence_list": list(evidence_qs),
        "reviews": reviews,
    }
    return render(request, "dashboard/audit_trail.html", context)


# ---------------------------------------------------------------------------
# Task 13: Subscription manager
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Phase 6 Task 11: Health alerts panel (HTMX polled partial)
# ---------------------------------------------------------------------------


def health_alerts_panel(request: HttpRequest) -> HttpResponse:
    """Render the recent-open-alerts widget for the dashboard navbar.

    Polled every 30s by HTMX from the base template. Returns only
    unresolved HealthAlert rows, capped at 5 most recent.
    """
    from monitoring.models import HealthAlert  # noqa: PLC0415 — lazy import

    alerts = HealthAlert.objects.filter(resolved_at__isnull=True).order_by("-created_at")[:5]
    return render(
        request,
        "dashboard/partials/health_alerts.html",
        {"alerts": list(alerts)},
    )


@login_required
def subscriptions(request: HttpRequest) -> HttpResponse:
    """List all of the logged-in user's subscriptions with toggle controls."""
    from verify.models import Subscription as SubscriptionModel

    user_subs = list(
        SubscriptionModel.objects.filter(user=request.user)  # type: ignore[misc]
        .select_related("network")
        .order_by("created_at")
    )
    context: dict[str, Any] = {
        "subscriptions": user_subs,
    }
    return render(request, "dashboard/subscriptions.html", context)
