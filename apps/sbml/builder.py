"""SBML-qual document builder.

Builds the exact XML structure shown in spec §7. The libsbml API is
verbose so this module is intentionally linear:

    create document
      → create model
        → create compartments (from Entity.compartment values)
        → create qual species (one per Entity)
            → attach CVTerm(bqbiol:is) with identifiers.org URIs
        → create transitions (one per Edge)
            → inputs (with sign) + outputs (assignmentLevel)
            → function terms (default 0, then 1 when input ≥ 1)
            → custom interactome:evidence annotation block

The custom evidence block uses an XMLNode tree (libsbml's
``XMLNode.convertStringToXMLNode``) appended as an annotation, so the
file stays standard-compliant — tools that don't know our namespace
simply ignore the block (spec §7 explicit requirement).

Real field names (per cross-plan reconciliation):
- edge.relation  (NOT relation_type)
- network.title  (NOT name)
- raw_ppi.run.chunk.section.paper.pmid  (chain via run, NOT raw_ppi.chunk)
- raw_ppi.evidence_offset_start/end  (NOT evidence_span_start/end)
"""

from __future__ import annotations

import re
from typing import Any
from xml.sax.saxutils import escape as xml_escape

import libsbml

SBML_LEVEL = 3
SBML_VERSION = 1
QUAL_NS_URI = "http://www.sbml.org/sbml/level3/version1/qual/version1"
INTERACTOME_NS_URI = "https://interactome.simbiosys.sb.upf.edu/ns/evidence/1.0"

POSITIVE_RELATIONS = frozenset(
    {
        "activates",
        "phosphorylates",
        "induces",
        "upregulates",
        "promotes",
        "ubiquitinates",
        "methylates",
        "acetylates",
        "transcribes",
    }
)
NEGATIVE_RELATIONS = frozenset(
    {
        "inhibits",
        "dephosphorylates",
        "represses",
        "downregulates",
        "degrades",
        "deubiquitinates",
        "deacetylates",
        "cleaves",
    }
)
NEUTRAL_RELATIONS = frozenset(
    {
        "binds",
        "interacts_with",
        "co_expresses",
        "complexes_with",
        "regulates",
    }
)


class SbmlBuildError(RuntimeError):
    pass


def sign_for_relation(relation: str) -> str:
    """Map a graph relation to a qual:sign attribute string.

    Returns "positive", "negative", or "unknown".
    Raises ValueError for unrecognised relations.
    """
    if relation in POSITIVE_RELATIONS:
        return "positive"
    if relation in NEGATIVE_RELATIONS:
        return "negative"
    if relation in NEUTRAL_RELATIONS:
        return "unknown"
    raise ValueError(f"Unknown relation for SBML sign: {relation!r}")


def _sign_constant(relation: str) -> int:
    s = sign_for_relation(relation)
    return {
        "positive": libsbml.INPUT_SIGN_POSITIVE,
        "negative": libsbml.INPUT_SIGN_NEGATIVE,
        "unknown": libsbml.INPUT_SIGN_UNKNOWN,
    }[s]


def _safe_sid(raw: str) -> str:
    """SBML SIds: letter (or _), then letter/digit/_; max length 256."""
    out = re.sub(r"[^A-Za-z0-9_]", "_", raw)
    if not out or not (out[0].isalpha() or out[0] == "_"):
        out = "_" + out
    return out[:256]


def _check(code: int, what: str) -> None:
    if code != libsbml.LIBSBML_OPERATION_SUCCESS:
        raise SbmlBuildError(f"libsbml call {what} returned {code}")


