# Cross-Plan Reconciliation — Authoritative Contract

> **PRECEDENCE:** This document overrides any conflicting field name, model
> location, task name, or enum value in the individual phase plans
> (`2026-05-19-phase-*.md`). When a phase plan's code references a
> cross-phase model attribute that disagrees with the canonical names
> below, **fix the reference at the consuming call site to match the
> canonical name** — do NOT alter the upstream model definition.

**Date:** 2026-05-19
**Reason for existence:** Phases 1-7 were authored in parallel by independent
agents, each deferring to the spec for cross-phase schemas. The spec describes
models prose-style; the agents made differing concrete naming choices at the
boundaries. This document pins every cross-phase contract to one canonical form.

---

## 1. Definer-precedence rule

Each model is **defined** by exactly one phase. Every other phase is a
**consumer** and must conform to the definer's actual field names.

| Model(s) | Defining phase | App |
|---|---|---|
| `TimestampedModel` | Phase 0 | `core` |
| `OntologyEntity`, `Identifier` | Phase 3 | `core` |
| `Network`, `NetworkQuery`, `FamilyFilter` | Phase 1 | `networks` |
| `Paper`, `PaperRelevance`, `IngestRun` | Phase 1 | `corpus` |
| `Section`, `Chunk`, `PaperClassification` | Phase 1 | `papers` |
| `RateLimitBucket`, `Watermark`, `ScheduledJob` | Phase 1 | `schedule` |
| `PromptTemplate`, `ExtractionRun`, `RawPPI` | Phase 2 | `extract` |
| `Entity`, `Edge`, `EdgeEvidence`, `Conflict`, `NetworkEdgeMembership` | Phase 3 | `graph` |
| `ModelVersion`, `ExportArtifact` | Phase 4 | `sbml` |
| `Review`, `Signoff`, `ReviewAssignment`, `Subscription`, `Notification` | Phase 5 | `verify` |
| `FeatureFlag`, `HealthAlert` | Phase 6 | `monitoring` |

---

## 2. Canonical field names — RawPPI (defined Phase 2, consumed Phases 3/4/5)

`extract.RawPPI` canonical fields:

| Canonical name | Type | Consumers that got it WRONG → fix |
|---|---|---|
| `subject` | CharField | Phase 3 referenced `subject_text` → use `subject` |
| `object` | CharField | Phase 3 referenced `object_text` → use `object` |
| `relation` | CharField | ✓ consistent |
| `evidence_span` | TextField (the text) | ✓ |
| `evidence_offset_start` | PositiveIntegerField | Phase 3/4 referenced `evidence_span_start` → use `evidence_offset_start` |
| `evidence_offset_end` | PositiveIntegerField | Phase 3/4 referenced `evidence_span_end` → use `evidence_offset_end` |
| `cell_type` | CharField (nullable) | ✓ |
| `stimulus` | CharField (nullable) | ✓ |
| `confidence` | FloatField | ✓ |
| `relation_logprob` | FloatField (nullable) | Phase 4 referenced `logprob` / `extraction_logprob` → use `relation_logprob` |
| `ungrounded` | BooleanField | ✓ |
| `run` | FK → `extract.ExtractionRun` | Phase 4 referenced `raw_ppi.extraction_run` → use `raw_ppi.run` |

**The model name of the extractor is NOT on RawPPI.** It lives on the related
`ExtractionRun`. Access it as `raw_ppi.run.model_name`. Phase 4's
`evidence.csv` column `extractor_model` must be sourced from
`raw_ppi.run.model_name` (NOT `raw_ppi.extractor_model`, which does not exist).

## 3. Canonical field names — ExtractionRun (defined Phase 2)

`extract.ExtractionRun` canonical fields: `model_name`, `prompt_version`,
`status` (TextChoices: `queued`/`running`/`done`/`failed`), `chunk` (FK),
`heartbeat`, `attempts`, `error`, `started_at`, `finished_at`, `duration_ms`,
`response_tokens`.

| Mistake | Fix |
|---|---|
| Phase 3 referenced `ExtractionRun.extractor_model` | use `ExtractionRun.model_name` |

## 4. Canonical field names — Edge (defined Phase 3)

`graph.Edge` canonical fields: `source` (FK Entity), `target` (FK Entity),
`relation` (CharField, choices `RELATIONS`), `belief_score`, `status`
(choices: `candidate`/`accepted`/`conflicted`/`rejected`, default `candidate`),
`raw_ppis` (M2M), **plus the two denormalized counters added by this
reconciliation (see §8): `n_supporting_papers`, `n_models_agreeing`.**

