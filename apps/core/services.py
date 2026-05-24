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
from typing import Any, Protocol, runtime_checkable

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


@runtime_checkable
class _Grounder(Protocol):
    """Minimal grounder protocol — implemented by both the real gilda module
    and the MagicMock stubs used in tests."""

    def ground(self, text: str) -> list[Any]: ...


class _HttpGrounder:
    """Grounder backed by the Gilda/INDRA grounding web service.

    Avoids loading Gilda's multi-GB in-memory index in every worker — useful
    for memory-constrained deployments. POSTs ``{"text": ...}`` to the service
    and adapts the JSON into ScoredMatch-like objects exposing ``.score`` and
    ``.term.db / .term.id / .term.entry_name`` (the same surface ground_mention
    reads from local gilda).
    """

    def __init__(self, url: str, *, timeout: float = 15.0) -> None:
        self._url = url
        self._timeout = timeout

    def ground(self, text: str) -> list[Any]:
        import types  # noqa: PLC0415

        import httpx  # noqa: PLC0415

        resp = httpx.post(self._url, json={"text": text}, timeout=self._timeout)
        resp.raise_for_status()
        out: list[Any] = []
        for item in resp.json():
            term = item.get("term") or {}
            if not term.get("db") or not term.get("id"):
                continue
            out.append(
                types.SimpleNamespace(
                    score=float(item.get("score", 0.0)),
                    term=types.SimpleNamespace(
                        db=term["db"],
                        id=str(term["id"]),
                        entry_name=term.get("entry_name") or text,
                    ),
                )
            )
        out.sort(key=lambda m: m.score, reverse=True)  # defensive: highest first
        return out


def _default_grounder() -> _Grounder:
    """Return the grounder for the current settings.

    If ``GILDA_GROUNDING_URL`` is set, use the remote grounding web service
    (no local memory cost). Otherwise load the local ``gilda`` module lazily.
    """
    from django.conf import settings  # noqa: PLC0415

    url = getattr(settings, "GILDA_GROUNDING_URL", "") or ""
    if url:
        return _HttpGrounder(url)
    import gilda  # noqa: PLC0415 — lazy import intentional

    return gilda


def ground_mention(
    text: str,
    *,
    entity_type_hint: str | None = None,
    grounder: _Grounder | None = None,
) -> OntologyEntity | None:
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

    _g: _Grounder = grounder if grounder is not None else _default_grounder()

    try:
        matches = _g.ground(text.strip())
    except Exception as exc:  # gilda's resource load can fail on cold worker
        logger.warning("grounder.ground failed for %r: %s", text, exc)
        return None

    if not matches:
        return None

    top = matches[0]
    if top.score < GROUND_SCORE_THRESHOLD:
        return None

    scheme = _GILDA_DB_TO_SCHEME.get(top.term.db.upper(), "OTHER")
    entity_type = entity_type_hint or _GILDA_DB_TO_ENTITY_TYPE.get(top.term.db.upper(), "other")

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
