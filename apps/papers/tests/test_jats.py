"""Tests for papers.jats."""

from __future__ import annotations

from pathlib import Path

from papers.jats import parse_jats

FIXTURE = Path(__file__).parent / "fixtures" / "sample_jats.xml"


def test_parse_jats_returns_sections():
    sections = parse_jats(FIXTURE.read_bytes())
    assert len(sections) >= 4
    labels = [s.doco_label for s in sections]
    assert "Introduction" in labels
    assert "Methods" in labels
    assert "Results" in labels
    assert "Conclusion" in labels


def test_parse_jats_results_includes_text():
    sections = parse_jats(FIXTURE.read_bytes())
    results = [s for s in sections if s.doco_label == "Results"]
    assert len(results) == 1
    assert "HIF1A" in results[0].body_text
    assert "NF" in results[0].body_text


def test_parse_jats_results_includes_subsections():
    sections = parse_jats(FIXTURE.read_bytes())
    results = [s for s in sections if s.doco_label == "Results"][0]
    assert "SOX9" in results.body_text


def test_parse_jats_assigns_doco_iri():
    sections = parse_jats(FIXTURE.read_bytes())
    for s in sections:
        assert s.doco_iri.startswith("http://purl.org/spar/doco/")


def test_parse_jats_assigns_order_index():
    sections = parse_jats(FIXTURE.read_bytes())
    indices = [s.order_index for s in sections]
    assert indices == sorted(indices)
    assert indices[0] == 0


def test_parse_jats_preserves_heading():
    sections = parse_jats(FIXTURE.read_bytes())
    headings = {s.heading for s in sections}
    assert "Introduction" in headings
    assert "Methods" in headings
