# Disc Interactome — Autonomous Regulatory Network App Design

**Date:** 2026-05-19
**Status:** Design approved by stakeholder; ready for implementation planning
**Owner:** Francis Chemorion (SIMBIOsys / BCN MedTech / UPF DTIC)

---

## 0. Purpose

A Django application, hosted on the SIMBIOsys cluster alongside the existing
Ollama gateway, that autonomously builds and maintains regulatory network
models of the human intervertebral disc by reading PubMed. The system runs
continuously for months at a time; biologists review and sign off on per-network
SBML-qual outputs through a web UI.

The scope covers 200+ networks across 17 categories (NF-κB axis, TGF-β / BMP / SMAD,
Wnt / β-catenin, Notch, Hedgehog, PI3K / AKT / mTOR, MAPK, JAK / STAT, Hippo / YAP-TAZ,
HIF, redox, cGAS-STING, autophagy, apoptosis, senescence, emerging cell-death
modalities, plus transcription factor, epigenetic, non-coding RNA, ECM, growth
factor / cytokine, metabolic, mechanobiology, cell-type-specific, neurovascular,
cell-fate, inter-tissue, GWAS, disease-specific, therapeutic / regenerative,
proteostasis / UPR, and multi-omics integration networks).

The first usable artifact (deliverable in week 3) is the master IDD corpus
itself — a queryable Postgres database of ~30,000–40,000 disc-relevant
papers, network-tagged, with full-text where available.

---

## 1. High-level architecture

```
                                ┌─────────────────────────────────────┐
                                │   Browser (lab team via Authelia)   │
                                └────────────────┬────────────────────┘
                                                 │ HTTPS
                ┌────────────────────────────────▼────────────────────────────────┐
                │                    Authelia gateway                              │
                │       (same instance that fronts the Ollama API)                 │
                └────────────────────────────────┬────────────────────────────────┘
                                                 │ Remote-User header
                ┌────────────────────────────────▼────────────────────────────────┐
                │                      Django web (gunicorn)                       │
                │   Apps: dashboard · networks · verify · sbml · admin             │
                └─────┬───────────────────────────────────────────────┬───────────┘
                      │ read/write                                    │ enqueue
                      ▼                                               ▼
                ┌──────────────┐                              ┌────────────────────┐
                │  Postgres    │◄─── checkpoints ─────────────│   Redis (broker)   │
                │  single DB   │                              └─────────┬──────────┘
                │  all state   │                                        │
                └──────┬───────┘                                        ▼
                       │                          ┌──────────────────────────────────────┐
                       │     ◄── results ──┐      │       Celery worker pool             │
                       │                   │      │  • corpus.refresh   (Beat-scheduled) │
                       │                   ├──────┤  • paper.section    (DoCO)           │
                       │                   │      │  • ppi.extract.<model> × 7 queues    │
                       │                   │      │  • graph.integrate                   │
                       │                   │      │  • sbml.emit                         │
                       │                   │      │  • verify.notify                     │
                       │                   │      └─────────────────┬────────────────────┘
                       │                   │                        │
                       │                   │                        ▼
                       │                   │       ┌───────────────────────────────────┐
                       │                   │       │  External services                │
                       │                   │       │  • NCBI E-utilities (PubMed)      │
                       │                   │       │  • Europe PMC (full text)         │
                       │                   │       │  • PubTator3 (pre-annotation)     │
                       │                   │       │  • UniProt / HGNC / ChEBI REST    │
                       │                   │       │  • Ollama gateway (7 models)      │
                       │                   │       └───────────────────────────────────┘
                       │                   │
                       │           ┌───────┴─────────┐
                       └──────────►│ Object store    │ (full-text PDFs, GROBID XML,
                                   │ MinIO / volume  │  large extracted chunks)
                                   └─────────────────┘
```

### Architectural invariants

- **All persistent state lives in Postgres.** Resumability is a free consequence:
  every Celery task starts by reading rows, ends by committing rows.
- **MinIO holds blobs only** (full-text PDFs, GROBID XML, generated SBML files,
  large LLM responses). Object keys stored in Postgres rows.
- **One Authelia, one auth path.** Same gateway as Ollama; no new password store.
- **Celery routing by queue, not just worker count.** Each Ollama model gets its
  own queue and dedicated worker process so the GPU box doesn't thrash through
  model swaps.

---

## 2. Django apps and module boundaries

Single Django project, ten internal apps. Each owns one concern; cross-app talk
goes through models (reads) or Celery tasks (writes). No circular imports.

```
core ──► networks ──► corpus ──► papers ──► extract ──► graph ──► sbml
   │         │           │          │           │         │        │
   │         └───────────┴──────────┴───────────┴────────►│        │
   │                                                       │        │
   ▼                                                       ▼        ▼
schedule ◄── (Beat triggers; reads everywhere) ────── verify   dashboard (read-only)
```

| App | Responsibility | Key models |
|---|---|---|
| **`core`** | Authelia middleware, ID-ontology clients (UniProt / HGNC / ChEBI / miRBase / MeSH), shared utilities, base abstract models. | `Identifier`, `OntologyEntity` |
| **`networks`** | The 200+ network registry, per-network search queries, eligible protein families, status. | `Network`, `NetworkQuery`, `FamilyFilter` |
| **`corpus`** | Master IDD corpus: PubMed E-utilities client, Europe PMC full-text fetcher, PubTator3 annotations, dedupe, per-network relevance triage. | `Paper`, `PaperRelevance`, `IngestRun` |
| **`papers`** | Document sectioning: PMC JATS XML parser, GROBID for PDFs, DoCO tag mapping, Results-chunk extraction, original-vs-review classifier. | `Section`, `Chunk`, `PaperClassification` |
| **`extract`** | PPI extraction. One task per `(chunk × model)`. Structured-JSON output via Ollama `format` constraint. | `ExtractionRun`, `RawPPI`, `PromptTemplate` |
| **`graph`** | Normalize entities to ontology IDs, aggregate across models and papers, belief scoring, conflict detection, network slicing. | `Entity`, `Edge`, `EdgeEvidence`, `Conflict` |
| **`sbml`** | SBML-qual emission per network, MIRIAM annotations, semver-tagged versions, CSV spreadsheet export. | `ModelVersion`, `ExportArtifact` |
| **`verify`** | Biologist review queue, per-edge approve/reject/comment, per-network sign-off, reviewer audit trail. | `Review`, `Signoff`, `ReviewAssignment` |
| **`schedule`** | Celery Beat schedules, rate limiting, pipeline state machine, dead-letter handling. | `ScheduledJob`, `Watermark`, `RateLimitBucket` |
| **`dashboard`** | Read-only views over everything. Top-level grid, drill-in, search, activity feed. | (no models) |

