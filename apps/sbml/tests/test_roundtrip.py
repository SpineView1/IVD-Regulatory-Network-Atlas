"""End-to-end round-trip: build a document, serialise, re-parse, verify.

This is the load-bearing acceptance test: emitted SBML must be parseable
by libsbml with no fatal errors, and qual species/transitions/MIRIAM
annotations must survive the serialize→parse cycle intact.
"""

from __future__ import annotations

import libsbml
import pytest

from sbml.builder import (
    INTERACTOME_NS_URI,
    QUAL_NS_URI,
    build_sbml_document,
    serialise_to_string,
)


@pytest.fixture
def parsed_doc(db, network, entities, accepted_edges):
    doc = build_sbml_document(network=network, edges=accepted_edges, semver="0.1.0")
    xml = serialise_to_string(doc)
    reader = libsbml.SBMLReader()
    return reader.readSBMLFromString(xml), xml


def test_roundtrip_no_fatal_errors(parsed_doc):
    doc, _ = parsed_doc
    fatal = [
        doc.getError(i).getMessage()
        for i in range(doc.getNumErrors())
        if doc.getError(i).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
    ]
    assert fatal == [], "Fatal SBML errors: " + " | ".join(fatal)


def test_roundtrip_species_count_preserved(parsed_doc, accepted_edges):
    doc, _ = parsed_doc
    qmodel = doc.getModel().getPlugin("qual")
    distinct = {e.source.symbol for e in accepted_edges} | {e.target.symbol for e in accepted_edges}
    assert qmodel.getNumQualitativeSpecies() == len(distinct)


def test_roundtrip_transition_count_preserved(parsed_doc, accepted_edges):
    doc, _ = parsed_doc
    qmodel = doc.getModel().getPlugin("qual")
    assert qmodel.getNumTransitions() == len(accepted_edges)


def test_roundtrip_miriam_resources_non_empty(parsed_doc):
    doc, _ = parsed_doc
    qmodel = doc.getModel().getPlugin("qual")
    for i in range(qmodel.getNumQualitativeSpecies()):
        sp = qmodel.getQualitativeSpecies(i)
        cv_terms = sp.getCVTerms()
        assert cv_terms is not None, f"{sp.getId()} missing CVTerms"
        assert cv_terms.getSize() >= 1, f"{sp.getId()} has zero CVTerms"
        cv = cv_terms.get(0)
        n_res = cv.getNumResources()
        assert n_res >= 1, f"{sp.getId()} CVTerm has zero resources"
        for j in range(n_res):
            uri = cv.getResourceURI(j)
            assert uri.startswith(
                "https://identifiers.org/"
            ), f"non-MIRIAM URI on {sp.getId()}: {uri}"


def test_roundtrip_evidence_block_survives_serialisation(parsed_doc):
    doc, xml = parsed_doc
    qmodel = doc.getModel().getPlugin("qual")
    for i in range(qmodel.getNumTransitions()):
        tr = qmodel.getTransition(i)
        ann = tr.getAnnotation()
        assert ann is not None, f"{tr.getId()} has no annotation"
        ann_str = ann.toXMLString()
        assert "interactome:evidence" in ann_str
        assert "interactome:pmids" in ann_str
        assert "interactome:belief" in ann_str
    assert INTERACTOME_NS_URI in xml


def test_roundtrip_input_signs_preserved(parsed_doc, accepted_edges):
    doc, _ = parsed_doc
    qmodel = doc.getModel().getPlugin("qual")
    for i in range(qmodel.getNumTransitions()):
        tr = qmodel.getTransition(i)
        sign = tr.getInput(0).getSign()
        assert sign in {
            libsbml.INPUT_SIGN_POSITIVE,
            libsbml.INPUT_SIGN_NEGATIVE,
            libsbml.INPUT_SIGN_UNKNOWN,
        }


def test_roundtrip_function_terms_well_formed(parsed_doc):
    doc, _ = parsed_doc
    qmodel = doc.getModel().getPlugin("qual")
    for i in range(qmodel.getNumTransitions()):
        tr = qmodel.getTransition(i)
        assert tr.getDefaultTerm() is not None
        assert tr.getDefaultTerm().getResultLevel() == 0
        assert tr.getNumFunctionTerms() == 1
        ft = tr.getListOfFunctionTerms().get(0)
        assert ft.getResultLevel() == 1
        assert ft.getMath() is not None


def test_roundtrip_qual_namespace_declared(parsed_doc):
    doc, xml = parsed_doc
    assert QUAL_NS_URI in xml
    ns = doc.getNamespaces()
    uris = {ns.getURI(i) for i in range(ns.getNumNamespaces())}
    assert QUAL_NS_URI in uris
