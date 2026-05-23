"""sbml public API — called by ``sbml.tasks`` and by Phase 5 views.

External callers must use this module rather than reaching into models
or builder directly (spec §2 boundary discipline).

Real field names (per cross-plan reconciliation):
- edge.relation  (NOT relation_type)
- EdgeSnapshot.relation  (NOT relation_type — see versioning.py)
- raw_ppi.run.chunk.section.paper  (chain via run)
- network.title  (NOT name)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction

from core.storage import ObjectStore
from graph.models import Edge
from networks.models import Network
from sbml import builder, exporters, packaging
from sbml.models import ModelVersion
from sbml.versioning import EdgeSnapshot, bump_semver

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RegenerateResult:
    network_code: str
    semver: str
    created_new_version: bool
    zip_s3_key: str
    n_species: int
    n_reactions: int
    n_edges: int


def regenerate_network(
    *,
    network_id: int,
    triggered_by_curator: bool = False,
) -> RegenerateResult:
    """End-to-end regeneration of one network. Idempotent.

    Pipeline (spec §4 tail):
      1. SELECT accepted edges via NetworkEdgeMembership
      2. Diff vs prior ModelVersion, compute next semver
      3. If unchanged, mark idle and return (no new ModelVersion)
      4. Build SBML, CSVs, README, ZIP
      5. Upload all four to MinIO
      6. Create + freeze new ModelVersion row
      7. Flip network.pipeline_status -> version_draft
      8. Best-effort downstream notification (Phase 5)
    """
    with transaction.atomic():
        network = Network.objects.select_for_update().get(pk=network_id)
        edges = _accepted_edges_for(network)
        new_snapshots = {_snapshot(e) for e in edges}

        prev = ModelVersion.latest_for(network)
        prev_snapshots = _snapshots_from(prev) if prev else set()
        next_semver = bump_semver(
            prev=prev.semver if prev else None,
            prev_edges=prev_snapshots,
            new_edges=new_snapshots,
            triggered_by_curator=triggered_by_curator,
        )

        if prev and next_semver == prev.semver:
            log.info("network %s: no change, staying at v%s", network.code, prev.semver)
            network.pipeline_status = "idle"
            network.save(update_fields=["pipeline_status", "updated_at"])
            return RegenerateResult(
                network_code=network.code,
                semver=prev.semver,
                created_new_version=False,
                zip_s3_key=prev.zip_s3_key,
                n_species=prev.n_species,
                n_reactions=prev.n_reactions,
                n_edges=prev.n_edges,
            )

        # Build artifacts
        doc = builder.build_sbml_document(network=network, edges=edges, semver=next_semver)
        sbml_bytes = builder.serialise_to_string(doc).encode("utf-8")
        edges_csv = exporters.write_edges_csv(edges)
        evidence_csv = exporters.write_evidence_csv(edges)

        n_species = doc.getModel().getPlugin("qual").getNumQualitativeSpecies()
        n_reactions = doc.getModel().getPlugin("qual").getNumTransitions()
        n_papers = _distinct_paper_count(edges)

        readme = packaging.generate_readme(
            network=network,
            semver=next_semver,
            n_species=n_species,
            n_reactions=n_reactions,
            n_edges=len(edges),
            n_papers=n_papers,
            edges=edges,
        )
        zip_bytes = packaging.bundle_artifact(
            network_code=network.code,
            semver=next_semver,
            sbml_bytes=sbml_bytes,
            edges_csv=edges_csv,
            evidence_csv=evidence_csv,
            readme_md=readme,
        )

        # Upload to MinIO (ObjectStore instantiated directly for testability;
        # see Batch A note: monkeypatch ObjectStore instance, not singleton)
        store = ObjectStore()
        bucket = settings.MINIO_BUCKET_SBML
        store.ensure_bucket(bucket)
        prefix = f"{network.code}/v{next_semver}"
        sbml_key = f"{prefix}/model.sbml"
        edges_key = f"{prefix}/edges.csv"
        evidence_key = f"{prefix}/evidence.csv"
        zip_key = f"{prefix}/{packaging.zip_filename(network.code, next_semver)}"

        store.upload_bytes(bucket, sbml_key, sbml_bytes, content_type="application/xml")
        store.upload_bytes(bucket, edges_key, edges_csv, content_type="text/csv")
        store.upload_bytes(bucket, evidence_key, evidence_csv, content_type="text/csv")
        store.upload_bytes(bucket, zip_key, zip_bytes, content_type="application/zip")

        # Persist the snapshot row
        mv = ModelVersion.objects.create(
            network=network,
            semver=next_semver,
            n_species=n_species,
            n_reactions=n_reactions,
            n_edges=len(edges),
            sbml_s3_key=sbml_key,
            csv_s3_key=edges_key,
            evidence_csv_s3_key=evidence_key,
            zip_s3_key=zip_key,
        )
        mv.generated_from_edges.set(edges)
        mv.freeze()

        network.pipeline_status = "version_draft"
        network.save(update_fields=["pipeline_status", "updated_at"])

        log.info(
            "network %s: created v%s with %d species, %d transitions",
            network.code,
            next_semver,
            n_species,
            n_reactions,
        )

    # Best-effort downstream notification (Phase 5) — outside atomic block
    try:
        from verify.services import notify_subscribers  # type: ignore[import-not-found]

        notify_subscribers(network=network, model_version=mv)
    except Exception:
        log.exception("verify.notify hook failed for %s v%s", network.code, next_semver)

    return RegenerateResult(
        network_code=network.code,
        semver=next_semver,
        created_new_version=True,
        zip_s3_key=zip_key,
        n_species=n_species,
        n_reactions=n_reactions,
        n_edges=len(edges),
    )


def _accepted_edges_for(network: Network) -> list[Edge]:
    """All accepted Edges in this Network's membership, joined for builder
    and exporters. ``select_related`` keeps the builder from N+1-querying
    Entity rows; ``prefetch_related`` does the same for evidence.

    Chain for evidence: edge → EdgeEvidence → RawPPI → ExtractionRun → Chunk
                        → Section → Paper
    """
    return list(
        Edge.objects.filter(
            status="accepted",
            network_memberships__network=network,
        )
        .select_related(
            "source__ontology_entity",
            "target__ontology_entity",
        )
        .prefetch_related(
            "evidence__raw_ppi__run__chunk__section__paper",
            "source__ontology_entity__identifiers",
            "target__ontology_entity__identifiers",
        )
        .order_by(
            "source__ontology_entity__preferred_label",
            "target__ontology_entity__preferred_label",
            "id",
        )
        .distinct()
    )


def _snapshot(edge: Edge) -> EdgeSnapshot:
    return EdgeSnapshot(
        edge_id=edge.id,
        source_id=edge.source_id,
        target_id=edge.target_id,
        relation=edge.relation,  # real field name (NOT relation_type)
    )


def _snapshots_from(mv: ModelVersion) -> set[EdgeSnapshot]:
    return {
        EdgeSnapshot(
            edge_id=e.id,
            source_id=e.source_id,
            target_id=e.target_id,
            relation=e.relation,  # real field name
        )
        for e in mv.generated_from_edges.all()
    }


def _distinct_paper_count(edges: list[Edge]) -> int:
    pmids: set[object] = set()
    for e in edges:
        for ev in e.evidence.all():
            try:
                pmid = ev.raw_ppi.run.chunk.section.paper.pmid
                if pmid is not None:
                    pmids.add(pmid)
            except AttributeError:
                pass
    return len(pmids)