| Mistake | Fix |
|---|---|
| Phase 4 referenced `edge.relation_type` (lines ~934, 1003, 1088) | use `edge.relation` |
| Phase 4 read `edge.n_supporting_papers`, `edge.n_models_agreeing` but Phase 3 didn't persist them | now persisted — see §8 |

The `edges.csv` column header is **`relation`** (per spec §7), not
`relation_type`.

## 5. Canonical field names — Entity / OntologyEntity (defined Phase 3, in core)

`core.OntologyEntity`: `entity_type`, `preferred_label`, `description`, **plus
`compartment` and `canonical_uri` added by this reconciliation (§8).**

`core.Identifier`: `entity` (FK), `scheme`, `value`.

`graph.Entity`: `ontology_entity` (OneToOne → OntologyEntity), **plus the proxy
properties added by this reconciliation (§8): `symbol`, `compartment`,
`canonical_uri`, `miriam_uris`.**

| Mistake | Fix |
|---|---|
| Phase 4 read `entity.symbol`, `entity.compartment`, `entity.canonical_uri`, `entity.miriam_uris` as if flat fields | now provided as proxy properties on Entity (§8) — Phase 4 code works unchanged |

## 6. Canonical field names — Network (defined Phase 1)

`networks.Network`: `code` (SlugField), `category`, `title`, `description`,
`keywords` (JSON list of strings, for cheap relevance keyword matching),
`root_entity_aliases` (JSON list of alias strings, for cheap relevance keyword
matching), **plus `root_entities` (JSON list of `{scheme, value}` dicts, for
graph membership) added by this reconciliation (§8)**, `pipeline_status`
(choices: `idle`/`refreshing`/`stale`/`version_draft`/`verified`),
`is_active`.

**Two distinct fields, do not conflate:**
- `root_entity_aliases` — free-text alias strings (`"NF-κB"`, `"RelA"`, `"p65"`) used by Phase 1's cheap keyword relevance triage.
- `root_entities` — structured identifier dicts (`{"scheme":"HGNC","value":"7794"}`) used by Phase 3's `NetworkEdgeMembership` assignment.

| Mistake | Fix |
|---|---|
| Phase 3 referenced `Network.root_entities` but Phase 1 only defined `root_entity_aliases` | `root_entities` now added to Network (§8); both fields coexist |

## 7. Canonical field names — Paper (defined Phase 1)

`corpus.Paper`: `pmid` (PK), `doi`, `pmcid`, `title`, `abstract`, `authors`,
`journal`, **`publication_date`** (DateField), `entrez_date`,
`publication_types`, `mesh_terms`, `pubtator_entities`, `is_original`,
`classification_confidence`, `classification_reason`, `full_text_status`,
`fulltext_s3_key`, `fulltext_fetch_error`, `ingest_status`.

| Mistake | Fix |
|---|---|
| Phase 3 read `paper.pub_date` (lines ~1667) and used `pub_date=` in Paper fixtures (lines ~765, 3362, 3426) | use `publication_date` |
| Phase 6 used `"pub_date"` in a fixture dict (line ~2617) | use `publication_date` (or map it when constructing the Paper) |

Note: a *local variable* or *function parameter* named `pub_date` (e.g.
`recency_weight_for_date(pub_date: date)`) is fine — only the **Django field
access** `paper.pub_date` and the **`Paper(...)` kwarg** must become
`publication_date`.

---

## 8. Genuine model GAPS fixed in this pass (additive, applied to the plans)

These were not naming disagreements but missing fields/properties that
consumers genuinely require. The phase plans have been edited to add them.

1. **`networks.Network.root_entities`** (Phase 1 plan, model + migration):
   ```python
   # JSON list of {"scheme": "...", "value": "..."} dicts — graph membership.
   # Distinct from root_entity_aliases (free-text strings for keyword triage).
   root_entities = models.JSONField(default=list, blank=True)
   ```

2. **`graph.Edge.n_supporting_papers` and `.n_models_agreeing`** (Phase 3 plan,
   model + migration + populated in `normalize_and_integrate`):
   ```python
   n_supporting_papers = models.PositiveIntegerField(default=0)
   n_models_agreeing = models.PositiveIntegerField(default=0)
   ```
   `normalize_and_integrate` must set these whenever it recomputes
   `belief_score` (same code path; the counts are already computed there as
   arguments to `bayes_belief`).

3. **`core.OntologyEntity.compartment` and `.canonical_uri`** (Phase 3 plan,
   model + migration):
   ```python
   compartment = models.CharField(max_length=32, blank=True, default="cytoplasm")
   canonical_uri = models.URLField(blank=True, default="")
   ```