**Boundary discipline:** each app's `services.py` is the public API of that
app. Other apps call those functions, not the underlying models or tasks. Lets
us refactor (e.g., move `extract` from same-process Celery to a separate
microservice) without touching call sites.

Explicitly *not* introducing a `pipeline` app that "owns the workflow." The
workflow is `schedule` plus app-local Celery tasks. Centralising it creates a
god-module.

---

## 3. Data model

### Layer overview

```
                        ┌─────────────────────────────────────┐
                        │   OntologyEntity (gene/protein/...)  │
ontology layer          │     1..n  Identifier (UNIPROT, ...)   │
                        └────────────────┬────────────────────┘
                                         │
                        ┌────────────────▼────────────────────┐
                        │             Entity                   │
graph layer             │  (a normalized node in the graph)    │
                        └─────┬──────────────────────┬────────┘
                              │ source               │ target
                        ┌─────▼──────────────────────▼────────┐         ┌──────────────────────┐
                        │              Edge                    │1     n  │ NetworkEdgeMembership │ n   1
                        │  (subject, predicate, object)        │◄────────│                       │────►Network
                        │  belief_score · status               │         └──────────────────────┘
                        └──────────────────┬──────────────────┘
                                           │ n
                                           ▼
                        ┌──────────────────────────────────────┐
                        │           EdgeEvidence                │
                        │  Edge ◄─ RawPPI ◄─ ExtractionRun      │
                        │           ▲                           │
                        │           │                           │
                        │       Chunk ◄─ Section ◄─ Paper        │
                        └──────────────────────────────────────┘

                        ┌──────────────────────────────────────┐
                        │       ModelVersion (per Network)      │
sbml/versioning         │  snapshot of accepted Edges → SBML    │
                        │  semver, frozen_at, s3_key            │
                        └──────────────────────────────────────┘

                        ┌──────────────────────────────────────┐
                        │     Review / Conflict / Signoff       │
verify layer            │  per-Edge or per-Network reviewer     │
                        │  actions; audit trail                 │
                        └──────────────────────────────────────┘
```

### Tables

| Table | Why it matters |
|---|---|
| `Paper` (PK = `pmid`) | One row per paper ingested. Status fields drive the pipeline. The whole corpus = `SELECT * FROM corpus_paper` — the "master IDD corpus" deliverable. |
| `Chunk` | Atomic LLM input. Indexed on `(paper_id, section_doco_type)` so the extractor can find `WHERE doco_type='Results' AND NOT processed_by_model_X`. |
| `ExtractionRun` | One row per `(chunk × model × prompt_version)`. Has `status ∈ {queued, running, done, failed}`. The resumability anchor — a crashed worker leaves `running` rows older than the heartbeat threshold; the next sweep re-queues them. |
| `RawPPI` | LLM's raw output with the exact `evidence_span` (char offsets into the chunk). Never deleted, even when superseded. Audit trail. |
| `Entity` & `Edge` | Normalized graph. `Edge` unique on `(source_id, target_id, relation_type)`. `belief_score` recomputed by the integration worker; `status ∈ {candidate, accepted, conflicted, rejected}`. |
| `NetworkEdgeMembership` | Slices the shared edge graph into per-network views. One edge can belong to many networks with different relevance scores. |
| `ModelVersion` | Immutable snapshot. SBML generation reads the current edge set, writes the file to MinIO, freezes the version. |
| `Conflict` | Created when two extractions disagree on direction. Has `resolution_status` + free-text `reasoning`. |
| `Review`, `Signoff` | Append-only — every state change is an audit row, never an UPDATE. |
| `Watermark` | One row per external source (`pubmed_last_pmid`, `pubmed_last_entrez_date`, `europe_pmc_oai_token`). Lets daily ingest pick up exactly where it left off. |
| `RateLimitBucket` | Token-bucket per provider (NCBI, Europe PMC, PubTator, Ollama). Persisted in DB so restart doesn't reset budget. |

### Three load-bearing decisions

**1. Tiered identifier strictness.** Every `Entity` must resolve to at least one
`Identifier` to be promoted from `RawPPI` to `Edge`. If we can't normalize
(~10–20% of mentions), the `RawPPI` stays flagged `ungrounded`, never enters
the graph. Trades some recall for clean SBML and meaningful conflict detection.

**2. Edges are shared, networks slice them.** A single normalized edge appears
in many networks. Don't duplicate — store once, link via
`NetworkEdgeMembership`. A new paper can update many networks simultaneously.

**3. Provenance is a graph, not a string.** Every `Edge` has many
`EdgeEvidence` rows → many `RawPPI`s → each from one `ExtractionRun` over one
`Chunk` of one `Paper`. The biologist UI renders the full provenance tree for
any edge.

### Resumability pattern

Every long-running task:

```python
def task(input_id):
    row = Model.objects.select_for_update().get(id=input_id)
    if row.status == "done":
        return  # idempotent: already processed
    row.status = "running"; row.heartbeat = now(); row.save()
    try:
        result = do_work(row)
        with transaction.atomic():
            write_outputs(result)
            row.status = "done"; row.save()
    except Exception as e:
        row.status = "failed"; row.error = str(e); row.save()
```

A janitor job scans for `status='running' AND heartbeat < now() - 10min` rows
every 5 minutes and resets them to `queued`.

---

## 4. Core pipeline (per-paper end-to-end)

