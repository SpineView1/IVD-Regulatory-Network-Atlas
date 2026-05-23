"""JATS / TEI section-type → DoCO IRI mapping.

DoCO (Document Components Ontology) is the SPAR vocabulary that names
canonical paper sections. We map both JATS @sec-type attributes and
free-form headings to a small set of DoCO classes:
    Introduction, Methods, Results, Discussion, Conclusion, Other.

(per spec §4 chunking stage)
"""

from __future__ import annotations

import re

DOCO_IRI_PREFIX = "http://purl.org/spar/doco/"

_DOCO_LABELS = {
    "Introduction": f"{DOCO_IRI_PREFIX}Introduction",
    "Methods": f"{DOCO_IRI_PREFIX}Methods",
    "Results": f"{DOCO_IRI_PREFIX}Results",
    "Discussion": f"{DOCO_IRI_PREFIX}Discussion",
    "Conclusion": f"{DOCO_IRI_PREFIX}Conclusion",
    "Other": f"{DOCO_IRI_PREFIX}Section",
}

_JATS_TYPE_MAP = {
    "intro": "Introduction",
    "introduction": "Introduction",
    "background": "Introduction",
    "methods": "Methods",
    "materials": "Methods",
    "materials|methods": "Methods",
    "methods|materials": "Methods",
    "results": "Results",
    "results|discussion": "Results",
    "discussion": "Discussion",
    "conclusions": "Conclusion",
    "conclusion": "Conclusion",
}

_HEADING_PATTERNS = [
    (re.compile(r"\bintroduction\b|\bbackground\b", re.I), "Introduction"),
    (re.compile(r"\bmethods?\b|\bmaterials\b|\bexperimental procedures?\b", re.I), "Methods"),
    (re.compile(r"\bresults?\b|\bfindings?\b", re.I), "Results"),
    (re.compile(r"\bdiscussion\b", re.I), "Discussion"),
    (re.compile(r"\bconclusions?\b|\bsummary\b", re.I), "Conclusion"),
]


def map_jats_sec_type(sec_type: str | None) -> tuple[str, str]:
    """Map JATS ``@sec-type`` → (label, IRI). Falls back to "Other"."""
    if not sec_type:
        return "Other", _DOCO_LABELS["Other"]
    key = sec_type.lower().strip()
    label = _JATS_TYPE_MAP.get(key, "Other")
    return label, _DOCO_LABELS[label]


def map_section_heading(heading: str | None) -> tuple[str, str]:
    """Map a free-form heading string → (label, IRI). Falls back to "Other"."""
    if not heading:
        return "Other", _DOCO_LABELS["Other"]
    for pattern, label in _HEADING_PATTERNS:
        if pattern.search(heading):
            return label, _DOCO_LABELS[label]
    return "Other", _DOCO_LABELS["Other"]
