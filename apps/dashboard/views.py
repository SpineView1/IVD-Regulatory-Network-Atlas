"""Dashboard views — read-only stats, paper detail, grid, network detail, queue."""

from __future__ import annotations

from collections import Counter
from typing import Any

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

    # Build per-network edge count and open conflict count annotations
    edge_counts: dict[int, int] = {
        row["network_id"]: row["cnt"]
        for row in NetworkEdgeMembership.objects.values("network_id").annotate(cnt=Count("id"))
    }
    open_conflict_counts: dict[int, int] = {}
    for n in networks:
        edge_ids = n.edge_memberships.values_list("edge_id", flat=True)
        open_conflict_counts[n.pk] = Conflict.objects.filter(
            Q(edge_a_id__in=edge_ids) | Q(edge_b_id__in=edge_ids),
            resolution_status="open",
        ).count()

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
    """Per-network detail: Cytoscape.js graph + ModelVersion panel."""
    from networks.models import Network
    from sbml.models import ModelVersion

    network = get_object_or_404(Network, code=code)
    versions = list(
        ModelVersion.objects.filter(network=network)
        .filter(frozen_at__isnull=False)
        .order_by("-created_at")
    )
    edges_json_url = f"/graph/dev/networks/{code}/edges.json"
    context: dict[str, Any] = {
        "network": network,
        "versions": versions,
        "edges_json_url": edges_json_url,
    }
    return render(request, "dashboard/network_detail.html", context)


# ---------------------------------------------------------------------------
# Task 11: Disagreement queue
# ---------------------------------------------------------------------------


def disagreement_queue(request: HttpRequest, code: str) -> HttpResponse:
    """List open Conflicts for a network with an HTMX resolution form."""
    from graph.models import Conflict, NetworkEdgeMembership
    from networks.models import Network

    network = get_object_or_404(Network, code=code)
    edge_ids = NetworkEdgeMembership.objects.filter(network=network).values_list(
        "edge_id", flat=True
    )
    conflicts = list(
        Conflict.objects.filter(
            Q(edge_a_id__in=edge_ids) | Q(edge_b_id__in=edge_ids),
            resolution_status="open",
        )
        .select_related("edge_a__source", "edge_a__target", "edge_b__source", "edge_b__target")
        .order_by("created_at")
    )
    context: dict[str, Any] = {
        "network": network,
        "conflicts": conflicts,
    }
    return render(request, "dashboard/disagreement_queue.html", context)


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