```
   ┌─────────────────────────────────────────────────────────────────────────┐
   │  Daily Beat: corpus.refresh                                             │
   │  Query PubMed E-utilities with the master IDD query, watermark = max    │
   │  PMID seen. Returns ~10-150 new PMIDs/day.                              │
   └─────────────────────────────────┬───────────────────────────────────────┘
                                     │   for each new PMID:
                                     ▼
   ┌─────────────────────────────────────────────────────────────────────────┐
   │  corpus.ingest_paper(pmid)                                              │
   │  • efetch metadata → INSERT Paper(pmid, title, abstract, pubtypes, ...) │
   │  • PubTator3 fetch → cached entity annotations                          │
   │  • Status: PAPER_INGESTED                                               │
   └─────────────────────────────────┬───────────────────────────────────────┘
                                     │
                                     ▼
   ┌─────────────────────────────────────────────────────────────────────────┐
   │  papers.classify_original(paper_id)                                     │
   │  • Cheap path: if `Review`/`Meta-Analysis` in pubtypes → is_original=F  │
   │  • Expensive path: LLM (qwen3:8b) reads abstract+title, returns         │
   │    JSON {is_original: bool, confidence: float, reason: str}             │
   │  • is_original=F → terminate; kept for citation discovery               │
   │  • is_original=T → Status: PAPER_ORIGINAL                               │
   └─────────────────────────────────┬───────────────────────────────────────┘
                                     │
                                     ▼
   ┌─────────────────────────────────────────────────────────────────────────┐
   │  papers.fetch_fulltext(paper_id)                                        │
   │  • If pmcid: Europe PMC OAI-PMH → JATS XML to MinIO                     │
   │  • Else if open-access PDF discoverable: download → GROBID → TEI XML    │
   │  • Else: abstract-only (mark full_text_status='abstract_only')          │
   │  • Status: FULLTEXT_FETCHED                                             │
   └─────────────────────────────────┬───────────────────────────────────────┘
                                     │
                                     ▼
   ┌─────────────────────────────────────────────────────────────────────────┐
   │  papers.section_and_chunk(paper_id)                                     │
   │  • Parse XML → map section types to DoCO IRIs                           │
   │  • Keep doco:Results sections (plus doco:Conclusions tagged as aux)     │
   │  • Split each Results section into chunks of ≤ 1800 tokens, 200-token   │
   │    overlap, sentence-boundary-aware                                     │
   │  • Bulk INSERT Section + Chunk rows                                     │
   │  • Status: CHUNKED                                                      │
   └─────────────────────────────────┬───────────────────────────────────────┘
                                     │   fans out: 7 models × N chunks
                                     ▼
   ┌─────────────────────────────────────────────────────────────────────────┐
   │  extract.run_ppi(chunk_id, model_name)   [one per Celery queue]         │
   │  • Build prompt from PromptTemplate(version=active)                     │
   │  • POST /api/generate with format=PPI_SCHEMA + logprobs=true            │
   │  • Parse structured JSON: list of {subject, object, relation,           │
   │    evidence_span, cell_type, stimulus, confidence}                      │
   │  • Bulk INSERT RawPPI rows referencing this ExtractionRun               │
   │  • ExtractionRun.status = done                                          │
   └─────────────────────────────────┬───────────────────────────────────────┘
                                     │   chunk completion triggers...
                                     ▼
   ┌─────────────────────────────────────────────────────────────────────────┐
   │  graph.normalize_and_integrate(raw_ppi_ids)                             │
   │  • Gilda-ground each subject/object string → OntologyEntity (or fail)   │
   │  • If both grounded: upsert Entity rows                                 │
   │  • Find or create Edge(source, target, relation)                        │
   │  • Append EdgeEvidence row                                              │
   │  • Recompute Edge.belief_score (Bayes update over models + papers)      │
   │  • Detect Conflict: same (source,target) but opposite relation in same  │
   │    chunk (intra-paper) or other paper (inter-paper) → open Conflict     │
   │  • Update NetworkEdgeMembership: which network roots is this near?      │
   │  • If new edges crossed threshold → mark affected Networks as STALE     │
   └─────────────────────────────────┬───────────────────────────────────────┘
                                     │   nightly: STALE networks
                                     ▼
   ┌─────────────────────────────────────────────────────────────────────────┐
   │  sbml.regenerate(network_id)                                            │
   │  • SELECT Edges WHERE Edge.status='accepted' AND in NetworkEdgeMembership│
   │  • Build SBML-qual document with MIRIAM annotations                     │
   │  • Build CSV (edges × evidence count × belief × reviewer state)         │
   │  • Bump ModelVersion semver                                             │
   │  • Notify subscribed reviewers via verify.notify                        │
   └─────────────────────────────────────────────────────────────────────────┘
```

### Per-stage failure handling

| Stage | Failure mode | Recovery |
|---|---|---|
| `corpus.refresh` | NCBI rate-limit / outage | Watermark not advanced; retry next Beat tick |
| `ingest_paper` | Bad metadata | `Paper.status='ingest_failed'`, retried 3× with backoff, then DLQ |
| `classify_original` | LLM returns garbage | `RetryError` with exponential backoff; uses fallback rule-based after 3 tries |
| `fetch_fulltext` | PDF / GROBID failure | Continue with abstract-only; `full_text_status='abstract_only'` |
| `section_and_chunk` | XML parsing crash | Log to Sentry, mark paper `chunk_failed`; ops can re-trigger |
| `run_ppi` | Ollama timeout / 5xx | Celery retry (3×, exponential backoff). Persistent fails → `ExtractionRun.status='failed'`, integration skips it |
| `normalize_and_integrate` | Gilda lookup fail | `RawPPI.ungrounded=True`, never enters graph |
| `regenerate` | SBML library error | ModelVersion stays at previous semver; alert ops |

### Key per-stage choices

- **Cheap-first triage.** Paper classification uses PubMed publication types
  before invoking an LLM. ~70% of reviews are pre-tagged.
- **Fan-out happens at chunking.** A 6-section, 12-chunk paper produces 84
  `ExtractionRun` rows (12 × 7 models). Each is a Celery message routed to its
  model's queue.
- **Integration is debounced.** `graph.normalize_and_integrate` batches
  `RawPPI`s per `(paper × model)` so the Bayes update on belief scores doesn't
  thrash. Batch size 10–50.
- **STALE → regenerate is throttled.** SBML regeneration runs nightly per
  network, not on every edge change.

---

## 5. Master IDD corpus subsystem

### PubMed query

Hybrid MeSH-anchored + free-text, weighted by date:

```
(
  "Intervertebral Disc"[MeSH]               OR
  "Intervertebral Disc Degeneration"[MeSH]  OR
  "Intervertebral Disc Displacement"[MeSH]  OR
  "Nucleus Pulposus"[MeSH]                  OR
  "intervertebral disc"[TIAB]               OR
  "intervertebral disk"[TIAB]               OR
  "nucleus pulposus"[TIAB]                  OR
  "annulus fibrosus"[TIAB]                  OR
  "disc degeneration"[TIAB]                 OR
  "disc herniation"[TIAB]                   OR
  "cartilage endplate"[TIAB]                OR
  "spinal disc"[TIAB]
)
AND English[Language]
AND ("1980"[PDAT] : "3000"[PDAT])
```

Expected counts:
- Historical: ~30,000–40,000 papers
- Annual flow: ~3,000–5,000 new papers
- PMC full-text yield: ~50–60% for ≥ 2008; lower for older work

