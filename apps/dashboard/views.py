"""Dashboard views — read-only stats and paper detail."""

from __future__ import annotations

from collections import Counter
from typing import Any

from django.core.cache import cache
from django.db.models import Count, Q
from django.db.models.functions import ExtractYear
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from corpus.models import Paper

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
