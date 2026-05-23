"""Tests for the DoCO section-type mapping."""

from __future__ import annotations

from papers.doco import (
    DOCO_IRI_PREFIX,
    map_jats_sec_type,
    map_section_heading,
)


def test_map_jats_results_to_doco_results():
    assert map_jats_sec_type("results") == ("Results", f"{DOCO_IRI_PREFIX}Results")


def test_map_jats_intro_to_doco_introduction():
    assert map_jats_sec_type("intro") == ("Introduction", f"{DOCO_IRI_PREFIX}Introduction")
    assert map_jats_sec_type("introduction") == ("Introduction", f"{DOCO_IRI_PREFIX}Introduction")


def test_map_jats_methods_to_doco_methods():
    assert map_jats_sec_type("methods") == ("Methods", f"{DOCO_IRI_PREFIX}Methods")
    assert map_jats_sec_type("materials|methods") == ("Methods", f"{DOCO_IRI_PREFIX}Methods")


def test_map_jats_discussion_to_doco_discussion():
    assert map_jats_sec_type("discussion") == ("Discussion", f"{DOCO_IRI_PREFIX}Discussion")


def test_map_jats_conclusions_to_doco_conclusion():
    assert map_jats_sec_type("conclusions") == ("Conclusion", f"{DOCO_IRI_PREFIX}Conclusion")


def test_map_jats_unknown_falls_to_other():
    label, iri = map_jats_sec_type("custom-xyz")
    assert label == "Other"
    # doco:Section is the correct catch-all IRI (no doco:Other in the ontology)
    assert iri == f"{DOCO_IRI_PREFIX}Section"


def test_map_jats_none_returns_other():
    label, iri = map_jats_sec_type(None)
    assert label == "Other"


def test_map_section_heading_results():
    assert map_section_heading("Results")[0] == "Results"
    assert map_section_heading("3. Results and discussion")[0] in {"Results", "Discussion"}


def test_map_section_heading_methods():
    assert map_section_heading("Materials and Methods")[0] == "Methods"
    assert map_section_heading("Experimental Procedures")[0] == "Methods"


def test_map_section_heading_introduction():
    assert map_section_heading("Background")[0] == "Introduction"
    assert map_section_heading("Introduction")[0] == "Introduction"