def build_sbml_document(*, network: Any, edges: Any, semver: str) -> libsbml.SBMLDocument:
    """Build the full SBML-qual document. Returns the libsbml.SBMLDocument
    object; serialise it with ``serialise_to_string``.

    Args:
        network: ``networks.Network`` instance (provides code + title)
        edges: iterable of ``graph.Edge`` rows (must be ``.status='accepted'``)
        semver: target version string, used in ``model.id``
    """
    sbmlns = libsbml.SBMLNamespaces(SBML_LEVEL, SBML_VERSION, "qual", 1)
    doc = libsbml.SBMLDocument(sbmlns)
    _check(doc.setPackageRequired("qual", True), "setPackageRequired(qual)")

    model = doc.createModel()
    model_id = _safe_sid(f"{network.code}_v{semver.replace('.', '_')}")
    _check(model.setId(model_id), "model.setId")
    # network.title is the human-readable name (reconciliation §8)
    _check(model.setName(network.title), "model.setName")

    # ---- Compartments ----
    entities = _collect_entities(edges)
    compartments = sorted({e.compartment or "cytoplasm" for e in entities})
    for comp_id in compartments:
        c = model.createCompartment()
        _check(c.setId(_safe_sid(comp_id)), f"compartment[{comp_id}].setId")
        _check(c.setConstant(True), "compartment.setConstant")
        _check(c.setSpatialDimensions(3), "compartment.setSpatialDimensions")
        _check(c.setSize(1.0), "compartment.setSize")

    # ---- Qual species ----
    qmodel = model.getPlugin("qual")
    if qmodel is None:
        raise SbmlBuildError("qual plugin not loaded on model")

    for entity in entities:
        sp = qmodel.createQualitativeSpecies()
        sid = _safe_sid(entity.symbol)
        _check(sp.setId(sid), f"species[{sid}].setId")
        _check(sp.setName(entity.symbol), "species.setName")
        _check(
            sp.setCompartment(_safe_sid(entity.compartment or "cytoplasm")),
            "species.setCompartment",
        )
        _check(sp.setMaxLevel(1), "species.setMaxLevel")
        _check(sp.setInitialLevel(0), "species.setInitialLevel")
        _check(sp.setConstant(False), "species.setConstant")

        # MIRIAM annotations: bqbiol:is → identifiers.org URIs
        sp.setMetaId(f"meta_{sid}")
        if entity.miriam_uris:
            cv = libsbml.CVTerm()
            cv.setQualifierType(libsbml.BIOLOGICAL_QUALIFIER)
            cv.setBiologicalQualifierType(libsbml.BQB_IS)
            for uri in entity.miriam_uris:
                cv.addResource(uri)
            _check(sp.addCVTerm(cv), "species.addCVTerm")

    # ---- Transitions ----
    for i, edge in enumerate(edges):
        tr = qmodel.createTransition()
        tid = _safe_sid(f"t_{i}_{edge.source.symbol}_{edge.target.symbol}")
        _check(tr.setId(tid), f"transition[{tid}].setId")

        inp = tr.createInput()
        _check(inp.setId(_safe_sid(f"{tid}_in")), "input.setId")
        _check(
            inp.setQualitativeSpecies(_safe_sid(edge.source.symbol)),
            "input.setQualitativeSpecies",
        )
        # edge.relation is the real field name (reconciliation override)
        _check(inp.setSign(_sign_constant(edge.relation)), "input.setSign")
        _check(
            inp.setTransitionEffect(libsbml.INPUT_TRANSITION_EFFECT_NONE),
            "input.setTransitionEffect",
        )

        out = tr.createOutput()
        _check(out.setId(_safe_sid(f"{tid}_out")), "output.setId")
        _check(
            out.setQualitativeSpecies(_safe_sid(edge.target.symbol)),
            "output.setQualitativeSpecies",
        )
        _check(
            out.setTransitionEffect(libsbml.OUTPUT_TRANSITION_EFFECT_ASSIGNMENT_LEVEL),
            "output.setTransitionEffect",
        )

        default = tr.createDefaultTerm()
        _check(default.setResultLevel(0), "defaultTerm.setResultLevel")

        ft = tr.createFunctionTerm()
        _check(ft.setResultLevel(1), "functionTerm.setResultLevel")
        math_str = (
            "<math xmlns='http://www.w3.org/1998/Math/MathML'>"
            f"<apply><geq/><ci>{_safe_sid(edge.source.symbol)}</ci>"
            "<cn type='integer'>1</cn></apply>"
            "</math>"
        )
        math_ast = libsbml.readMathMLFromString(math_str)
        if math_ast is None:
            raise SbmlBuildError(f"failed to parse MathML for {tid}")
        _check(ft.setMath(math_ast), "functionTerm.setMath")

        _attach_evidence_annotation(tr, edge)

    return doc


def _collect_entities(edges: Any) -> list[Any]:
    seen: dict[int, object] = {}
    for e in edges:
        seen.setdefault(e.source_id, e.source)
        seen.setdefault(e.target_id, e.target)
    return sorted(seen.values(), key=lambda e: e.symbol)


def _attach_evidence_annotation(transition: Any, edge: Any) -> None:
    """Attach the custom interactome:evidence block to a transition.

    Tools that don't understand our namespace will silently ignore it
    (spec §7). We build the XMLNode tree directly so libsbml emits it
    inside the transition's <annotation> element verbatim.
    """
    pmids = _gather_pmids(edge)
    reviewer = "true" if _has_reviewer_signoff(edge) else "false"

    xml = (
        f'<interactome:evidence xmlns:interactome="{INTERACTOME_NS_URI}">'
        f"<interactome:pmids>{xml_escape(','.join(pmids))}</interactome:pmids>"
        f"<interactome:belief>{edge.belief_score:.4f}</interactome:belief>"
        f"<interactome:n_models_agree>{edge.n_models_agreeing}</interactome:n_models_agree>"
        f"<interactome:n_supporting_papers>{edge.n_supporting_papers}</interactome:n_supporting_papers>"
        f"<interactome:reviewer_signoff>{reviewer}</interactome:reviewer_signoff>"
        f"</interactome:evidence>"
    )
    node = libsbml.XMLNode.convertStringToXMLNode(xml)
    if node is None:
        raise SbmlBuildError(f"failed to parse evidence annotation XML for edge {edge.id}")
    _check(transition.appendAnnotation(node), "transition.appendAnnotation")


def _gather_pmids(edge: Any) -> list[str]:
    """Distinct PMIDs supporting this edge, sorted ascending.

    Chain: EdgeEvidence → RawPPI → ExtractionRun → Chunk → Section → Paper
    (raw_ppi.run.chunk.section.paper.pmid per reconciliation doc)

    Iterates ``edge.evidence.all()`` to reuse the prefetch cache populated by
    ``_accepted_edges_for``'s ``prefetch_related("evidence__raw_ppi__run__chunk
    __section__paper")``.  Using ``values_list(...)`` would bypass the cache
    and issue a fresh query per edge (N+1).
    """
    seen: set[str] = set()
    for ev in edge.evidence.all():
        try:
            pmid = ev.raw_ppi.run.chunk.section.paper.pmid
            if pmid is not None:
                seen.add(str(pmid))
        except AttributeError:
            pass
    return sorted(seen)


def _has_reviewer_signoff(edge: Any) -> bool:
    """True if at least one Review row exists with action='approve'.

    Phase 5 will populate Review rows; if the model isn't installed yet
    we tolerate any exception and return False.
    """
    try:
        return edge.reviews.filter(action="approve").exists()
    except Exception:
        return False


def serialise_to_string(doc: libsbml.SBMLDocument) -> str:
    """Serialise the document to a self-contained XML string."""
    writer = libsbml.SBMLWriter()
    writer.setProgramName("interactome")
    writer.setProgramVersion("phase-4")
    return writer.writeSBMLToString(doc)
