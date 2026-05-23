"""Tests for graph.services conflict detection.

Uses canonical field names per reconciliation doc:
  - raw_ppi_factory uses: subject=, object=, model_name=
  - RawPPI FK is raw_ppi.run (not extraction_run)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from graph.models import Conflict
from graph.services import (
    OPPOSITE_RELATIONS,
    detect_inter_model_conflicts,
    detect_inter_paper_conflicts,
    detect_intra_paper_conflicts,
)


def _fake_ground(text: str) -> object | None:
    return _fake_ground.table.get(text.strip().upper())  # type: ignore[attr-defined]


_fake_ground.table = {}  # type: ignore[attr-defined]


@pytest.fixture
def gilda_table(il1b_ontology_entity, nfkb1_ontology_entity):
    _fake_ground.table = {  # type: ignore[attr-defined]
        "IL1B": il1b_ontology_entity,
        "NFKB1": nfkb1_ontology_entity,
    }
    yield
    _fake_ground.table = {}  # type: ignore[attr-defined]


def test_opposite_relations_covers_core_pairs():
    assert OPPOSITE_RELATIONS["activates"] == "inhibits"
    assert OPPOSITE_RELATIONS["inhibits"] == "activates"
    assert OPPOSITE_RELATIONS["phosphorylates"] == "dephosphorylates"
    assert OPPOSITE_RELATIONS["transcribes"] == "represses"


@patch("graph.services.ground_mention", side_effect=_fake_ground)
def test_intra_paper_conflict_when_two_models_disagree_on_one_chunk(
    mock_ground,
    db,
    gilda_table,
    paper_factory,
    chunk_factory,
    raw_ppi_factory,
):
    from graph.services import normalize_and_integrate  # noqa: PLC0415

    paper = paper_factory(pmid="30001", year=2025)
    chunk = chunk_factory(paper=paper)
    raw_act = raw_ppi_factory(
        subject="IL1B",
        object="NFKB1",
        relation="activates",
        chunk=chunk,
        model_name="qwen3:8b",
    )
    raw_inh = raw_ppi_factory(
        subject="IL1B",
        object="NFKB1",
        relation="inhibits",
        chunk=chunk,
        model_name="phi4:14b",
    )
    normalize_and_integrate([raw_act.pk, raw_inh.pk])

    # normalize_and_integrate calls _post_integrate_hook which calls detectors.
    # But calling explicitly again should be idempotent.
    detect_intra_paper_conflicts([raw_act.pk, raw_inh.pk])

    conflicts = Conflict.objects.filter(conflict_type="intra_paper")
    assert conflicts.count() == 1
    c = conflicts.first()
    assert c is not None
    assert {c.edge_a.relation, c.edge_b.relation} == {"activates", "inhibits"}
    assert c.resolution_status == "open"


@patch("graph.services.ground_mention", side_effect=_fake_ground)
def test_no_intra_paper_conflict_when_relations_agree(
    mock_ground,
    db,
    gilda_table,
    paper_factory,
    chunk_factory,
    raw_ppi_factory,
):
    from graph.services import normalize_and_integrate  # noqa: PLC0415

    paper = paper_factory(pmid="30002")
    chunk = chunk_factory(paper=paper)
    r1 = raw_ppi_factory(
        subject="IL1B",
        object="NFKB1",
        relation="activates",
        chunk=chunk,
        model_name="qwen3:8b",
    )
    r2 = raw_ppi_factory(
        subject="IL1B",
        object="NFKB1",
        relation="activates",
        chunk=chunk,
        model_name="phi4:14b",
    )
    normalize_and_integrate([r1.pk, r2.pk])
    detect_intra_paper_conflicts([r1.pk, r2.pk])

    assert Conflict.objects.count() == 0


@patch("graph.services.ground_mention", side_effect=_fake_ground)
def test_inter_paper_conflict_when_different_papers_disagree(
    mock_ground,
    db,
    gilda_table,
    paper_factory,
    chunk_factory,
    raw_ppi_factory,
):
    from graph.services import normalize_and_integrate  # noqa: PLC0415

    paper_a = paper_factory(pmid="30003")
    paper_b = paper_factory(pmid="30004")
    chunk_a = chunk_factory(paper=paper_a)
    chunk_b = chunk_factory(paper=paper_b)

    r_act = raw_ppi_factory(
        subject="IL1B",
        object="NFKB1",
        relation="activates",
        chunk=chunk_a,
        model_name="qwen3:8b",
    )
    r_inh = raw_ppi_factory(
        subject="IL1B",
        object="NFKB1",
        relation="inhibits",
        chunk=chunk_b,
        model_name="qwen3:8b",
    )
    normalize_and_integrate([r_act.pk, r_inh.pk])

    detect_inter_paper_conflicts([r_act.pk, r_inh.pk])

    conflicts = Conflict.objects.filter(conflict_type="inter_paper")
    assert conflicts.count() == 1


@patch("graph.services.ground_mention", side_effect=_fake_ground)
def test_inter_model_conflict_when_consensus_below_majority(
    mock_ground,
    db,
    gilda_table,
    paper_factory,
    chunk_factory,
    raw_ppi_factory,
):
    from graph.services import normalize_and_integrate  # noqa: PLC0415

    paper = paper_factory(pmid="30005")
    chunk = chunk_factory(paper=paper)
    # 4 models say activate, 3 say inhibit → 4/7 is below consensus threshold of 5
    raws_act = [
        raw_ppi_factory(
            subject="IL1B",
            object="NFKB1",
            relation="activates",
            chunk=chunk,
            model_name=m,
        )
        for m in ("qwen3_8b", "phi4_14b", "gemma3_12b", "deepseek_r1_32b")
    ]
    raws_inh = [
        raw_ppi_factory(
            subject="IL1B",
            object="NFKB1",
            relation="inhibits",
            chunk=chunk,
            model_name=m,
        )
        for m in ("devstral_24b", "llama3_1_8b", "medgemma_27b")
    ]
    normalize_and_integrate([r.pk for r in raws_act + raws_inh])

    detect_inter_model_conflicts([r.pk for r in raws_act + raws_inh])
    assert Conflict.objects.filter(conflict_type="inter_model").count() == 1


@patch("graph.services.ground_mention", side_effect=_fake_ground)
def test_no_inter_model_conflict_when_consensus_at_or_above_threshold(
    mock_ground,
    db,
    gilda_table,
    paper_factory,
    chunk_factory,
    raw_ppi_factory,
):
    from graph.services import normalize_and_integrate  # noqa: PLC0415

    paper = paper_factory(pmid="30006")
    chunk = chunk_factory(paper=paper)
    # 6 vs 1 → well above threshold, no conflict
    raws_act = [
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
        )
    ]
    raw_inh = raw_ppi_factory(
        subject="IL1B",
        object="NFKB1",
        relation="inhibits",
        chunk=chunk,
        model_name="medgemma_27b",
    )
    normalize_and_integrate([r.pk for r in raws_act + [raw_inh]])

    detect_inter_model_conflicts([r.pk for r in raws_act + [raw_inh]])
    assert Conflict.objects.filter(conflict_type="inter_model").count() == 0


@patch("graph.services.ground_mention", side_effect=_fake_ground)
def test_conflict_detection_is_idempotent(
    mock_ground,
    db,
    gilda_table,
    paper_factory,
    chunk_factory,
    raw_ppi_factory,
):
    from graph.services import normalize_and_integrate  # noqa: PLC0415

    paper = paper_factory(pmid="30007")
    chunk = chunk_factory(paper=paper)
    r_act = raw_ppi_factory(
        subject="IL1B",
        object="NFKB1",
        relation="activates",
        chunk=chunk,
        model_name="qwen3:8b",
    )
    r_inh = raw_ppi_factory(
        subject="IL1B",
        object="NFKB1",
        relation="inhibits",
        chunk=chunk,
        model_name="phi4:14b",
    )
    normalize_and_integrate([r_act.pk, r_inh.pk])
    detect_intra_paper_conflicts([r_act.pk, r_inh.pk])
    detect_intra_paper_conflicts([r_act.pk, r_inh.pk])

    assert Conflict.objects.filter(conflict_type="intra_paper").count() == 1
