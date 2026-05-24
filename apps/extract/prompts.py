"""Versioned PPI extraction prompt.

Per spec §2 / §10 (Phase 2 deliverable), every ``ExtractionRun`` is
keyed on ``(chunk × model × prompt_version)`` so iterating the prompt
later does not invalidate prior extractions — old rows stay; new rows
appear alongside under a new version. Never edit ``PROMPT_V1_BODY`` in
place after first deploy; bump to ``PROMPT_V2_BODY`` instead.
"""

from __future__ import annotations

PROMPT_V1_VERSION = "1.0.0"

# The exact 7 Ollama models the cluster gateway exposes (per spec §1
# architecture diagram and §6 worker rationale). This is the canonical
# ensemble roster; deployments may run a subset (see active_models()).
SUPPORTED_OLLAMA_MODELS: tuple[str, ...] = (
    "medgemma:27b",
    "phi4:14b",
    "qwen3:8b",
    "gemma3:12b",
    "deepseek-r1:32b",
    "devstral:24b",
    "llama3.1:8b",
)


def active_models() -> tuple[str, ...]:
    """Return the models extraction should actually dispatch to.

    Defaults to the full canonical ensemble (``SUPPORTED_OLLAMA_MODELS``).
    A deployment whose GPU can only serve a subset (e.g. a single box with
    ``OLLAMA_MAX_LOADED_MODELS=2``) sets ``settings.EXTRACTION_ACTIVE_MODELS``
    to that subset so chunks are considered "covered" once those models
    finish — otherwise coverage can never reach ``len(SUPPORTED_OLLAMA_MODELS)``
    and ``enqueue_pending_chunks`` re-dispatches the missing models forever,
    flooding queues that have no worker. Unknown names are ignored; an empty
    or fully-invalid config falls back to the full roster.
    """
    from django.conf import settings  # noqa: PLC0415 — avoid import-time settings access

    configured = getattr(settings, "EXTRACTION_ACTIVE_MODELS", None)
    if not configured:
        return SUPPORTED_OLLAMA_MODELS
    active = tuple(m for m in SUPPORTED_OLLAMA_MODELS if m in set(configured))
    return active or SUPPORTED_OLLAMA_MODELS


PROMPT_V1_BODY = """\
You are a biomedical relation-extraction system specialised in the
intervertebral disc (IVD) literature, including nucleus pulposus,
annulus fibrosus, cartilage endplate, and notochordal cell biology.

Read the Results-section text below and extract every protein-protein,
protein-RNA, protein-metabolite, or gene-regulation interaction the
authors **directly demonstrate** in their own experiments. Do not
extract claims that the authors merely cite from other papers, and do
not infer interactions that the text does not state.

For each interaction, return one object with these fields:

  • subject              — gene/protein symbol acting as the upstream node
  • object               — gene/protein symbol being acted on
  • relation             — one of:
      activates, inhibits, binds, phosphorylates, dephosphorylates,
      ubiquitinates, deubiquitinates, transcribes, represses, cleaves,
      translocates
  • evidence_span        — the verbatim sentence(s) supporting the claim
  • evidence_offset_start — zero-based character index of the span in the
                            chunk text I gave you
  • evidence_offset_end   — exclusive character index of the span's end
                            (strictly greater than evidence_offset_start)
  • cell_type            — cell type / tissue context (e.g. "nucleus
                           pulposus", "annulus fibrosus", "MSC"),
                           or null if not stated
  • stimulus             — experimental stimulus (e.g. "IL-1β
                           stimulation", "TNF-α", "hypoxia", "mechanical
                           load"), or null if not stated
  • confidence           — your subjective confidence on [0.0, 1.0]
                           that this interaction is correctly extracted

Return strictly the JSON object {"ppis": [ ... ]}. If the chunk reports
no qualifying interactions, return {"ppis": []}. Do not output prose,
commentary, code fences, or any field not listed above.

----- BEGIN CHUNK -----
{{CHUNK_TEXT}}
----- END CHUNK -----
"""


# V2 adds two curation fields biologists need to triage an interaction:
# the source organism (species) and whether it was shown in degenerated vs
# healthy disc tissue (deg_status). Bumping the version (rather than editing
# V1 in place) keeps prior V1 extractions valid and re-extracts under the new
# schema — see the module docstring.
PROMPT_V2_VERSION = "2.0.0"

PROMPT_V2_BODY = """\
You are a biomedical relation-extraction system specialised in the
intervertebral disc (IVD) literature, including nucleus pulposus,
annulus fibrosus, cartilage endplate, and notochordal cell biology.

Read the Results-section text below and extract every protein-protein,
protein-RNA, protein-metabolite, or gene-regulation interaction the
authors **directly demonstrate** in their own experiments. Do not
extract claims that the authors merely cite from other papers, and do
not infer interactions that the text does not state.

For each interaction, return one object with these fields:

  • subject              — gene/protein symbol acting as the upstream node
  • object               — gene/protein symbol being acted on
  • relation             — one of:
      activates, inhibits, binds, phosphorylates, dephosphorylates,
      ubiquitinates, deubiquitinates, transcribes, represses, cleaves,
      translocates
  • evidence_span        — the verbatim sentence(s) supporting the claim
  • evidence_offset_start — zero-based character index of the span in the
                            chunk text I gave you
  • evidence_offset_end   — exclusive character index of the span's end
                            (strictly greater than evidence_offset_start)
  • cell_type            — cell type / tissue context (e.g. "nucleus
                           pulposus", "annulus fibrosus", "MSC"),
                           or null if not stated
  • species              — source organism of the cells/tissue, one of:
                           human, rat, mouse, bovine, porcine, rabbit,
                           canine, ovine, other — or null if not stated
  • deg_status           — was the interaction shown in degenerated or
                           healthy disc tissue? "DEG" for degenerated /
                           herniated / pathological / Pfirrmann-graded
                           tissue, "NON-DEG" for healthy / non-degenerated /
                           control tissue, or null if not stated
  • stimulus             — experimental stimulus (e.g. "IL-1β
                           stimulation", "TNF-α", "hypoxia", "mechanical
                           load"), or null if not stated
  • confidence           — your subjective confidence on [0.0, 1.0]
                           that this interaction is correctly extracted

Return strictly the JSON object {"ppis": [ ... ]}. If the chunk reports
no qualifying interactions, return {"ppis": []}. Do not output prose,
commentary, code fences, or any field not listed above.

----- BEGIN CHUNK -----
{{CHUNK_TEXT}}
----- END CHUNK -----
"""


def render_prompt(chunk_text: str) -> str:
    """Fill the chunk-text placeholder with the current (latest) prompt body.

    We use ``{{CHUNK_TEXT}}`` as the placeholder so curly braces inside
    the literal prompt text (e.g. the example JSON shape) don't trigger
    ``str.format``-style errors. The live pipeline renders the active
    ``PromptTemplate`` from the DB via ``extract.services.build_prompt_text``;
    this helper mirrors the latest version for direct callers and smoke tests.
    """
    return PROMPT_V2_BODY.replace("{{CHUNK_TEXT}}", chunk_text)