4. **`graph.Entity` proxy properties** (Phase 3 plan) so Phase 4's flat-attribute
   access works without changing Phase 4 code:
   ```python
   @property
   def symbol(self) -> str:
       return self.ontology_entity.preferred_label

   @property
   def compartment(self) -> str:
       return self.ontology_entity.compartment or "cytoplasm"

   @property
   def canonical_uri(self) -> str:
       return self.ontology_entity.canonical_uri

   @property
   def miriam_uris(self) -> list[str]:
       # Build identifiers.org URIs from the entity's Identifier rows.
       scheme_prefix = {
           "UNIPROT": "uniprot", "HGNC": "hgnc", "CHEBI": "chebi",
           "MIRBASE": "mirbase",
       }
       uris = []
       for ident in self.ontology_entity.identifiers.all():
           prefix = scheme_prefix.get(ident.scheme.upper())
           if prefix:
               uris.append(f"https://identifiers.org/{prefix}:{ident.value}")
       return uris
   ```
   (This assumes `Identifier` has `related_name="identifiers"` on its FK to
   `OntologyEntity`. If Phase 3 used a different related_name, adjust the
   property body, not Phase 4.)

---

## 9. Architectural reconciliations

**A. The `monitoring` app (Phase 6) is an accepted 11th app.** The spec
(§2) listed 10 apps and assigned health/state concerns to `schedule`. Phase 6
created a separate `monitoring` app for `FeatureFlag` + `HealthAlert`. This is
accepted — it keeps `schedule` focused on Beat/queue concerns and avoids a
god-module, consistent with the spec's stated boundary discipline. The spec's
app list should be read as 11 apps including `monitoring`.

**B. `Conflict.reasoning` already exists (Phase 3).** Phase 6's plan says it
"adds `reasoning`" to `Conflict` — but Phase 3 already defines
`Conflict.reasoning` (TextField). Phase 6's migration must add ONLY the three
genuinely-new columns: `resolved_relation`, `resolved_at`,
`auto_resolve_attempted_at`. Do not re-add `reasoning`.

**C. `Conflict.resolution_status` values.** Canonical choices (Phase 3 definer):
`open` / `auto_resolved` / `human_resolved`. Phase 6's auto-resolver sets
`auto_resolved`; the verify UI (Phase 5) sets `human_resolved`.

**D. `NetworkEdgeMembership` Phase 6 extensions.** Phase 6 adds
`pending_paper_id` and `pending_extraction` columns to Phase 3's
`NetworkEdgeMembership` (which defines `network`, `edge`, `relevance`). This is
an additive migration in Phase 6; no conflict.

---

## 10. Confirmed-consistent contracts (no action needed)

- **Celery queue names**: `q.io`, `q.fast`, `q.extract.<model>` (7 models) — consistent across Phases 2, 6.
- **Integration task naming**: `graph.normalize_and_integrate` (worker fn) + `graph.integrate_pending` (Beat task) — consistent across Phases 3, 6.
- **`Chunk.text`** and **`Chunk.processed_by_models`** — Phase 2's assumptions match Phase 1's definitions exactly.
- **`EdgeEvidence` reverse name `evidence`** — Phase 4's `edge.evidence.all()` matches Phase 3's `related_name="evidence"`.
- **`graph.Edge.status='accepted'`** filter — value exists in Phase 3's `STATUSES`.
- **`Network.pipeline_status`** includes `version_draft` and `verified` — Phases 4/5 dependencies satisfied.
- **`Paper.ingest_status`, `is_original`, `full_text_status`** — Phase 2/3 dependencies satisfied.

---

## 11. Implementer checklist (per consuming phase)

**Before implementing Phase 3:** confirm RawPPI uses `subject`/`object`/
`evidence_offset_*`/`relation_logprob`/`run`; use `publication_date` not
`pub_date`; `Network.root_entities` now exists.

**Before implementing Phase 4:** use `edge.relation` (not `relation_type`);
`edge.n_supporting_papers`/`n_models_agreeing` now persist; `entity.symbol`/
`compartment`/`canonical_uri`/`miriam_uris` are proxy properties;
`raw_ppi.run.model_name` (not `extraction_run`); `raw_ppi.relation_logprob`
(not `logprob`); `raw_ppi.evidence_offset_start/end` (not `evidence_span_*`).

**Before implementing Phase 6:** `Conflict.reasoning` already exists — migrate
only `resolved_relation`/`resolved_at`/`auto_resolve_attempted_at`; use
`publication_date` in Paper fixtures.

**Before implementing Phase 5:** consume `graph.Edge`, `graph.Conflict`,
`sbml.ModelVersion` per canonical names above. Call `sbml.services.regenerate(
network_id, bump='major')` on sign-off.