No publication-type exclusion at query time — reviews stay in the corpus for
citation discovery. The `is_original` classifier later decides what gets
extracted.

### Discovery sources

| Source | Role | Rate budget |
|---|---|---|
| **NCBI E-utilities (ESearch, EFetch, ELink)** | Primary discovery + metadata. ELink with `linkname=pubmed_pubmed_refs` traverses review reference lists. | 3 req/s → 10 req/s with free API key |
| **Europe PMC OAI-PMH** | Full-text JATS XML for PMC open-access papers. | ~30 req/s |
| **PubTator3 REST** | Pre-annotated entities (genes, chemicals, diseases, mutations) per PMID. | ~10 req/s |
| **GROBID (local sidecar)** | PDF → TEI XML for non-PMC papers. | Local, no rate limit |

All four wrapped in `schedule.RateLimitBucket` (token-bucket per source,
persisted in Postgres).

### Watermark / continuous monitoring

`Watermark` rows per source:
- `pubmed_last_entrez_date` — date paper was added to PubMed
- `pubmed_last_pmid_seen` — high-water mark
- Daily Beat queries with `mindate = last_entrez_date - 7 days` (7-day overlap
  to catch late-indexed papers)
- `corpus.refresh` runs hourly; full re-sweep weekly for safety

### Citation traversal

Every paper marked `is_original=False` gets its reference list pulled via ELink.
Each cited PMID enters the discovery queue if not already in `Paper`. This is
the "find papers our keyword search missed" mechanism. Reviews are kept in the
corpus, just never sent to extraction.

### Per-network relevance triage (two-pass)

```
   New Paper ingested
        │
        ▼
  ┌────────────────────────────────────────────────────────────────┐
  │ Cheap pass (per network, instant):                             │
  │   • Any of network.keywords match abstract/title?              │
  │   • Any of network.root_entity_aliases match PubTator entities?│
  │   → If neither: PaperRelevance.relevance=0, done.              │
  └────────────────────────┬───────────────────────────────────────┘
                           │ pass
                           ▼
  ┌────────────────────────────────────────────────────────────────┐
  │ Expensive pass (qwen3:8b, ~1s):                                 │
  │   "Given network description: [X], does this abstract report   │
  │    primary experimental evidence relevant to this network?"    │
  │   Returns JSON {relevant: bool, confidence: float, reason}     │
  │   → store PaperRelevance(paper, network, score=confidence)     │
  └────────────────────────────────────────────────────────────────┘
```

Result: many-to-many `PaperRelevance`. The "corpus for network X" is
`SELECT paper FROM PaperRelevance WHERE network=X AND relevance > 0.5`.

### Storage

| Where | What |
|---|---|
| Postgres `corpus_paper` | PMID, DOI, title, authors (jsonb), journal, pub_date, entrez_date, abstract, mesh_terms (array), publication_types (array), is_original, full_text_status, fulltext_s3_key |
| Postgres `corpus_paperrelevance` | (paper_id, network_id, score, classified_by, classified_at) |
| Postgres `schedule_watermark` | per-source watermark state |
| MinIO `papers/<pmid_prefix>/<pmid>.{xml,pdf,tei}` | raw documents, sharded by first 4 digits of PMID |

### Phase-1 deliverable surface

- `/corpus/export.csv?format=full` — every paper with metadata + classifier + full-text flag
- `/corpus/export.csv?network=nfkb_axis` — network-filtered slice
- `/corpus/stats` — counts by year, journal, MeSH, full-text coverage, original-vs-review
- `/corpus/paper/<pmid>` — single-paper view
- Postgres dump — corpus is portable

### Bootstrap timeline (corpus only)

| Phase | Effort | Wall-clock |
|---|---|---|
| 0. PubMed dump (ESearch + EFetch) | ~40k papers × metadata only | ~3 hours at 10 req/s |
| 1. `is_original` classifier sweep | Cheap rule covers ~70%; LLM covers rest | ~6 hours |
| 2. Full-text fetch (PMC OAI + GROBID) | ~20k full texts | ~24 hours |
| 3. Sectioning + chunking | CPU-bound, parallel | ~4 hours |
| 4. Per-network relevance triage (×200 networks) | Cheap pass instant; LLM only on candidates | ~2 days |

**Total: master corpus, network-tagged, exportable, in ≤ 1 week** of cluster
wall-clock. Extraction takes months; corpus is the early win.

---

## 6. Celery topology and concurrency

The hard constraint: all 7 Ollama models share one GPU box. Naively running
them in parallel just makes Ollama thrash through `mmap`/`munmap` cycles.
Queue layout is designed around model affinity.

### Workers and queues

```
                           ┌──────────────────────────────────────────┐
                           │   Beat (single instance)                  │
                           │   Cron-fires periodic tasks               │
                           └─────────────────────┬────────────────────┘
                                                 │
   ┌─────────────────────────────────────────────┴──────────────────────────────────┐
   │                          Redis broker (queues)                                  │
   └──────────────────────────────┬─────────────────────────────────────────────────┘
                                  │
   ┌──────────────────────────────┼──────────────────────────────────────────────────┐
   │                              │                                                   │
   ▼                              ▼                                                   ▼
worker.io                  worker.fast_llm                              worker.extractor.<model>
concurrency=8              concurrency=2                                concurrency=1   (×7 processes)
queues: q.io               queues: q.fast                               queue: q.extract.<model>
                                                                        bound to ONE model each

Handles:                   Handles:                                     Handles:
• corpus.ingest_paper      • classify_original                          • run_ppi(chunk, model)
• fetch_fulltext           • per-network relevance triage              • (no other tasks — keep model hot)
• section_and_chunk        • conflict.auto_resolve (re-read)
• graph.normalize_*
• graph.integrate
• sbml.regenerate
• verify.notify
```

### Per-worker rationale

| Worker process | Why this shape |
|---|---|
| `worker.io` × 1, concurrency 8 | IO-bound (HTTP calls). Eight concurrent greenlets fits NCBI's 10 req/s. |
| `worker.fast_llm` × 1, concurrency 2 | Cheap classifier calls (qwen3:8b ~1 s/call). Two in flight keeps the smallest model busy. |
| `worker.extractor.<model>` × 7, concurrency 1 | One worker per Ollama model. Combined with `OLLAMA_KEEP_ALIVE=2h`, each model stays resident as long as its queue has anything. Avoids swap-thrash. |

Two extractor workers run on the GPU simultaneously
(`OLLAMA_MAX_LOADED_MODELS=2`); the other five queues accumulate; Ollama
rotates models in as VRAM frees.

