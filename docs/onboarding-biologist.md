# Biologist Curator Onboarding

> **Welcome.** This document walks you through your first 30 minutes as a curator on the IVD Regulatory Network Atlas. By the end of it, you will have logged in, reviewed your first conflicting edge, and understand how the model versions you sign off on flow into the downstream SBML files.

---

## 1. Access

Your account is provisioned through UPF SSO via Authelia. Your IT username (the one you use for UPF email) is your curator identity. No separate password.

1. Open `https://interactome.simbiosys.sb.upf.edu` in a browser.
2. Authelia redirects you to the SSO login page. Sign in with your UPF credentials.
3. After login you land on the dashboard.

**If you see "Access denied":** ask Javier (IT, it.simbiosys@upf.edu) to add you to the AD group `simbiosys-lab`.

---

## 2. The dashboard

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ /dashboard                                                  Francis · Curator│
├─────────────────────────────────────────────────────────────────────────────┤
│  200 Networks  ·  Active corpus 34,127 papers  ·  PubMed +43 last 24h       │
│  Category I — Core Signaling                                                │
│   ▸ NF-κB Axis (7)         [▣▣▣▢▢▢▢]  STALE  · 12 disagreements            │
│   ▸ TGF-β / BMP / SMAD (10) [▣▣▣▣▢▢▢]  REFRESHING                          │
│   ▸ Wnt / β-catenin (5)    [▣▣▣▣▣▢▢]  VERIFIED (v1.2.0)                    │
└─────────────────────────────────────────────────────────────────────────────┘
```

Every network shows three things, left to right:

1. **Name and number** — the network name and how many sub-networks belong to its parent category.
2. **Confidence bar** — `[▣▣▣▢▢▢▢]` is a 7-segment indicator of how much accepted evidence the network has accumulated. More filled segments = more papers, more cross-model agreement, more reviewer sign-off.
3. **Status badge** — one of `IDLE`, `STALE`, `REFRESHING`, `VERSION_DRAFT`, `VERIFIED`, plus the count of open disagreements you can resolve.

### Colour codes

| Colour | Meaning |
|--------|---------|
| **Green** (text/bar) | An edge is `accepted` by the integration step and has reviewer sign-off, OR a network is `VERIFIED` |
| **Amber** | An edge is `candidate` — auto-generated, awaiting review |
| **Red** | A `conflict` — two extractions disagree on direction; needs human resolution |
| **Grey** | An edge is `rejected` — held in the audit trail but excluded from SBML output |

---

## 3. Reviewing your first edge

Click any network with `disagreements` showing — for example "NF-κB Axis · 12 disagreements".

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ /networks/nfkb_axis_mmp_adamts/disagreements                                │
├─────────────────────────────────────────────────────────────────────────────┤
│ ⚠ SIRT1 → NFKB1   (4 models INHIBIT  ·  3 models ACTIVATE)                 │
│   Evidence A: PMID 28456123 "...SIRT1 overexpression deacetylated p65..."   │
│   Evidence B: PMID 32156789 "In pancreatic β-cells, SIRT1 enhanced NF-κB"  │
│   Resolution: ◯ Keep INHIBIT  ◯ Keep ACTIVATE  ◉ Context-dependent (split) │
│   [Approve & continue →]                                                    │
└─────────────────────────────────────────────────────────────────────────────┘
```

For each disagreement you see:

- **The proposed edge** — `SIRT1 → NFKB1` here.
- **How models split** — e.g. "4 models INHIBIT vs 3 models ACTIVATE".
- **The actual evidence sentences** — verbatim from the source paper, with PMID linked.
- **Resolution choices:**
  - **Keep INHIBIT / Keep ACTIVATE** — pick the direction supported by the evidence in NP-cell context.
  - **Context-dependent (split)** — record both directions as separate edges, each gated on cell-type or stimulus annotation. Use this when both findings are real but the paper biology is different.

Click your resolution radio button, then **Approve & continue**. The system writes a `Review` row, updates the `Edge.status` to `accepted` or `rejected`, and shows you the next disagreement.

---

## 4. Sign-off and version semantics

The system maintains semantic versioning for every network:

- **PATCH** (e.g. v0.3.1 → v0.3.2) — auto-generated; edges added, no signs changed
- **MINOR** (e.g. v0.3 → v0.4) — auto-generated; an edge changed sign or was integration-rejected
- **MAJOR** (e.g. v0.x.y → v1.0.0) — **you cut this**; your curator-level sign-off makes a network `VERIFIED`

When you have reviewed all open disagreements and want to publish a curated v1.0.0:

1. Open the network detail page (e.g. `/networks/nfkb_axis_mmp_adamts`).
2. Scroll to the "Versions" panel on the right.
3. Click **Cut MAJOR version (sign off)**.
4. Confirm in the modal — it asks you to acknowledge that "the current draft accurately represents the literature in NP-cell context to the best of my professional judgement."
5. The system creates a `Signoff` row, bumps `ModelVersion.semver` to v1.0.0, regenerates the SBML artifact (~30 seconds), and emails subscribers.

The result is a frozen, immutable `v1.0.0` artifact, downloadable as SBML-qual + edges.csv + evidence.csv from `/networks/<code>/v/1.0.0/download`.

After v1.0.0, the network re-enters `STALE` status whenever new evidence arrives, and a new auto-draft (v1.0.1, v1.1.0, ...) appears for your review.

---

## 5. Subscribing to notifications

To receive an email each time a network you care about gets a new draft:

1. Open `/networks/<code>`.
2. Click the **Subscribe** button next to the network name.
3. You can also subscribe to a whole category from `/dashboard`.

Email goes to your UPF address; unsubscribe links are in every notification.

---

## 6. Common questions

**Q: I disagree with an edge that's already marked accepted. Can I reject it?**
Yes — click the edge in the graph view, then **Reject with comment**. The system records your comment, moves the edge to `rejected`, and bumps the network status to `STALE` so a new draft is regenerated.

**Q: I want to add an edge the LLMs missed.**
Click **Add edge manually** on the network detail page. Provide source HGNC symbol, target HGNC symbol, relation, and a PMID + evidence sentence. The system creates an `Edge` with `provenance='curator'` and your username in the audit trail.

**Q: How do I download the per-network artifact for use in CellNOpt / GINsim?**
On the network detail page, "Downloads" panel: pick SBML-qual, edges.csv, evidence.csv, or the bundled zip. All annotations are MIRIAM-compliant.

**Q: Who else can see my reviews?**
All curators see all reviews. Reviews are append-only and tagged with your username — they're an audit trail.

**Q: What's the difference between STALE and VERSION_DRAFT?**
`STALE` means new evidence has arrived and a re-extraction is queued (automated). `VERSION_DRAFT` means the automated re-extraction has completed and a new draft ModelVersion is waiting for your review and sign-off.

**Q: How long does the automatic extraction cycle take?**
End-to-end: new PubMed paper → extraction (7 models in parallel) → graph integration → new draft ModelVersion is typically under 2 hours for a single-paper increment. Full corpus re-runs (triggered by a taxonomy change) may take 24–48 hours.

---

## 7. Getting help

- **Bug / unexpected behaviour:** francis.chemorion@upf.edu
- **Account / access:** it.simbiosys@upf.edu (Javier)
- **Biology / curation question:** discuss in the weekly SIMBIOsys lab meeting

Welcome aboard.
