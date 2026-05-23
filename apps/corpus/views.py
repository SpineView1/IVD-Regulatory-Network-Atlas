"""corpus views — export.csv."""

from __future__ import annotations

import csv
import json

from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest

from corpus.models import Paper, PaperRelevance
from networks.models import Network


def export_csv(request: HttpRequest) -> HttpResponse:
    """Stream the corpus as CSV.

    Query params:
      - ``format=full`` — emit the wide column set including is_original,
        full_text_status, publication_types, mesh_terms, doi, pmcid.
      - ``network=<code>`` — restrict to papers with PaperRelevance for
        the named network above ``threshold``.
      - ``threshold=<float>`` — default 0.5 (per spec §5).
    """
    full = request.GET.get("format") == "full"
    network_code = request.GET.get("network", "").strip()
    try:
        threshold = float(request.GET.get("threshold", "0.5"))
    except ValueError:
        return HttpResponseBadRequest("threshold must be a float")

    if network_code:
        try:
            network = Network.objects.get(code=network_code)
        except Network.DoesNotExist:
            return HttpResponseBadRequest(f"unknown network code: {network_code}")
        pmids = PaperRelevance.objects.filter(network=network, score__gte=threshold).values_list(
            "paper_id", flat=True
        )
        qs = Paper.objects.filter(pmid__in=pmids).order_by("pmid")
        filename = f"corpus_{network_code}.csv"
    else:
        qs = Paper.objects.all().order_by("pmid")
        filename = "corpus_full.csv" if full else "corpus.csv"

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)
    writer.writerow(_csv_headers(full=full))
    for paper in qs.iterator(chunk_size=500):
        writer.writerow(_csv_row(paper, full=full))
    return response


def _csv_headers(*, full: bool) -> list[str]:
    base = ["pmid", "title", "journal", "publication_date", "entrez_date"]
    if not full:
        return base
    return base + [
        "doi",
        "pmcid",
        "is_original",
        "classification_confidence",
        "full_text_status",
        "publication_types",
        "mesh_terms",
        "ingest_status",
    ]


def _csv_row(paper: Paper, *, full: bool) -> list[object]:
    base: list[object] = [
        paper.pmid,
        paper.title,
        paper.journal,
        paper.publication_date.isoformat() if paper.publication_date else "",
        paper.entrez_date.isoformat() if paper.entrez_date else "",
    ]
    if not full:
        return base
    if paper.is_original is None:
        is_original_val: object = ""
    else:
        is_original_val = str(paper.is_original)
    if paper.classification_confidence is None:
        conf_val: object = ""
    else:
        conf_val = f"{paper.classification_confidence:.3f}"
    return base + [
        paper.doi,
        paper.pmcid,
        is_original_val,
        conf_val,
        paper.full_text_status,
        json.dumps(paper.publication_types or []),
        json.dumps(paper.mesh_terms or []),
        paper.ingest_status,
    ]