### Beat schedule

| Task | Cadence | Purpose |
|---|---|---|
| `schedule.janitor_reset_stale_running` | every 5 min | Resets `status='running' AND heartbeat < now()-10min` to `queued` |
| `corpus.refresh_pubmed` | every 1 hour | Incremental PubMed sweep using watermark |
| `corpus.refresh_pubmed_full` | weekly, Sunday 03:00 UTC | Wider re-sweep (90-day overlap) |
| `papers.classify_pending` | every 15 min | Any `Paper.is_original IS NULL` |
| `papers.fetch_fulltext_pending` | every 10 min | Any `Paper.full_text_status='none'` |
| `papers.section_pending` | every 10 min | Any fetched paper not yet chunked |
| `extract.enqueue_pending_chunks` | every 5 min | Find unprocessed `(Chunk × Model)` pairs |
| `graph.integrate_pending` | every 10 min | Batch-process new `RawPPI`s into `Edge`s |
| `sbml.regenerate_stale_networks` | daily, 02:00 UTC | Any network with new edges → re-emit |
| `schedule.refill_rate_limit_buckets` | every 1 min | Token-bucket replenish |
| `verify.dispatch_review_assignments` | every 1 hour | Notify reviewers |

### Rate limits

`RateLimitBucket(provider, capacity, refill_per_sec, current_tokens, updated_at)`.
Every outbound call wrapped in `@require_token("ncbi_eutils", cost=1)`. If
exhausted, task re-enqueued with `countdown=bucket.seconds_until_refill`.

### Priority lanes

Two priorities per queue:

| Priority | Source |
|---|---|
| 9 (urgent) | User-triggered actions, conflict resolution |
| 1 (default) | Background sweep, daily refresh, scheduled re-extraction |

### Failure / observability

- Tasks wrap their bodies in `try/except` with heartbeat updates every 30 s
- A heartbeat callback updates `Model.heartbeat = now()` for long tasks
- Flower (Celery web monitor) at `/flower/` behind Authelia
- Failed tasks accumulate in `dead_letter_log`; admin UI shows them with retry

---

## 7. SBML-qual output and verification UI

### SBML-qual emission

One file per `ModelVersion`, built with `python-libsbml`. Each accepted `Edge`
becomes one `qual:Transition`; each `Entity` becomes one
`qual:QualitativeSpecies`.

```xml
<sbml xmlns="http://www.sbml.org/sbml/level3/version1/core"
      xmlns:qual="http://www.sbml.org/sbml/level3/version1/qual/version1"
      level="3" version="1">
  <model id="nfkb_axis_v0_3_2" name="NF-κB → MMP/ADAMTS catabolic output (NP cells)"
         qual:required="true">
    <listOfCompartments>
      <compartment id="cytoplasm" constant="true" />
      <compartment id="nucleus" constant="true" />
      <compartment id="extracellular" constant="true" />
    </listOfCompartments>
    <qual:listOfQualitativeSpecies>
      <qual:qualitativeSpecies qual:id="IL1B" qual:compartment="extracellular"
                               qual:maxLevel="1" qual:initialLevel="0"
                               qual:constant="false">
        <annotation>
          <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
                   xmlns:bqbiol="http://biomodels.net/biology-qualifiers/">
            <rdf:Description rdf:about="#IL1B">
              <bqbiol:is>
                <rdf:Bag>
                  <rdf:li rdf:resource="https://identifiers.org/uniprot:P01584"/>
                  <rdf:li rdf:resource="https://identifiers.org/hgnc:5992"/>
                </rdf:Bag>
              </bqbiol:is>
            </rdf:Description>
          </rdf:RDF>
        </annotation>
      </qual:qualitativeSpecies>
    </qual:listOfQualitativeSpecies>
    <qual:listOfTransitions>
      <qual:transition qual:id="t_IL1B_NFKB1">
        <qual:listOfInputs>
          <qual:input qual:qualitativeSpecies="IL1B" qual:sign="positive"
                      qual:transitionEffect="none"/>
        </qual:listOfInputs>
        <qual:listOfOutputs>
          <qual:output qual:qualitativeSpecies="NFKB1"
                       qual:transitionEffect="assignmentLevel"/>
        </qual:listOfOutputs>
        <qual:listOfFunctionTerms>
          <qual:defaultTerm qual:resultLevel="0"/>
          <qual:functionTerm qual:resultLevel="1">
            <math xmlns="http://www.w3.org/1998/Math/MathML">
              <apply><geq/><ci>IL1B</ci><cn type="integer">1</cn></apply>
            </math>
          </qual:functionTerm>
        </qual:listOfFunctionTerms>
        <annotation>
          <interactome:evidence>
            <interactome:pmids>12345678,23456789,34567890</interactome:pmids>
            <interactome:belief>0.94</interactome:belief>
            <interactome:n_models_agree>6</interactome:n_models_agree>
            <interactome:reviewer_signoff>true</interactome:reviewer_signoff>
          </interactome:evidence>
        </annotation>
      </qual:transition>
    </qual:listOfTransitions>
  </model>
</sbml>
```

Annotations on every species and transition:
- **MIRIAM `bqbiol:is`** points to authoritative ontology entries via
  `identifiers.org` (UniProt, HGNC, ChEBI, miRBase). Makes the file portable
  into BioModels, CellNOpt, GINsim, CellDesigner.
- **Custom `interactome:evidence`** namespace carries provenance metadata
  (PMIDs, belief, model agreement, reviewer status). Tools that don't know our
  namespace ignore it.

### Versioning rules

```
PATCH  =  Edges added; existing signs unchanged; no edges removed
MINOR  =  An edge changed sign, OR an edge was rejected by integration
MAJOR  =  Curator action: edges added/removed manually, or network flipped to 'verified'
```

Curators always cut MAJOR versions on sign-off — the curated model is
semantically a different document from the auto-generated draft.

### CSV exports — two files per network per version

`edges.csv`:

| col | meaning |
|---|---|
| `source_symbol`, `source_id`, `source_type` | HGNC symbol, canonical URI, gene/protein/miRNA/metabolite/complex |
| `relation` | activates / inhibits / binds / phosphorylates / etc. |
| `target_symbol`, `target_id`, `target_type` | … |
| `belief` | 0..1 |
| `n_supporting_papers` | distinct PMIDs |
| `n_models_agreeing` | how many of the 7 Ollama models extracted this |
| `reviewer_status` | unreviewed / approved / rejected / conflicted |
| `first_seen`, `last_seen` | timestamps |

