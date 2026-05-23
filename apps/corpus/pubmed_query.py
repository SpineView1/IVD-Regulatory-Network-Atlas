"""The canonical IDD PubMed query string.

(per spec §5 — hybrid MeSH-anchored + free-text, weighted by date.
~30,000–40,000 historical hits, ~3,000–5,000 new papers/year.)
"""

from __future__ import annotations

from datetime import date, timedelta

MASTER_IDD_QUERY = (
    "("
    '"Intervertebral Disc"[MeSH] OR '
    '"Intervertebral Disc Degeneration"[MeSH] OR '
    '"Intervertebral Disc Displacement"[MeSH] OR '
    '"Nucleus Pulposus"[MeSH] OR '
    '"intervertebral disc"[TIAB] OR '
    '"intervertebral disk"[TIAB] OR '
    '"nucleus pulposus"[TIAB] OR '
    '"annulus fibrosus"[TIAB] OR '
    '"disc degeneration"[TIAB] OR '
    '"disc herniation"[TIAB] OR '
    '"cartilage endplate"[TIAB] OR '
    '"spinal disc"[TIAB]'
    ") "
    "AND English[Language] "
    'AND ("1980"[PDAT] : "3000"[PDAT])'
)


def build_incremental_query(*, since: date | None, overlap_days: int = 0) -> str:
    """Build a date-bounded variant for incremental refresh.

    ``since`` is the watermark's ``last_entrez_date``. The query subtracts
    ``overlap_days`` to catch late-indexed papers (per spec §5 watermark
    section: "7-day overlap to catch late-indexed papers").
    """
    if since is None:
        return MASTER_IDD_QUERY
    mindate = since - timedelta(days=overlap_days)
    mindate_str = mindate.strftime("%Y/%m/%d")
    return f'{MASTER_IDD_QUERY} AND ("{mindate_str}"[EDAT] : "3000"[EDAT])'
