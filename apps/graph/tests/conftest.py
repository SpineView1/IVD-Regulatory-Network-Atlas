"""Shared fixtures for graph tests.

Provides minimal stand-ins for Phase 1/2 models so the graph tests can
exercise normalize_and_integrate without depending on the full corpus
pipeline.

NOTE: Field names match the ACTUAL Phase 1/2 models, not the stale plan body:
  - Paper.publication_date (not pub_date)
  - ExtractionRun.model_name (not extractor_model)
  - RawPPI.subject / .object (not subject_text / object_text)
  - RawPPI.run (not extraction_run)
  - RawPPI.evidence_offset_start/end (not evidence_span_start/end)
  - Section.order_index (not order), Section.body_text (not raw_xml)
  - Chunk uses char_offset_start/end + token_count (not char_start/end)
"""

from __future__ import annotations

from datetime import date

import pytest

from core.models import Identifier, OntologyEntity


@pytest.fixture
def il1b_ontology_entity(db):
    e = OntologyEntity.objects.create(entity_type="protein", preferred_label="IL1B")
    Identifier.objects.create(entity=e, scheme="HGNC", value="5992", is_primary=True)
    return e


@pytest.fixture
def nfkb1_ontology_entity(db):
    e = OntologyEntity.objects.create(entity_type="protein", preferred_label="NFKB1")
    Identifier.objects.create(entity=e, scheme="HGNC", value="7794", is_primary=True)
    return e


@pytest.fixture
def sirt1_ontology_entity(db):
    e = OntologyEntity.objects.create(entity_type="protein", preferred_label="SIRT1")
    Identifier.objects.create(entity=e, scheme="HGNC", value="14929", is_primary=True)
    return e


@pytest.fixture
def paper_factory(db):
    """Build minimal Paper rows using the real Phase 1 model."""
    from corpus.models import Paper  # noqa: PLC0415

    def _make(*, pmid: str, year: int = 2024, title: str = "Test paper"):
        return Paper.objects.create(
            pmid=pmid,
            doi=f"10.0/{pmid}",
            title=title,
            abstract="",
            publication_date=date(year, 1, 1),  # canonical field name
            is_original=True,
        )

    return _make


@pytest.fixture
def chunk_factory(db, paper_factory):
    from papers.models import Chunk, Section  # noqa: PLC0415

    def _make(*, paper=None, text: str = "IL1B activates NFKB1.", index: int = 0):
        paper = paper or paper_factory(pmid=str(abs(hash(text)) % 999999 + 1))
        section, _ = Section.objects.get_or_create(
            paper=paper,
            order_index=0,
            defaults={
                "doco_type": "Results",
                "body_text": text,
                "token_count": len(text.split()),
            },
        )
        return Chunk.objects.create(
            section=section,
            paper=paper,
            chunk_index=index,
            text=text,
            token_count=len(text.split()),
            char_offset_start=0,
            char_offset_end=len(text),
        )

    return _make


@pytest.fixture
def raw_ppi_factory(db, chunk_factory):
    from extract.models import ExtractionRun, RawPPI  # noqa: PLC0415

    def _make(
        *,
        subject: str,
        object: str,
        relation: str = "activates",
        chunk=None,
        model_name: str = "qwen3:8b",
        confidence: float = 0.9,
    ):
        chunk = chunk or chunk_factory()
        run, _ = ExtractionRun.objects.get_or_create(
            chunk=chunk,
            model_name=model_name,  # canonical field name
            prompt_version="v1",
            defaults={"status": "done"},
        )
        return RawPPI.objects.create(
            run=run,  # canonical FK name
            subject=subject,  # canonical field name
            object=object,  # canonical field name
            relation=relation,
            evidence_span=chunk.text,
            evidence_offset_start=0,  # canonical field name
            evidence_offset_end=len(chunk.text),  # canonical field name
            confidence=confidence,
            ungrounded=False,
        )

    return _make