`evidence.csv` (one row per `EdgeEvidence`):

| col | meaning |
|---|---|
| `edge_id` | foreign key |
| `pmid` | source paper |
| `chunk_excerpt` | sentence containing the evidence span |
| `evidence_span_start`, `evidence_span_end` | char offsets |
| `extractor_model` | which Ollama model produced this |
| `extraction_logprob` | confidence at the relation-type token |
| `extracted_at` | timestamp |

Both CSVs + SBML + `README.md` zipped into per-version artifact:
`<network_code>_v<semver>.zip`, served via
`/networks/<code>/v/<semver>/download`.

### Verification UI — five screens

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ /dashboard                                                  Francis · Curator│
├─────────────────────────────────────────────────────────────────────────────┤
│  200 Networks  ·  Active corpus 34,127 papers  ·  PubMed +43 last 24h       │
│  Category I — Core Signaling                                                │
│   ▸ NF-κB Axis (7)         [▣▣▣▢▢▢▢]  STALE  · 12 disagreements             │
│   ▸ TGF-β / BMP / SMAD (10) [▣▣▣▣▢▢▢]  REFRESHING                            │
│   ▸ Wnt / β-catenin (5)    [▣▣▣▣▣▢▢]  VERIFIED (v1.2.0)                     │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ /networks/nfkb_axis_mmp_adamts                                              │
├──────────────────────────┬──────────────────────────────────────────────────┤
│ Graph (Cytoscape.js)     │ Versions                                          │
│   [interactive graph]    │  v0.3.2  (auto)   2026-05-18  edges 87 · ⚠ 12   │
│                          │  v0.3.1  (auto)   2026-05-15  edges 84           │
│                          │ Downloads                                        │
│                          │  ⬇ SBML-qual  ⬇ edges.csv  ⬇ evidence.csv  ⬇ zip│
└──────────────────────────┴──────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│ /networks/nfkb_axis_mmp_adamts/disagreements                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│ ⚠ SIRT1 → NFKB1   (4 models INHIBIT  ·  3 models ACTIVATE)                  │
│   Evidence A: PMID 28456123 "...SIRT1 overexpression deacetylated p65..."   │
│   Evidence B: PMID 32156789 "In pancreatic β-cells, SIRT1 enhanced NF-κB"   │
│   Resolution: ◯ Keep INHIBIT  ◯ Keep ACTIVATE  ◉ Context-dependent (split)  │
│   [Approve & continue →]                                                     │
└─────────────────────────────────────────────────────────────────────────────┘
```

Stack:
- Django templates + **HTMX** for partial updates (no SPA)
- **Cytoscape.js** for graph rendering
- **DataTables** for tabular grids
- Each click is a normal POST → Django view → DB write → HTMX swap

### Sign-off workflow

```
Network status state machine:

   IDLE ─── new corpus arrives ──► STALE
                                    │
                                    │ sbml.regenerate runs (nightly)
                                    ▼
                              VERSION_DRAFT (v0.X.Y, auto)
                                    │
                                    │ curator reviews
                                    ▼
                              VERIFIED (v1.0.0, curator-cut MAJOR)
                                    │
                                    │ new evidence arrives
                                    ▼
                              VERIFIED → STALE  (new draft cut on top)
```

Reviewers subscribe per-user, per-network or per-category for email + in-app
notifications.

---

## 8. Resumability and state semantics

Single invariant: **every checkpoint is a Postgres row.** No worker carries
meaningful in-memory state across task boundaries.

### Five mechanisms

**1. Status rows on every persistent unit of work.**

| Entity | Status field | Statuses |
|---|---|---|
| `Paper` | `ingest_status` | `pending → ingested → classified → fetched → chunked → done · failed` |
| `ExtractionRun` | `status` | `queued → running → done · failed` |
| `RawPPI` | (no status — terminal artifact) | — |
| `Edge` | `status` | `candidate → accepted · conflicted · rejected` |
| `Network` | `pipeline_status` | `idle → refreshing → stale → version_draft → verified` |
| `ModelVersion` | `frozen` | bool — `false` while generating, `true` when artifact in MinIO |
| `Review`, `Signoff` | — | append-only, no state |

**2. Heartbeats on long tasks** — `@with_heartbeat(model_id=ExtractionRun, interval=30)`
decorator updates `heartbeat = now()` every 30 s.

**3. The janitor** — `schedule.janitor_reset_stale_running` runs every 5 min:

```sql
UPDATE extract_extractionrun
   SET status = 'queued', heartbeat = NULL, attempts = attempts + 1
 WHERE status = 'running'
   AND (heartbeat IS NULL OR heartbeat < now() - interval '10 minutes');
