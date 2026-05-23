"""CSV exporters per spec §7.

Two files per ModelVersion:

- ``edges.csv``    — one row per accepted Edge in the network
- ``evidence.csv`` — one row per EdgeEvidence row (one Edge can have many)

Both functions return ``bytes`` (UTF-8 encoded). The packaging step
writes them straight into the ZIP without touching disk.

Real field names (per cross-plan reconciliation):
- edge.relation  (NOT relation_type)
- raw_ppi.run.model_name  (extractor model, NOT extraction_run.model_name)
- raw_ppi.run.chunk.section.paper.pmid  (chain via run, NOT raw_ppi.chunk)
- raw_ppi.evidence_offset_start/end  (NOT evidence_span_start/end)
- raw_ppi.relation_logprob  (NOT logprob)
"""

from __future__ import annotations

import csv
import io
import logging
from collections.abc import Iterable
from typing import Any

log = logging.getLogger(__name__)

EDGES_CSV_COLUMNS = [
    "source_symbol",
    "source_id",
    "source_type",
    "relation",
    "target_symbol",
    "target_id",
    "target_type",
    "belief",
    "n_supporting_papers",
    "n_models_agreeing",
    "reviewer_status",
    "first_seen",
    "last_seen",
]

EVIDENCE_CSV_COLUMNS = [
    "edge_id",
    "pmid",
    "chunk_excerpt",
    "evidence_span_start",
    "evidence_span_end",
    "extractor_model",
    "extraction_logprob",
    "extracted_at",
]


def write_edges_csv(edges: Iterable) -> bytes:
    """Write edges.csv — one row per accepted Edge."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=EDGES_CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for e in edges:
        writer.writerow(
            {
                "source_symbol": e.source.symbol,
                "source_id": e.source.canonical_uri,
                "source_type": e.source.ontology_entity.entity_type,
                "relation": e.relation,  # real field name
                "target_symbol": e.target.symbol,
                "target_id": e.target.canonical_uri,
                "target_type": e.target.ontology_entity.entity_type,
                "belief": f"{e.belief_score:.4f}",
                "n_supporting_papers": e.n_supporting_papers,
                "n_models_agreeing": e.n_models_agreeing,
                "reviewer_status": _reviewer_status(e),
                "first_seen": e.created_at.isoformat(),
                "last_seen": e.updated_at.isoformat(),
            }
        )
    return buf.getvalue().encode("utf-8")


def write_evidence_csv(edges: Iterable) -> bytes:
    """Write evidence.csv — one row per EdgeEvidence (many per Edge)."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=EVIDENCE_CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for e in edges:
        # select_related chain: raw_ppi__run__chunk__section__paper
        for ev in e.evidence.select_related("raw_ppi__run__chunk__section__paper").all():
            rppi = ev.raw_ppi
            chunk = rppi.run.chunk
            # Excerpt: window around the evidence span
            start_w = max(0, rppi.evidence_offset_start - 20)
            end_w = rppi.evidence_offset_end + 20
            excerpt = chunk.text[start_w:end_w].replace("\n", " ").replace("\r", " ")
            logprob_val = (
                f"{rppi.relation_logprob:.4f}" if rppi.relation_logprob is not None else ""
            )
            writer.writerow(
                {
                    "edge_id": e.id,
                    "pmid": chunk.section.paper.pmid,
                    "chunk_excerpt": excerpt,
                    "evidence_span_start": rppi.evidence_offset_start,
                    "evidence_span_end": rppi.evidence_offset_end,
                    "extractor_model": rppi.run.model_name,
                    "extraction_logprob": logprob_val,
                    "extracted_at": rppi.created_at.isoformat(),
                }
            )
    return buf.getvalue().encode("utf-8")


def _reviewer_status(edge: Any) -> str:
    """Map edge.status + Review rows to the spec's reviewer_status column."""
    if edge.status == "conflicted":
        return "conflicted"
    if edge.status == "rejected":
        return "rejected"
    try:
        if edge.reviews.filter(action="approve").exists():
            return "approved"
    except Exception:  # noqa: BLE001
        log.debug("reviews not available for edge %s", edge.id)
    return "unreviewed"
