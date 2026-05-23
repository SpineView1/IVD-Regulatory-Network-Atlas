"""Tests for graph.services edge-belief recomputation and normalize_and_integrate.

Field names used in fixtures match the ACTUAL Phase 1/2 models (authoritative
per reconciliation doc §2/§3):
  - raw_ppi_factory uses: subject=, object=, model_name= (not subject_text, extractor_model)
  - paper_factory uses: publication_date=  (not pub_date)
  - RawPPI FK is ``run`` (not ``extraction_run``)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from graph.models import Edge, EdgeEvidence, Entity
from graph.services import (
    BAYES_PRIOR,
    BELIEF_THRESHOLD_ACCEPTED,
    normalize_and_integrate,
    recompute_edge_belief,
)

# ---------------------------------------------------------------------------
# Task 9: recompute_edge_belief tests
# ---------------------------------------------------------------------------


def test_recompute_belief_with_zero_evidence_equals_prior(
    db,
    il1b_ontology_entity,
    nfkb1_ontology_entity,
):
    src = Entity.objects.create(ontology_entity=il1b_ontology_entity)
    tgt = Entity.objects.create(ontology_entity=nfkb1_ontology_entity)
    e = Edge.objects.create(source=src, target=tgt, relation="activates")
    recompute_edge_belief(e)
    e.refresh_from_db()
    assert e.belief_score == pytest.approx(BAYES_PRIOR, abs=1e-3)


def test_recompute_belief_promotes_to_accepted_with_strong_evidence(
    db,
    il1b_ontology_entity,
    nfkb1_ontology_entity,
    paper_factory,
    chunk_factory,
    raw_ppi_factory,
):
    src = Entity.objects.create(ontology_entity=il1b_ontology_entity)
    tgt = Entity.objects.create(ontology_entity=nfkb1_ontology_entity)
    edge = Edge.objects.create(source=src, target=tgt, relation="activates")

    # 7 models all agree on a single recent paper
    paper = paper_factory(pmid="11111111", year=2025)
    chunk = chunk_factory(paper=paper, text="IL1B activates NFKB1.")
    for model in [
        "qwen3_8b",
        "phi4_14b",
        "gemma3_12b",
        "deepseek_r1_32b",
        "devstral_24b",
        "llama3_1_8b",
        "medgemma_27b",
    ]:
        # Use canonical field names: subject=, object=, model_name= via raw_ppi_factory
        raw = raw_ppi_factory(
            subject="IL1B",
            object="NFKB1",
            relation="activates",
            chunk=chunk,
            model_name=model,
        )
        EdgeEvidence.objects.create(edge=edge, raw_ppi=raw)

    recompute_edge_belief(edge)
    edge.refresh_from_db()
    assert edge.belief_score >= BELIEF_THRESHOLD_ACCEPTED
    assert edge.status == "accepted"
    assert edge.n_supporting_papers == 1
    assert edge.n_models_agreeing == 7


def test_recompute_belief_keeps_candidate_with_weak_evidence(
    db,
    il1b_ontology_entity,
    nfkb1_ontology_entity,
    paper_factory,
    chunk_factory,
    raw_ppi_factory,
):
    src = Entity.objects.create(ontology_entity=il1b_ontology_entity)
    tgt = Entity.objects.create(ontology_entity=nfkb1_ontology_entity)
    edge = Edge.objects.create(source=src, target=tgt, relation="activates")

    paper = paper_factory(pmid="22222222", year=2025)
    chunk = chunk_factory(paper=paper)
    raw = raw_ppi_factory(
        subject="IL1B",
        object="NFKB1",
        relation="activates",
        chunk=chunk,
        model_name="qwen3:8b",
    )
    EdgeEvidence.objects.create(edge=edge, raw_ppi=raw)

    recompute_edge_belief(edge)
    edge.refresh_from_db()
    assert edge.status == "candidate"


def test_recompute_belief_counts_distinct_papers_only(
    db,
    il1b_ontology_entity,
    nfkb1_ontology_entity,
    paper_factory,
    chunk_factory,
    raw_ppi_factory,
):
    """Two RawPPIs from the same paper but different chunks should count as 1 paper."""
    src = Entity.objects.create(ontology_entity=il1b_ontology_entity)
    tgt = Entity.objects.create(ontology_entity=nfkb1_ontology_entity)
    edge = Edge.objects.create(source=src, target=tgt, relation="activates")

    paper = paper_factory(pmid="33333333", year=2025)
    chunk_a = chunk_factory(paper=paper, text="IL1B activates NFKB1.", index=0)
    chunk_b = chunk_factory(paper=paper, text="IL1B activates NFKB1 again.", index=1)
    for chunk in (chunk_a, chunk_b):
        raw = raw_ppi_factory(
            subject="IL1B",
            object="NFKB1",
            relation="activates",
            chunk=chunk,
            model_name="qwen3:8b",
        )
        EdgeEvidence.objects.create(edge=edge, raw_ppi=raw)

    recompute_edge_belief(edge)
    edge.refresh_from_db()
    assert edge.n_supporting_papers == 1  # same paper, two chunks
    assert edge.status == "candidate"  # 1 paper × 1 model → candidate


# ---------------------------------------------------------------------------
# Task 10: normalize_and_integrate tests
# ---------------------------------------------------------------------------


def _fake_ground(text: str) -> object | None:
    """Test stub: maps mention strings to OntologyEntity via in-memory dict."""
    return _fake_ground.table.get(text.strip().upper())  # type: ignore[attr-defined]


_fake_ground.table = {}  # type: ignore[attr-defined]


@pytest.fixture
def gilda_table(il1b_ontology_entity, nfkb1_ontology_entity):
    _fake_ground.table = {  # type: ignore[attr-defined]
        "IL1B": il1b_ontology_entity,
        "IL-1B": il1b_ontology_entity,
        "INTERLEUKIN-1B": il1b_ontology_entity,
        "NFKB1": nfkb1_ontology_entity,
        "NF-KB1": nfkb1_ontology_entity,
    }
    yield
    _fake_ground.table = {}  # type: ignore[attr-defined]


@patch("graph.services.ground_mention", side_effect=_fake_ground)
def test_normalize_creates_entities_and_edge(
    mock_ground,
    db,
    gilda_table,
    paper_factory,
    chunk_factory,
    raw_ppi_factory,
):
    paper = paper_factory(pmid="44444444", year=2025)
    chunk = chunk_factory(paper=paper)
    raw = raw_ppi_factory(
        subject="IL1B",
        object="NFKB1",
        relation="activates",
        chunk=chunk,
    )
    normalize_and_integrate([raw.pk])

    assert Entity.objects.count() == 2
    assert Edge.objects.filter(relation="activates").count() == 1
    edge = Edge.objects.get(relation="activates")
    assert edge.evidence.count() == 1


@patch("graph.services.ground_mention", side_effect=_fake_ground)
def test_normalize_is_idempotent_on_same_raw_ppi(
    mock_ground,
    db,
    gilda_table,
    paper_factory,
    chunk_factory,
    raw_ppi_factory,
):
    paper = paper_factory(pmid="55555555", year=2025)
    chunk = chunk_factory(paper=paper)
    raw = raw_ppi_factory(
        subject="IL1B",
        object="NFKB1",
        relation="activates",
        chunk=chunk,
    )
    normalize_and_integrate([raw.pk])
    normalize_and_integrate([raw.pk])

    assert Edge.objects.count() == 1
    assert EdgeEvidence.objects.count() == 1


@patch("graph.services.ground_mention", side_effect=_fake_ground)
def test_normalize_marks_ungrounded_when_subject_unmappable(
    mock_ground,
    db,
    gilda_table,
    paper_factory,
    chunk_factory,
    raw_ppi_factory,
):
    paper = paper_factory(pmid="66666666", year=2025)
    chunk = chunk_factory(paper=paper)
    raw = raw_ppi_factory(
        subject="UnknownProteinXYZ",
        object="NFKB1",
        relation="activates",
        chunk=chunk,
    )
    normalize_and_integrate([raw.pk])

    raw.refresh_from_db()
    assert raw.ungrounded is True
    assert Edge.objects.count() == 0
    assert EdgeEvidence.objects.count() == 0


@patch("graph.services.ground_mention", side_effect=_fake_ground)
def test_normalize_marks_ungrounded_when_object_unmappable(
    mock_ground,
    db,
    gilda_table,
    paper_factory,
    chunk_factory,
    raw_ppi_factory,
):
    paper = paper_factory(pmid="77777777", year=2025)
    chunk = chunk_factory(paper=paper)
    raw = raw_ppi_factory(
        subject="IL1B",
        object="UnknownProteinXYZ",
        relation="activates",
        chunk=chunk,
    )
    normalize_and_integrate([raw.pk])

    raw.refresh_from_db()
    assert raw.ungrounded is True
    assert Edge.objects.count() == 0


@patch("graph.services.ground_mention", side_effect=_fake_ground)
def test_normalize_dedupes_repeated_evidence(
    mock_ground,
    db,
    gilda_table,
    paper_factory,
    chunk_factory,
    raw_ppi_factory,
):
    """Three RawPPIs from three models on the same chunk -> three EdgeEvidences, one Edge."""
    paper = paper_factory(pmid="88888888", year=2025)
    chunk = chunk_factory(paper=paper)
    raws = [
        raw_ppi_factory(
            subject="IL1B",
            object="NFKB1",
            relation="activates",
            chunk=chunk,
            model_name=m,
        )
        for m in ("qwen3_8b", "phi4_14b", "gemma3_12b")
    ]
    normalize_and_integrate([r.pk for r in raws])

    assert Edge.objects.count() == 1
    assert EdgeEvidence.objects.count() == 3


@patch("graph.services.ground_mention", side_effect=_fake_ground)
def test_normalize_recomputes_belief_after_integration(
    mock_ground,
    db,
    gilda_table,
    paper_factory,
    chunk_factory,
    raw_ppi_factory,
):
    paper = paper_factory(pmid="99999999", year=2025)
    chunk = chunk_factory(paper=paper)
    raws = [
        raw_ppi_factory(
            subject="IL1B",
            object="NFKB1",
            relation="activates",
            chunk=chunk,
            model_name=m,
        )
        for m in (
            "qwen3_8b",
            "phi4_14b",
            "gemma3_12b",
            "deepseek_r1_32b",
            "devstral_24b",
            "llama3_1_8b",
            "medgemma_27b",
        )
    ]
    normalize_and_integrate([r.pk for r in raws])

    edge = Edge.objects.get()
    assert edge.belief_score >= BELIEF_THRESHOLD_ACCEPTED
    assert edge.status == "accepted"


@patch("graph.services.ground_mention", side_effect=_fake_ground)
def test_normalize_emits_edges_integrated_signal(
    mock_ground,
    db,
    gilda_table,
    paper_factory,
    chunk_factory,
    raw_ppi_factory,
):
    """normalize_and_integrate must emit edges_integrated signal with touched_edges."""
    from graph.signals import edges_integrated  # noqa: PLC0415

    received: list[dict] = []

    def handler(sender, touched_edges, raws, **kwargs):
        received.append({"touched_edges": touched_edges, "raws": raws})

    edges_integrated.connect(handler)
    try:
        paper = paper_factory(pmid="60001", year=2025)
        chunk = chunk_factory(paper=paper)
        raw = raw_ppi_factory(subject="IL1B", object="NFKB1", relation="activates", chunk=chunk)
        normalize_and_integrate([raw.pk])
        assert len(received) == 1
        assert isinstance(received[0]["touched_edges"], set)
        assert len(received[0]["touched_edges"]) == 1
    finally:
        edges_integrated.disconnect(handler)


@patch("graph.services.ground_mention", side_effect=_fake_ground)
def test_ungrounded_raw_ppi_never_becomes_edge(
    mock_ground,
    db,
    gilda_table,
    paper_factory,
    chunk_factory,
    raw_ppi_factory,
):
    """Spec tiered-strictness: ungrounded RawPPI NEVER becomes an Edge."""
    paper = paper_factory(pmid="60002", year=2025)
    chunk = chunk_factory(paper=paper)
    # Both subject and object ungrounded
    raw1 = raw_ppi_factory(
        subject="GarbageXYZ",
        object="GarbageABC",
        relation="activates",
        chunk=chunk,
    )
    # Only subject ungrounded
    raw2 = raw_ppi_factory(
        subject="GarbageXYZ",
        object="NFKB1",
        relation="activates",
        chunk=chunk,
    )
    # Only object ungrounded
    raw3 = raw_ppi_factory(
        subject="IL1B",
        object="GarbageABC",
        relation="activates",
        chunk=chunk,
    )
    normalize_and_integrate([raw1.pk, raw2.pk, raw3.pk])

    assert Edge.objects.count() == 0
    assert EdgeEvidence.objects.count() == 0
    for raw in [raw1, raw2, raw3]:
        raw.refresh_from_db()
        assert raw.ungrounded is True


# ---------------------------------------------------------------------------
# Regression: papers with null publication_date must not be excluded from
#             n_supporting_papers (and thus from bayes_belief's paper count).
# ---------------------------------------------------------------------------


def test_recompute_belief_counts_papers_with_null_publication_date(
    db,
    il1b_ontology_entity,
    nfkb1_ontology_entity,
    chunk_factory,
    raw_ppi_factory,
):
    """Two EdgeEvidence rows whose papers BOTH have publication_date=None must yield
    n_supporting_papers == 2 (not 0), and the belief must reflect 2 supporting papers.

    Regression for: n_papers was derived from pmid_to_pubdate, which silently excluded
    papers with no publication_date, causing n_supporting_papers to undercount support.
    """
    from corpus.models import Paper  # noqa: PLC0415
    from graph.services import bayes_belief  # noqa: PLC0415

    src = Entity.objects.create(ontology_entity=il1b_ontology_entity)
    tgt = Entity.objects.create(ontology_entity=nfkb1_ontology_entity)
    edge = Edge.objects.create(source=src, target=tgt, relation="activates")

    # Create two papers with publication_date=None (preprints / ahead-of-print)
    paper_a = Paper.objects.create(
        pmid="70000001",
        doi="10.0/70000001",
        title="Preprint A",
        abstract="",
        publication_date=None,
        is_original=True,
    )
    paper_b = Paper.objects.create(
        pmid="70000002",
        doi="10.0/70000002",
        title="Preprint B",
        abstract="",
        publication_date=None,
        is_original=True,
    )

    chunk_a = chunk_factory(paper=paper_a, text="IL1B activates NFKB1.", index=0)
    chunk_b = chunk_factory(paper=paper_b, text="NFKB1 is activated by IL1B.", index=0)

    raw_a = raw_ppi_factory(
        subject="IL1B",
        object="NFKB1",
        relation="activates",
        chunk=chunk_a,
        model_name="qwen3:8b",
    )
    raw_b = raw_ppi_factory(
        subject="IL1B",
        object="NFKB1",
        relation="activates",
        chunk=chunk_b,
        model_name="qwen3:8b",
    )
    EdgeEvidence.objects.create(edge=edge, raw_ppi=raw_a)
    EdgeEvidence.objects.create(edge=edge, raw_ppi=raw_b)

    recompute_edge_belief(edge)
    edge.refresh_from_db()

    # Must count both PMIDs, not 0
    assert edge.n_supporting_papers == 2

    # Belief must match what bayes_belief returns for 2 papers (recency defaults to 1.0
    # when no dated papers exist)
    expected_belief = bayes_belief(
        n_supporting_papers=2,
        n_models_agreeing=1,
        mean_recency=1.0,
    )
    assert edge.belief_score == pytest.approx(expected_belief, abs=1e-9)