```

Tasks with `attempts >= 3` go to `dead_letter_log` instead of being re-queued.

**4. Idempotent task entry** — first line of every task body checks
`row.status == 'done'` and short-circuits.

**5. External-state watermarks** — PubMed last-seen-PMID, Europe PMC OAI
resumption token, Ollama session, rate-limit token counts all mirrored into
`schedule_watermark` and `schedule_ratelimit_bucket` rows, transactional with
the consuming task.

### Cold restart procedure

```
docker-compose down
docker-compose up -d postgres redis minio grobid
# wait for pg_isready
docker-compose up -d web beat celery_workers
```

Within ≤ 5 min, the janitor sweeps stale `running` rows back to `queued`.
Beat starts firing scheduled tasks. Workers pick up the queue. Total downtime
~30 seconds; ≤ 5 min for in-flight work to resume.

### Schema migration safety

Forward-only migrations; we never drop columns workers might still reference
until at least one deploy cycle of dual-read. `docker-compose` health check
makes `celery_workers` wait on `web` running `python manage.py migrate`.

### Disaster recovery

- Postgres: daily `pg_dump` + WAL archiving with `pgbackrest`. RPO ≤ 15 min, RTO ≤ 30 min.
- MinIO: nightly `rclone sync` to external location.
- Redis: ephemeral. Lost queue contents picked up by janitor on next sweep.

The whole system passes the "pull the plug" test: any moment, `kill -9` every
process, restart everything, it converges to the right state within minutes.

---

## 9. Deployment and operations

### docker-compose.yml (abridged)

```yaml
services:
  caddy:                # reverse proxy + TLS
    image: caddy:2
    ports: ["443:443"]
    # forward_auth → authelia.simbiosys.sb.upf.edu/api/verify

  web:                  # Django + gunicorn
    build: ./interactome
    command: gunicorn interactome.wsgi --workers 4 --bind 0.0.0.0:8000
    depends_on: [postgres, redis, minio]
    environment:
      - DJANGO_SETTINGS_MODULE=interactome.settings.production
      - DATABASE_URL=postgres://...
      - REDIS_URL=redis://redis:6379/0
      - OLLAMA_BASE=https://ollama.simbiosys.sb.upf.edu
      - AUTHELIA_VERIFY=https://authelia.simbiosys.sb.upf.edu/api/verify

  beat:
    image: <same as web>
    command: celery -A interactome beat -l info

  worker_io:
    command: celery -A interactome worker -Q q.io -c 8 -n io@%h
  worker_fast:
    command: celery -A interactome worker -Q q.fast -c 2 -n fast@%h
  worker_extract_medgemma:
    command: celery -A interactome worker -Q q.extract.medgemma_27b -c 1 -n m@%h
  worker_extract_phi4:
    command: celery -A interactome worker -Q q.extract.phi4_14b -c 1 -n p@%h
  worker_extract_qwen3:
    command: celery -A interactome worker -Q q.extract.qwen3_8b -c 1 -n q@%h
  worker_extract_gemma3:
    command: celery -A interactome worker -Q q.extract.gemma3_12b -c 1 -n g@%h
  worker_extract_deepseek:
    command: celery -A interactome worker -Q q.extract.deepseek_r1_32b -c 1 -n d@%h
  worker_extract_devstral:
    command: celery -A interactome worker -Q q.extract.devstral_24b -c 1 -n v@%h
  worker_extract_llama:
    command: celery -A interactome worker -Q q.extract.llama3_1_8b -c 1 -n l@%h

  flower:
    image: mher/flower:2
    command: celery flower --broker=redis://redis:6379/0 --port=5555

  postgres:
    image: postgres:16
    volumes: [pgdata:/var/lib/postgresql/data]

  redis:
    image: redis:7
    command: redis-server --appendonly yes --save 60 1000
    volumes: [redisdata:/data]

  minio:
    image: minio/minio
    command: server /data --console-address ':9001'
    volumes: [miniodata:/data]

  grobid:
    image: lfoppiano/grobid:0.8.0
    deploy: { resources: { limits: { memory: 6G } } }

  pgbackrest:
    image: pgbackrest/pgbackrest
    volumes: [pgdata:/pgdata:ro, backupdata:/backup]

volumes:
  pgdata: {}
  redisdata: {}
  miniodata: {}
  backupdata: {}
```

**Container count: 16.** Only `caddy` is reachable externally.

### Authelia integration

Caddy `forward_auth` directive talks to existing Authelia. On success,
Authelia sets `Remote-User`, `Remote-Groups`, `Remote-Name`, `Remote-Email`
headers. Caddy forwards to Django; `core.middleware.AutheliaRemoteUserMiddleware`
reads them and sets `request.user`.

Authelia config block to request from Javier:

```yaml
access_control:
  rules:
    - domain: interactome.simbiosys.sb.upf.edu
      policy: one_factor
      subject:
        - "group:simbiosys-lab"
```

DNS: one A record, `interactome.simbiosys.sb.upf.edu` → internal IP.

### Configuration layers

| Layer | Where | Examples |
|---|---|---|
| Code defaults | `interactome/settings/base.py` | safe Django defaults |
| Env overrides | `interactome/settings/{dev,production}.py` | `DEBUG`, `ALLOWED_HOSTS` |
| Secrets | `.env` mounted via compose, `chmod 600`, ignored in git | DB password, NCBI API key, session secret |

### Logging and monitoring

- All containers log to stdout, JSON lines via `structlog`
- Sentry (free tier) catches exceptions from `web` and `worker_*`
- Flower for queue depths and task runtimes
- Grafana + Prometheus deferred to v2

### Backup procedure

Daily 03:00 UTC inside the `pgbackrest` container:

```bash
pgbackrest --stanza=interactome backup --type=incr
pgbackrest --stanza=interactome backup --type=full   # weekly
mc mirror /minio/sbml-artifacts /backup/minio-mirror/
```

Weekly off-host rsync.

### Deploy

```bash
git pull
docker-compose pull
docker-compose build web
docker-compose up -d --no-deps web beat worker_*
```

`web` runs `python manage.py migrate` on startup; gunicorn binds only after
migration completes. Workers wait on `web` health-check.

### Asks for IT (Javier)

1. Host on internal network: Docker installed, ≥ 200 GB disk, ≥ 32 GB RAM,
   port 443 outbound, ports 80/443 inbound from cluster network. Does **not**
   need to be the GPU box.
2. DNS A record `interactome.simbiosys.sb.upf.edu` → host's internal IP.
3. Authelia rule and AD group `simbiosys-lab` (or reuse existing group).

---

## 10. Implementation roadmap

Eight phases. Each ends in a usable artifact.

| Phase | Wk | Deliverable | Apps touched | Risk |
|---|---|---|---|---|
| **0. Foundation** | 1 | `docker-compose up` brings full stack online. Caddy + Authelia working. Django boots, migrates, serves placeholder dashboard. CI runs lint + pytest. | `core`, settings, infra | low |
| **1. Master IDD corpus** | 2–3 | `corpus.refresh_pubmed`, `Paper`/`PaperRelevance` models, full-text fetch, DoCO sectioning, `is_original` classifier, per-network relevance triage, `/corpus/export.csv`, dashboard counters. **End of week 3: 30–40k IDD papers indexed, classified, network-tagged, exportable.** | `core`, `networks`, `corpus`, `papers`, `schedule` | medium — Europe PMC quirks, GROBID memory tuning |
| **2. Extraction pipeline** | 4–6 | Structured PPI prompt template, schema-constrained JSON output via Ollama `format`, 7 per-model Celery workers, rate-limit buckets, janitor. **End: `RawPPI` rows accumulating from all 7 models.** | `extract`, `schedule` | medium — prompt iteration |
| **3. Graph integration** | 7–9 | Gilda grounding, `Entity`/`Edge` models, Bayes belief scoring, conflict detection, `NetworkEdgeMembership`. **End: first per-network graphs queryable, NF-κB axis viewable in dev UI.** | `graph` | high — normalisation edge cases |
| **4. SBML + CSV emission** | 10 | `ModelVersion` snapshots, `sbml.regenerate` task with `libsbml` + MIRIAM, per-version zip. **End: downloadable SBML-qual, importable into GINsim/CellNOpt.** | `sbml` | low |
| **5. Verification UI** | 11–12 | Network grid dashboard, Cytoscape.js graph view, disagreement queue, resolution flow (HTMX), `Review`/`Signoff` models, email notifications. **End: biologist can approve/reject edges.** | `verify`, `dashboard` | medium — UX iteration |
| **6. Continuous monitoring** | 13 | Daily PubMed delta, re-extraction trigger on new evidence, auto-conflict resolver, subscribe-to-network notifications. **End: unattended autonomous operation.** | `schedule` | low |
| **7. Hardening + handoff** | 14–15 | pgbackrest, Sentry, Grafana basics, runbook, biologist onboarding, first sign-off. | infra, docs | low |

### Critical path

Phase 1 unblocks Phase 2 (no corpus → nothing to extract). Phase 3 unblocks
Phase 4 (no graph → no SBML). Phases 4 and 5 can parallelise with two pairs of
hands. Phase 6 needs the whole pipeline working but is mostly glue.

### MVP cut (~8 weeks)

If demoing to the professor faster matters:
- Phase 0–3 stay (foundation, corpus, extraction, graph integration), compressed to 7
- Phase 4 (SBML) merged into Phase 3, simplest libsbml output, no MIRIAM
- Phase 5 (verification UI) reduced to just CSV export
- Phase 6 (continuous monitoring) deferred — one-shot batch run
- Phase 7 deferred

Result in ~8 weeks: working pipeline from PubMed → master corpus → extracted
PPIs → SBML + CSV per network. No verification UI, no continuous monitoring,
but science is end-to-end.

### Risks and mitigations

| Risk | Mitigation |
|---|---|
| Prompt engineering for PPI extraction is harder than estimated → low yield in Phase 2 | Phase 1 produces the corpus first; can spend extra time on prompts without blocking. Use schema-constrained decoding + logprob approach already validated on Pfirrmann grading. |
| Gilda grounding misses too many entities (>30% ungrounded) → sparse graph | Add MetaMap or BERN2 as fallback; allow tiered identifier strictness |
| Compute contested by other groups → extraction stalls | Per-model queues already throttle to 2-models-in-VRAM. Beat-driven pause/resume. |
| Curator bandwidth (biologists) limits verification rate | Auto-conflict resolver handles ~70%; only hard cases reach humans |
| Schema evolution between phases breaks running data | Forward-only migrations, dual-read window, integration tests on a copy of production data |

### Definition of done

1. Biologist navigates to `https://interactome.simbiosys.sb.upf.edu`, logs in via UPF SSO, sees all 200+ networks at a glance.
2. For any network, downloads SBML-qual + edges.csv + evidence.csv, immediately loadable in CellNOpt / GINsim / Cytoscape.
3. New PubMed papers automatically update affected networks within ≤ 24 h, without human action.
4. A network can be marked "verified"; that version is immutable afterwards.
5. Stack survives a hard reboot of the host with zero manual intervention.

