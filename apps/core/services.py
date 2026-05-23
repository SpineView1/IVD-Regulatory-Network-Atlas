"""core.services — public API of the core app.

Today this is just the grounding helper. Other shared utilities (timezone
helpers, structured-log shims) live alongside as they accrete.

Testability design
------------------
``ground_mention`` accepts an optional ``grounder`` keyword argument. When
absent (production path), the real ``gilda`` module is used. Tests pass a
``MagicMock`` that implements the same API surface::

    mock.ground(text) -> list[ScoredMatch-like objects]
    match.term.db, match.term.id, match.term.entry_name
    match.score

This means tests NEVER trigger a Gilda resource download.
"""

from __future__ import annotations

import logging
from types import ModuleType
from typing import Optional

from django.db import transaction

from core.models import Identifier, OntologyEntity

logger = logging.getLogger(__name__)

# Gilda's score is roughly the dot-product of TF-IDF vectors. Empirically:
#   > 0.7  → high-confidence match
#   0.5-0.7 → ambiguous; could be wrong family member
#   < 0.5  → noise
# Spec §3 demands tiered strictness; we keep the bar high (0.70) to favour
# precision over recall — the ungrounded RawPPI is still archived, just
# never promoted to an Edge.
GROUND_SCORE_THRESHOLD: float = 0.70

# Gilda's db codes map onto our Identifier.SCHEMES. Anything not listed
# here falls through to OTHER.
_GILDA_DB_TO_SCHEME: dict[str, str] = {
    "HGNC": "HGNC",
    "UP": "UNIPROT",
    "UNIPROT": "UNIPROT",
    "ENSEMBL": "ENSEMBL",
    "EGID": "NCBI_GENE",
    "NCBIGENE": "NCBI_GENE",
    "CHEBI": "CHEBI",
    "MIRBASE": "MIRBASE",
    "MESH": "MESH",
    "GO": "GO",
    "CL": "CL",
    "DOID": "DOID",
    "REACTOME": "REACTOME",
}

# Heuristic mapping from a Gilda match's db code to our entity_type. The
# caller's ``entity_type_hint`` always wins.
_GILDA_DB_TO_ENTITY_TYPE: dict[str, str] = {
    "HGNC": "protein",
    "UP": "protein",
    "UNIPROT": "protein",
    "ENSEMBL": "gene",
    "EGID": "gene",
    "NCBIGENE": "gene",
    "CHEBI": "metabolite",
    "MIRBASE": "mirna",
    "GO": "phenotype",
    "CL": "cell_type",
    "DOID": "phenotype",
}


def _default_grounder() -> ModuleType:
    """Return the real gilda module (imported lazily to avoid startup cost)."""
    import gilda  # noqa: PLC0415 — lazy import intentional

    return gilda


def ground_mention(
    text: str,
    *,
    entity_type_hint: Optional[str] = None,
    grounder: Optional[object] = None,
) -> Optional[OntologyEntity]:
    """Ground a free-text mention to an OntologyEntity via Gilda.

    Returns the (created or pre-existing) OntologyEntity on success, or
    ``None`` if Gilda has no match above ``GROUND_SCORE_THRESHOLD``.
    Idempotent: re-grounding the same text never creates duplicates.

    Parameters
    ----------
    text:
        The raw mention string extracted by the LLM (e.g. ``"IL-1β"``).
    entity_type_hint:
        If supplied, overrides the heuristic entity-type derived from the
        Gilda match's db code (useful when the caller knows the mention is
        a miRNA or metabolite, for example).
    grounder:
        Injectable grounder object for testing. Must expose
        ``grounder.ground(text) -> list[ScoredMatch]``. When ``None``, the
        real ``gilda`` module is used (resource loaded lazily on first call).

    Caller contract: ``ground_mention`` never raises for "no match"; the
    integration task interprets ``None`` as "leave the RawPPI ungrounded".
    """
    if not text or not text.strip():
        return None

    _grounder = grounder if grounder is not None else _default_grounder()

    try:
        matches = _grounder.ground(text.strip())
    except Exception as exc:  # gilda's resource load can fail on cold worker
        logger.warning("grounder.ground failed for %r: %s", text, exc)
        return None

    if not matches:
        return None

    top = matches[0]
    if top.score < GROUND_SCORE_THRESHOLD:
        return None

    scheme = _GILDA_DB_TO_SCHEME.get(top.term.db.upper(), "OTHER")
    entity_type = entity_type_hint or _GILDA_DB_TO_ENTITY_TYPE.get(
        top.term.db.upper(), "other"
    )

    with transaction.atomic():
        # Look up by the primary identifier we're about to create — that is
        # the unique handle, not preferred_label (which can collide across
        # gene/protein synonyms).
        ident = (
            Identifier.objects.filter(scheme=scheme, value=top.term.id)
            .select_related("entity")
            .first()
        )
        if ident is not None:
            return ident.entity

        entity = OntologyEntity.objects.create(
            entity_type=entity_type,
            preferred_label=top.term.entry_name,
        )
        Identifier.objects.create(
            entity=entity,
            scheme=scheme,
            value=top.term.id,
            is_primary=True,
        )
        return entity
