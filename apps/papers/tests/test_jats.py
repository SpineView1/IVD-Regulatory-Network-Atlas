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


def test_parse_jats_tolerates_comments_and_pis():
    """Real PMC JATS contains XML comments / processing instructions whose
    lxml node .tag is a callable; the parser must not crash on them."""
    from papers.jats import parse_jats

    xml = b"""<?xml version="1.0"?>
    <!-- a top-level comment -->
    <article xmlns:xlink="http://www.w3.org/1999/xlink">
      <?some-pi data?>
      <body>
        <!-- comment inside body -->
        <sec sec-type="results">
          <title>Results</title>
          <p>TNF activates NF-kB in nucleus pulposus cells.</p>
        </sec>
      </body>
    </article>"""
    secs = parse_jats(xml)
    assert any(
        s.heading.lower().startswith("results") or "result" in s.doco_label.lower() for s in secs
    )
    assert any("nucleus pulposus" in s.body_text.lower() for s in secs)