---

## Appendix A — The 17-category network taxonomy

The system targets the following network families (200+ specific networks).
Maintained as fixtures in `networks/fixtures/`.

```
I.    Core Signaling Pathway Networks
        NF-κB Axis · TGF-β/BMP/SMAD · Wnt/β-catenin · Notch · Hedgehog
        PI3K/AKT/mTOR · MAPK Cascades · JAK/STAT · Hippo/YAP-TAZ
        Hypoxia/HIF · Oxidative Stress/Redox · cGAS-STING/Innate Immunity
        Autophagy · Apoptosis · Senescence · Cell Death (emerging modalities)
II.   Transcription Factor Networks (Sox9, Brachyury, Foxa1/2, KLF, AP-1, ...)
III.  Epigenetic Regulatory Networks (DNMT/TET, PRC2/EZH2, HDAC, SIRT, ...)
IV.   Non-Coding RNA Networks (miRNA, lncRNA, circRNA/ceRNA)
V.    ECM / Matrix Remodeling Networks (MMP, ADAMTS, TIMP, aggrecan, collagen, ...)
VI.   Growth Factor / Cytokine Networks (IGF-1, FGF, IL-1β, TNF-α, IL-6, ...)
VII.  Metabolic Regulatory Networks (glycolysis, AMPK, mitochondrial, NAD+, ...)
VIII. Mechanobiology Networks (Piezo, TRPV4, integrin, Rho/ROCK, ...)
IX.   Cell Type-Specific Networks (NP, AF, endplate, notochordal, immune/stromal)
X.    Neurovascular Networks (NGF/TrkA, CGRP, VEGF, ...)
XI.   Cell Fate / Differentiation Networks
XII.  Inter-Tissue / Systemic Crosstalk Networks (gut microbiome, adipokine, insulin, ...)
XIII. GWAS / Genetic Regulatory Networks (GDF5, CILP, COL9, ...)
XIV.  Disease-Specific Regulatory Networks (Modic, herniation, painful disc, ...)
XV.   Therapeutic / Regenerative Networks (PRP, MSC, AAV, hydrogel, senolytics)
XVI.  Proteostasis / UPR / Protein Quality Control
XVII. Multi-Omics Integration Networks
```

Full enumeration lives in `networks/fixtures/0001_taxonomy.yaml` and seeds
the `Network` table at first deploy.

---

## Appendix B — External dependencies and accounts needed

| Service | Purpose | Account / key needed |
|---|---|---|
| NCBI E-utilities | PubMed search/fetch | Free API key (10 req/s vs 3) |
| Europe PMC OAI-PMH | Full-text JATS XML | None (public) |
| PubTator3 REST | Entity pre-annotation | None (public) |
| UniProt / HGNC / ChEBI / miRBase | Entity normalisation | None |
| Gilda (local pip) | Grounding | None |
| GROBID (local container) | PDF → TEI XML | None |
| Ollama (cluster) | LLM inference | Authelia gateway (already working) |
| Authelia (cluster) | SSO | Authelia rule + AD group (request from Javier) |
| Sentry SaaS | Error tracking | Free tier account |

---

## Appendix C — Out of scope for v1

Explicitly deferred to avoid scope creep:

- Quantitative kinetic SBML-core export (we ship SBML-qual only — literature
  rarely reports rate constants reliably)
- Spatial transcriptomics / scRNA-seq integration (Category XVII multi-omics
  is in scope as a target network, but the data ingest pipeline for those
  modalities is its own future project)
- Federated learning / cross-institution model sharing
- Public API for third-party tools (consumers can use the SBML files)
- Mobile UI (responsive desktop only)
- i18n (English only)
- Multi-organ extension (the architecture supports it, but disc is the only
  configured organ in v1)
