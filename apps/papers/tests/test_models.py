"""Tests for papers.models."""

from __future__ import annotations

import pytest
from django.db import IntegrityError

from papers.models import Chunk, PaperClassification, Section


def test_section_round_trip(db, paper):
    s = Section.objects.create(
        paper=paper,
        order_index=2,
        doco_type="Results",
        doco_iri="http://purl.org/spar/doco/Results",
        heading="Results",
        body_text="Hypoxia upregulated HIF1A.",
        token_count=12,
    )
    assert s.pk is not None


def test_section_ordered_by_index(db, paper):
    Section.objects.create(paper=paper, order_index=2, doco_type="Results", body_text="b")
    Section.objects.create(paper=paper, order_index=1, doco_type="Introduction", body_text="a")
    Section.objects.create(paper=paper, order_index=3, doco_type="Conclusions", body_text="c")
    ordered = list(paper.sections.all())
    assert [s.order_index for s in ordered] == [1, 2, 3]


def test_section_paper_index_unique(db, paper):
    Section.objects.create(paper=paper, order_index=1, doco_type="Results", body_text="a")
    with pytest.raises(IntegrityError):
        Section.objects.create(paper=paper, order_index=1, doco_type="Methods", body_text="b")


def test_chunk_round_trip(db, paper):
    s = Section.objects.create(paper=paper, order_index=1, doco_type="Results", body_text="abc")
    c = Chunk.objects.create(
        section=s,
        chunk_index=0,
        text="Hypoxia upregulated HIF1A.",
        token_count=8,
        char_offset_start=0,
        char_offset_end=27,
    )
    assert c.pk is not None
    assert c.paper_id == paper.pmid  # denormalised FK for fast filters


def test_chunk_paper_chunk_index_unique(db, paper):
    s = Section.objects.create(paper=paper, order_index=1, doco_type="Results", body_text="x")
    Chunk.objects.create(
        section=s, chunk_index=0, text="a", token_count=1, char_offset_start=0, char_offset_end=1
    )
    with pytest.raises(IntegrityError):
        Chunk.objects.create(
            section=s,
            chunk_index=0,
            text="b",
            token_count=1,
            char_offset_start=0,
            char_offset_end=1,
        )


def test_chunk_processed_by_models_default_empty(db, paper):
    s = Section.objects.create(paper=paper, order_index=1, doco_type="Results", body_text="x")
    c = Chunk.objects.create(
        section=s, chunk_index=0, text="x", token_count=1, char_offset_start=0, char_offset_end=1
    )
    assert c.processed_by_models == []


def test_paper_classification_round_trip(db, paper):
    pc = PaperClassification.objects.create(
        paper=paper,
        is_original=True,
        confidence=0.92,
        classifier="rule:pubtype",
        reason="No 'Review' in publication_types",
    )
    assert pc.pk is not None


def test_paper_classification_one_per_paper(db, paper):
    PaperClassification.objects.create(
        paper=paper, is_original=True, confidence=0.9, classifier="rule:pubtype"
    )
    with pytest.raises(IntegrityError):
        PaperClassification.objects.create(
            paper=paper, is_original=False, confidence=0.9, classifier="llm:qwen3:8b"
        )


def test_chunk_save_with_update_fields_persists_paper_id(db, paper):
    """When update_fields is passed and paper_id is not yet set, the save()
    override must add 'paper' to update_fields so the denormalised FK is
    written to the database (not silently omitted).
    """
    s = Section.objects.create(paper=paper, order_index=1, doco_type="Results", body_text="x")
    # Create chunk fully so it has a PK (paper_id will be auto-set on first save).
    c = Chunk.objects.create(
        section=s,
        chunk_index=0,
        text="initial text",
        token_count=2,
        char_offset_start=0,
        char_offset_end=12,
    )
    # Simulate a caller that resets paper_id and saves with explicit update_fields.
    c.paper_id = None  # type: ignore[assignment]
    c.text = "updated text"
    c.save(update_fields=["text"])
    c.refresh_from_db()
    assert (
        c.paper_id == paper.pmid
    ), "paper_id must be persisted even when update_fields=['text'] is passed"
