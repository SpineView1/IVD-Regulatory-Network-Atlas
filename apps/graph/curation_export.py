"""Biologist-facing curation CSV — one network, the columns reviewers expect.

Columns (fixed, per the lab's curation sheet):

    STIMULI | RELATION | RESPONSE | PATHWAY INVOLVED | TYPE OF CELLS
          | DEG/NON-DEG | COMMENTS | REFERENCE

STIMULI/RESPONSE are the upstream/downstream molecules of the edge
(``edge.source`` → ``edge.target``); the experimental stimulus, belief, and
extracting models go in COMMENTS. One row per (edge, supporting paper): a
biologist curates per-finding, so each PMID that reports the interaction gets
its own row with the cell/species/degeneration context that paper described.
``species`` is folded into TYPE OF CELLS (e.g. "human · nucleus pulposus").
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from networks.models import Network

CURATION_CSV_COLUMNS = [
    "STIMULI",
    "RELATION",
    "RESPONSE",
    "PATHWAY INVOLVED",
    "TYPE OF CELLS",
    "DEG/NON-DEG",
    "COMMENTS",
    "REFERENCE",
]


@dataclass
class _PaperAggregate:
    """Curation facts gathered from one paper's RawPPIs supporting an edge."""

    cells: set[str] = field(default_factory=set)
    deg: set[str] = field(default_factory=set)
    stimuli: set[str] = field(default_factory=set)
    models: set[str] = field(default_factory=set)
    confidences: list[float] = field(default_factory=list)


def _type_of_cells(species: str, cell_type: str) -> str:
    """Combine species + cell type into one human-readable cell descriptor."""
    parts = [p for p in (species.strip(), cell_type.strip()) if p]
    return " · ".join(parts)


def network_curation_rows(network: Network) -> list[dict[str, str]]:
    """Build the curation rows for one ``Network``.

    One row per (concrete edge, supporting PMID); identical rows are
    de-duplicated. Edges are ordered by belief (most-supported first).
    """
    from graph.models import EdgeEvidence, NetworkEdgeMembership

    memberships = (
        NetworkEdgeMembership.objects.filter(network=network, edge__isnull=False)
        .select_related(
            "edge__source__ontology_entity",
            "edge__target__ontology_entity",
        )
        .order_by("-edge__belief_score")
    )

    rows: list[dict[str, str]] = []
    seen: set[tuple[str, ...]] = set()

    for m in memberships:
        edge = m.edge
        if edge is None:  # pending-only membership: no concrete edge yet
            continue

        evidence = EdgeEvidence.objects.filter(edge=edge).select_related(
            "raw_ppi__run",
            "raw_ppi__run__chunk__section__paper",
        )

        # Group the edge's evidence by the paper that reported it.
        per_pmid: dict[int, _PaperAggregate] = {}
        for ev in evidence:
            rp = ev.raw_ppi
            pmid = rp.run.chunk.section.paper.pmid
            agg = per_pmid.setdefault(pmid, _PaperAggregate())
            cell = _type_of_cells(rp.species or "", rp.cell_type or "")
            if cell:
                agg.cells.add(cell)
            if rp.deg_status:
                agg.deg.add(rp.deg_status)
            if rp.stimulus:
                agg.stimuli.add(rp.stimulus.strip())
            agg.models.add(rp.run.model_name)
            agg.confidences.append(rp.confidence)

        for pmid, agg in per_pmid.items():
            stim = "; ".join(sorted(agg.stimuli))
            comments = []
            if stim:
                comments.append(f"stimulus: {stim}")
            comments.append(f"belief {edge.belief_score:.2f}")
            comments.append(f"models: {', '.join(sorted(agg.models))}")
            if agg.confidences:
                comments.append(f"max confidence {max(agg.confidences):.2f}")
            if edge.status != "accepted":
                comments.append(f"status: {edge.status}")

            row = {
                "STIMULI": edge.source.symbol,
                "RELATION": edge.relation,
                "RESPONSE": edge.target.symbol,
                "PATHWAY INVOLVED": network.title,
                "TYPE OF CELLS": "; ".join(sorted(agg.cells)),
                "DEG/NON-DEG": "; ".join(sorted(agg.deg)),
                "COMMENTS": "; ".join(comments),
                "REFERENCE": f"PMID:{pmid}",
            }
            key = tuple(row[c] for c in CURATION_CSV_COLUMNS)
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)

    return rows


def write_network_curation_csv(network: Network) -> bytes:
    """Render the curation CSV for one network as UTF-8 bytes."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CURATION_CSV_COLUMNS, lineterminator="\n")
    writer.writeheader()
    for row in network_curation_rows(network):
        writer.writerow(row)
    return buf.getvalue().encode("utf-8")
