"""Curated alias normalization for entity mentions the grounder misses.

The LLM extracts colloquial surface-forms ("Collagen II", "Wnt 3α", "type I
collagen") that Gilda can't map, even though the official symbol (COL2A1,
WNT3A, COL1A1) grounds cleanly. ``ground_mention`` tries the raw text first
and only falls back to ``alias_for`` when that fails — so this layer can only
*recover* groundings, never break an existing one.

Keys are stored pre-normalized (see ``_normalize_key``): lower-cased, Greek
letters transliterated, punctuation flattened to single spaces. Values are the
official HGNC gene symbols passed back to the grounder.
"""

from __future__ import annotations

import re

# Greek letters → ASCII transliteration so "wnt 3α" and "wnt 3a" collapse to
# the same lookup key. (Clean symbols like "GSK-3β" already ground on the raw
# path and never reach this layer.)
_GREEK = {
    "α": "a",
    "β": "b",
    "γ": "g",
    "δ": "d",
    "κ": "k",
    "λ": "l",
    "μ": "u",
    "σ": "s",
    "ω": "w",
}


def _normalize_key(text: str) -> str:
    """Lower-case, transliterate Greek, flatten punctuation to single spaces."""
    s = text.strip().lower()
    for greek, ascii_ in _GREEK.items():
        s = s.replace(greek, ascii_)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return s.strip()


# Common IVD-literature surface-forms → official gene symbol. Extend as new
# ungroundable offenders show up in the integrator logs.
_RAW_ALIASES: dict[str, str] = {
    # Collagens — colloquial roman-numeral names vs the COLnA1 symbol.
    "collagen i": "COL1A1",
    "collagen type i": "COL1A1",
    "type i collagen": "COL1A1",
    "collagen 1": "COL1A1",
    "collagen ii": "COL2A1",
    "collagen type ii": "COL2A1",
    "type ii collagen": "COL2A1",
    "collagen 2": "COL2A1",
    "collagen ix": "COL9A1",
    "type ix collagen": "COL9A1",
    "collagen x": "COL10A1",
    "type x collagen": "COL10A1",
    "collagen xi": "COL11A1",
    "type xi collagen": "COL11A1",
    # Proteoglycans / matrix.
    "aggrecan": "ACAN",
    "versican": "VCAN",
    # Wnt ligands frequently written with a trailing Greek letter or hyphen.
    "wnt 3a": "WNT3A",
    "wnt 5a": "WNT5A",
    "wnt 1": "WNT1",
    # Common signalling shorthands.
    "gsk 3b": "GSK3B",
    "gsk 3 beta": "GSK3B",
    "nf kb": "RELA",
    "nf kappab": "RELA",
    "nf kappa b": "RELA",
    # Batch 2 — high-frequency IDD mentions the grounder still misses.
    # (Verified these do NOT ground raw; most other ungrounded names were
    # stranded by a grounding-service outage and just need re-grounding.)
    "lamp2a": "LAMP2",  # chaperone-mediated-autophagy receptor isoform
    "l2a": "LAMP2",
    "tie2": "TEK",
    "tie 2": "TEK",
    "asic1a": "ASIC1",
    "asic 1a": "ASIC1",
    "caspase 3": "CASP3",
    "cleaved caspase 3": "CASP3",
    "caspase 1": "CASP1",
    "cleaved caspase 1": "CASP1",
    "caspase 9": "CASP9",
    "cleaved caspase 9": "CASP9",
    "mir 191 5p": "MIR191",
    "mir 191": "MIR191",
}

# Pre-normalize the keys once so lookups are O(1) and definition stays readable.
MENTION_ALIASES: dict[str, str] = {_normalize_key(k): v for k, v in _RAW_ALIASES.items()}


def alias_for(text: str) -> str | None:
    """Return the official symbol for a known colloquial mention, else None."""
    if not text:
        return None
    return MENTION_ALIASES.get(_normalize_key(text))


# miRNA mentions ("miR-191-5p", "hsa-miR-21", "microRNA-140") map 1:1 to an
# HGNC miRNA *gene* symbol (MIR191, MIR21, MIR140), which grounds cleanly. We
# strip the leading species prefix and the mature-arm suffix (-5p/-3p), which
# denote the same gene. Conservative: only fires on canonical miR-<number>
# naming, so it can't mis-map a non-miRNA. (let-7 family and circRNAs are
# intentionally out of scope — let-7 gene symbols don't ground, and circRNAs
# have no HGNC symbol so mapping them to a host gene would be wrong.)
_MIRNA_RE = re.compile(r"(?:hsa[-_]?)?mir[-_]?(\d{1,4})([a-z]?)(?:[-_]?[35]p)?$", re.IGNORECASE)


def mirna_symbol(text: str) -> str | None:
    """Return the HGNC miRNA gene symbol for a miRNA mention, else None."""
    if not text:
        return None
    s = re.sub(r"microrna", "mir", text.strip(), flags=re.IGNORECASE).replace(" ", "")
    m = _MIRNA_RE.fullmatch(s)
    if not m:
        return None
    return f"MIR{m.group(1)}{m.group(2).upper()}"
