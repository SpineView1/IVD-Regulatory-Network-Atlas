"""Tests for verify.tasks.auto_resolve.

Uses mocked LLM calls — no live Ollama cluster required.

The Conflict model has edge_a + edge_b (not raw_ppi_a/b). The auto-resolver
derives chunk context from edge_a's EdgeEvidence → RawPPI → ExtractionRun →
Chunk chain.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from corpus.models import Paper
from extract.models import ExtractionRun, RawPPI
from graph.models import Conflict, Edge, EdgeEvidence, Entity
from papers.models import Chunk, Section
from verify.tasks import auto_resolve


@pytest.fixture
def conflict_with_evidence(db):
    """Build a minimal Conflict between two Edges with opposing relations."""
    # Paper + chunk
    paper = Paper.objects.create(pmid=33333333, title="t", abstract="a")
    section = Section.objects.create(
        paper=paper, doco_type="Results", body_text="...", order_index=0
    )
    chunk = Chunk.objects.create(
        section=section,
        text="SIRT1 deacetylates p65 at K310, attenuating NF-κB-driven transcription.",
        chunk_index=0,
        token_count=18,
        char_offset_start=0,
        char_offset_end=72,
    )

    # Entities need OntologyEntity parents — use minimal creation
    from core.models import OntologyEntity

    oe_src = OntologyEntity.objects.create(
        preferred_label="SIRT1",
        entity_type="gene",
        canonical_uri="https://identifiers.org/hgnc:14929",
    )
    oe_tgt = OntologyEntity.objects.create(
        preferred_label="NFKB1",
        entity_type="gene",
        canonical_uri="https://identifiers.org/hgnc:7794",
    )
    e_src = Entity.objects.create(ontology_entity=oe_src)
    e_tgt = Entity.objects.create(ontology_entity=oe_tgt)

    # Two opposite edges
    edge_a = Edge.objects.create(source=e_src, target=e_tgt, relation="inhibits")
    edge_b = Edge.objects.create(source=e_src, target=e_tgt, relation="activates")

    # ExtractionRun + RawPPI supporting edge_a
    run_a = ExtractionRun.objects.create(
        chunk=chunk,
        model_name="medgemma:27b",
        prompt_version="1.0.0",
        status="done",
    )
    ppi_a = RawPPI.objects.create(
        run=run_a,
        subject="SIRT1",
        object="NFKB1",
        relation="inhibits",
        evidence_span="deacetylates p65 at K310",
        evidence_offset_start=0,
        evidence_offset_end=20,
        confidence=0.74,
    )
    EdgeEvidence.objects.create(edge=edge_a, raw_ppi=ppi_a)

    # ExtractionRun + RawPPI supporting edge_b
    run_b = ExtractionRun.objects.create(
        chunk=chunk,
        model_name="phi4:14b",
        prompt_version="1.0.0",
        status="done",
    )
    ppi_b = RawPPI.objects.create(
        run=run_b,
        subject="SIRT1",
        object="NFKB1",
        relation="activates",
        evidence_span="...",
        evidence_offset_start=0,
        evidence_offset_end=3,
        confidence=0.68,
    )
    EdgeEvidence.objects.create(edge=edge_b, raw_ppi=ppi_b)

    return Conflict.objects.create(
        edge_a=edge_a,
        edge_b=edge_b,
        conflict_type="intra_paper",
        resolution_status="open",
    )


@pytest.mark.django_db
class TestAutoResolveHighConfidence:
    @patch("verify.tasks._call_medgemma_for_reread")
    def test_high_confidence_resolves_conflict(self, mock_llm, conflict_with_evidence):
        mock_llm.return_value = {
            "relation": "inhibits",
            "confidence": 0.93,
            "resolving_text": "SIRT1 deacetylates p65 at K310, attenuating NF-κB",
            "reasoning": "Deacetylation of p65 reduces NF-κB transcriptional output.",
        }
        auto_resolve(conflict_with_evidence.id)
        conflict_with_evidence.refresh_from_db()
        assert conflict_with_evidence.resolution_status == "auto_resolved"
        assert conflict_with_evidence.resolved_relation == "inhibits"
        assert "Deacetylation" in conflict_with_evidence.reasoning

    @patch("verify.tasks._call_medgemma_for_reread")
    def test_high_confidence_sets_resolved_at(self, mock_llm, conflict_with_evidence):
        mock_llm.return_value = {
            "relation": "inhibits",
            "confidence": 0.90,
            "resolving_text": "SIRT1 deacetylates",
            "reasoning": "Clear inhibitory mechanism.",
        }
        auto_resolve(conflict_with_evidence.id)
        conflict_with_evidence.refresh_from_db()
        assert conflict_with_evidence.resolved_at is not None
        assert conflict_with_evidence.auto_resolve_attempted_at is not None


@pytest.mark.django_db
class TestAutoResolveLowConfidence:
    @patch("verify.tasks._call_medgemma_for_reread")
    def test_low_confidence_leaves_open(self, mock_llm, conflict_with_evidence):
        mock_llm.return_value = {
            "relation": "context_dependent",
            "confidence": 0.55,
            "resolving_text": "ambiguous wording in chunk",
            "reasoning": "The chunk mixes two cell types; cannot decide.",
        }
        auto_resolve(conflict_with_evidence.id)
        conflict_with_evidence.refresh_from_db()
        assert conflict_with_evidence.resolution_status == "open"
        # reasoning is recorded for the human curator's benefit
        assert "ambiguous" in conflict_with_evidence.reasoning


@pytest.mark.django_db
class TestAutoResolveIdempotency:
    @patch("verify.tasks._call_medgemma_for_reread")
    def test_already_resolved_short_circuits(self, mock_llm, conflict_with_evidence):
        conflict_with_evidence.resolution_status = "auto_resolved"
        conflict_with_evidence.save()
        auto_resolve(conflict_with_evidence.id)
        assert mock_llm.called is False


@pytest.mark.django_db
class TestAutoResolvePromptShape:
    @patch("verify.tasks._call_medgemma_for_reread")
    def test_prompt_contains_chunk_text(self, mock_llm, conflict_with_evidence):
        mock_llm.return_value = {
            "relation": "inhibits",
            "confidence": 0.9,
            "resolving_text": "x",
            "reasoning": "y",
        }
        auto_resolve(conflict_with_evidence.id)
        args, kwargs = mock_llm.call_args
        prompt = kwargs.get("prompt") or (args[0] if args else "")
        assert "SIRT1 deacetylates p65" in prompt
        assert "EXTRACTION A" in prompt
        assert "EXTRACTION B" in prompt
