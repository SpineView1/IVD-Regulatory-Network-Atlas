"""Dashboard views — read-only stats and paper detail."""

from __future__ import annotations

from collections import Counter
from typing import Any

from django.db.models import Count
from django.db.models.functions import ExtractYear
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from corpus.models import Paper


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
    original_breakdown = {
        "original": Paper.objects.filter(is_original=True).count(),
        "review_or_secondary": Paper.objects.filter(is_original=False).count(),
        "unclassified": Paper.objects.filter(is_original__isnull=True).count(),
    }
    mesh_counter: Counter[str] = Counter()
    for terms in Paper.objects.values_list("mesh_terms", flat=True):
        if terms:
            mesh_counter.update(terms)
    top_mesh = mesh_counter.most_common(25)

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
