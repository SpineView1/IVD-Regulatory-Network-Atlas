# Deployment Summary Email — Draft

> **STATUS: DRAFT — DO NOT SEND until the sign-off ceremony has been completed
> and `docs/signoff-ceremony.md` has a recorded ceremony row.**
>
> Fill in the YYYY-MM-DD placeholders and the actual MinIO download URL before
> sending. Send from `francis.chemorion@upf.edu` to the professor.

---

**To:** [Professor's email address]
**From:** francis.chemorion@upf.edu
**Subject:** [Interactome] v1.0.0 deployed — first network signed off

---

Dear Professor,

I am writing to share that the IVD Regulatory Network Atlas has reached its
first production release, v1.0.0, as of YYYY-MM-DD. The system is live at
https://interactome.simbiosys.sb.upf.edu — your UPF SSO account is already
authorised; just log in.

**What is running unattended on the cluster:**

The system continuously monitors PubMed for new disc-disease literature and
passes each new paper through seven Ollama language models in parallel to
extract protein–protein interactions. Cross-model agreement drives belief
scores; edges above the threshold enter the graph.

Highlights at the time of writing:

- The master IDD corpus has indexed approximately 30,000–40,000 PubMed papers,
  each tagged for relevance against the 200+ networks in our taxonomy.
- Seven Ollama models are extracting protein-protein interactions from every
  new paper arriving on the PubMed feed, with cross-model agreement driving
  belief scores.
- The first curated network — NF-κB axis → MMP/ADAMTS catabolic output in
  nucleus pulposus cells (`nfkb_axis_mmp_adamts`) — has been signed off at
  v1.0.0 by the curator-of-record (Francis Chemorion).

The v1.0.0 SBML-qual artifact is downloadable directly:

  https://interactome.simbiosys.sb.upf.edu/networks/nfkb_axis_mmp_adamts/v/1.0.0/download

It contains four files: `nfkb_axis_mmp_adamts.sbml`, `edges.csv`, `evidence.csv`,
and `README.md`. All species and reactions carry MIRIAM-compliant annotations
(UniProt, HGNC, ChEBI identifiers). The SBML is importable into CellNOpt,
GINsim, or Cytoscape.

**Infrastructure:**

The stack runs as 18–20 Docker Compose services on a single cluster host:
PostgreSQL + pgbackrest (daily incremental backups + weekly full + weekly
automated restore-test), Redis, MinIO (object store for SBML artifacts), the
Django application (gunicorn), Celery workers for each extraction model,
Prometheus + Grafana for observability, and Caddy as the TLS-terminating
reverse proxy with Authelia SSO.

**Documentation committed to the repository:**

- Operations runbook (docs/runbook.md) — six named procedures: zero-downtime
  deploy, restore from backup, cluster host failure, Ollama outage, full
  bring-up from clean machine, Authelia/LDAP outage.
- Biologist onboarding guide (docs/onboarding-biologist.md) — access, dashboard
  colour codes, reviewing first edge, sign-off semantics.
- Sign-off ceremony record (docs/signoff-ceremony.md) — NF-κB axis ceremony
  procedure + record of today's run.
- Security review (docs/security-review.md) — Caddy/Authelia/Django hardening.

The full design specification, implementation plans (Phases 0–8), and all code
are at https://github.com/SpineView1/IVD-Regulatory-Network-Atlas (tag v1.0.0).

I would welcome a brief demo at your convenience — please let me know what
window works and I will prepare a walkthrough of the end-to-end pipeline (from
a new PubMed abstract to a downloadable SBML network).

Best regards,
Francis Chemorion
SIMBIOsys, Universitat Pompeu Fabra
francis.chemorion@upf.edu
