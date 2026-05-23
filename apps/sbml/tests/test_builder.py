"""Tests for sbml.builder — libsbml-driven document construction."""
from __future__ import annotations

import libsbml
import pytest

from sbml.builder import (
    INTERACTOME_NS_URI,
    QUAL_NS_URI,
    SBML_LEVEL,
    SBML_VERSION,
    build_sbml_document,
    serialise_to_string,
    sign_for_relation,
)


def test_sign_for_relation_maps_known_types():
    assert sign_for_relation("activates") == "positive"
    assert sign_for_relation("phosphorylates") == "positive"
    assert sign_for_relation("inhibits") == "negative"
    assert sign_for_relation("dephosphorylates") == "negative"
    assert sign_for_relation("binds") == "unknown"


def test_sign_for_relation_raises_on_unknown():
    with pytest.raises(ValueError):
        sign_for_relation("frobnicates")


def test_build_document_returns_libsbml_document(db, network, entities, accepted_edges):
    doc = build_sbml_document(network=network, edges=accepted_edges, semver="0.1.0")
    assert isinstance(doc, libsbml.SBMLDocument)
    assert doc.getLevel() == SBML_LEVEL
    assert doc.getVersion() == SBML_VERSION


def test_document_declares_qual_namespace(db, network, entities, accepted_edges):
    doc = build_sbml_document(network=network, edges=accepted_edges, semver="0.1.0")
    pkg = doc.getPlugin("qual")
    assert pkg is not None
    # getPkgURI not available in this libsbml version; check via SBMLNamespaces instead
    ns = doc.getNamespaces()
    uris = {ns.getURI(i) for i in range(ns.getNumNamespaces())}
    assert QUAL_NS_URI in uris


def test_document_model_has_one_species_per_entity(db, network, entities, accepted_edges):
    doc = build_sbml_document(network=network, edges=accepted_edges, semver="0.1.0")
    model_plugin = doc.getModel().getPlugin("qual")
    assert model_plugin.getNumQualitativeSpecies() == 3  # IL1B, NFKB1, MMP13


def test_document_model_has_one_transition_per_edge(db, network, entities, accepted_edges):
    doc = build_sbml_document(network=network, edges=accepted_edges, semver="0.1.0")
    model_plugin = doc.getModel().getPlugin("qual")
    assert model_plugin.getNumTransitions() == 2


def test_species_carry_miriam_annotations(db, network, entities, accepted_edges):
    doc = build_sbml_document(network=network, edges=accepted_edges, semver="0.1.0")
    species = doc.getModel().getPlugin("qual").getQualitativeSpecies("IL1B")
    cv_terms = species.getCVTerms()
    assert cv_terms is not None
    assert cv_terms.getSize() >= 1
    cv = cv_terms.get(0)
    assert cv.getBiologicalQualifierType() == libsbml.BQB_IS
    resources = {cv.getResourceURI(i) for i in range(cv.getNumResources())}
    assert "https://identifiers.org/uniprot:P01584" in resources
    assert "https://identifiers.org/hgnc:5992" in resources


def test_transition_has_correct_input_output(db, network, entities, accepted_edges):
    doc = build_sbml_document(network=network, edges=accepted_edges, semver="0.1.0")
    transitions = doc.getModel().getPlugin("qual").getListOfTransitions()
    tr = transitions.get(0)
    assert tr.getNumInputs() == 1
    assert tr.getNumOutputs() == 1
    inp = tr.getInput(0)
    out = tr.getOutput(0)
    assert inp.getQualitativeSpecies() in {"IL1B", "NFKB1"}
    assert out.getQualitativeSpecies() in {"NFKB1", "MMP13"}


def test_transition_sign_set_from_relation(db, network, entities, accepted_edges):
    doc = build_sbml_document(network=network, edges=accepted_edges, semver="0.1.0")
    transitions = doc.getModel().getPlugin("qual").getListOfTransitions()
    for i in range(transitions.size()):
        tr = transitions.get(i)
        sign = tr.getInput(0).getSign()
        assert sign == libsbml.INPUT_SIGN_POSITIVE


def test_transition_function_terms_have_default_and_active(db, network, entities, accepted_edges):
    doc = build_sbml_document(network=network, edges=accepted_edges, semver="0.1.0")
    tr = doc.getModel().getPlugin("qual").getListOfTransitions().get(0)
    assert tr.getDefaultTerm() is not None
    assert tr.getDefaultTerm().getResultLevel() == 0
    assert tr.getNumFunctionTerms() == 1
    ft = tr.getListOfFunctionTerms().get(0)
    assert ft.getResultLevel() == 1


def test_compartments_built_from_entity_metadata(db, network, entities, accepted_edges):
    doc = build_sbml_document(network=network, edges=accepted_edges, semver="0.1.0")
    model = doc.getModel()
    comps = {model.getCompartment(i).getId() for i in range(model.getNumCompartments())}
    assert {"extracellular", "nucleus"}.issubset(comps)


def test_serialised_xml_contains_interactome_evidence(db, network, entities, accepted_edges):
    doc = build_sbml_document(network=network, edges=accepted_edges, semver="0.1.0")
    xml = serialise_to_string(doc)
    assert INTERACTOME_NS_URI in xml
    assert "interactome:evidence" in xml
    assert "interactome:belief" in xml
    assert "interactome:n_models_agree" in xml


def test_serialised_xml_is_valid_sbml(db, network, entities, accepted_edges):
    doc = build_sbml_document(network=network, edges=accepted_edges, semver="0.1.0")
    xml = serialise_to_string(doc)
    # Re-parse and validate
    reader = libsbml.SBMLReader()
    doc2 = reader.readSBMLFromString(xml)
    n_errors = doc2.getNumErrors()
    # Errors with severity ERROR or FATAL fail us; warnings are allowed
    fatal = [
        doc2.getError(i)
        for i in range(n_errors)
        if doc2.getError(i).getSeverity() >= libsbml.LIBSBML_SEV_ERROR
    ]
    assert fatal == [], "\n".join(e.getMessage() for e in fatal)


def test_model_id_is_safe_sbml_sid(db, network, entities, accepted_edges):
    doc = build_sbml_document(network=network, edges=accepted_edges, semver="0.3.2")
    # Model id must be a valid SBML SId: no dots, no hyphens
    assert doc.getModel().getId() == "nfkb_axis_mmp_adamts_v0_3_2"
