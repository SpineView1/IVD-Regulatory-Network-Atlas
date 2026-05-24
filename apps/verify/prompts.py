"""Prompts for verify-app LLM tasks (conflict auto-resolution)."""

from __future__ import annotations

CONFLICT_REREAD_PROMPT = """\
You are a senior biomedical curator with deep expertise in cell signaling.
Two prior automated extractions disagreed about the direction of a
regulatory relationship reported in the same source chunk. Re-read the
chunk carefully, then return a single JSON object with your verdict.

Source chunk (PMID {pmid}, section {section_doco_type}):
\"\"\"
{chunk_text}
\"\"\"

Subject entity: {subject_symbol} ({subject_id})
Object entity:  {object_symbol} ({object_id})

The two prior extractions disagree as follows:

EXTRACTION A (model={model_a}, confidence={confidence_a:.2f}):
  relation={relation_a}
  evidence_span="{evidence_span_a}"

EXTRACTION B (model={model_b}, confidence={confidence_b:.2f}):
  relation={relation_b}
  evidence_span="{evidence_span_b}"

Your task:

1. Identify the single sentence (or sentence pair) in the chunk that
   resolves the question.
2. Pick the correct relation from this controlled vocabulary:
   activates, inhibits, binds, phosphorylates, dephosphorylates,
   ubiquitinates, deubiquitinates, methylates, acetylates,
   transcriptional_activation, transcriptional_repression,
   no_relation, context_dependent.
3. Assess your confidence on a 0.0–1.0 scale. A score >= 0.85 means
   "I am willing to stake my professional reputation on this verdict";
   below that, return ``context_dependent`` or ``no_relation`` and a
   lower confidence so a human reviews the case.
4. Cite the resolving text verbatim (≤ 200 chars).

Return ONLY valid JSON matching the schema below. No prose.
"""

CONFLICT_REREAD_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "relation": {
            "type": "string",
            "enum": [
                "activates",
                "inhibits",
                "binds",
                "phosphorylates",
                "dephosphorylates",
                "ubiquitinates",
                "deubiquitinates",
                "methylates",
                "acetylates",
                "transcriptional_activation",
                "transcriptional_repression",
                "no_relation",
                "context_dependent",
            ],
        },
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "resolving_text": {"type": "string", "maxLength": 200},
        "reasoning": {"type": "string", "maxLength": 800},
    },
    "required": ["relation", "confidence", "resolving_text", "reasoning"],
    "additionalProperties": False,
}

AUTO_RESOLVE_CONFIDENCE_THRESHOLD: float = 0.85
