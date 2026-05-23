"""Tests for sbml.packaging — ZIP bundle + auto-generated README."""
from __future__ import annotations

import io
import zipfile

import pytest

from sbml.packaging import bundle_artifact, generate_readme, zip_filename


def test_zip_filename_format():
    assert zip_filename("nfkb_axis", "0.3.2") == "nfkb_axis_v0.3.2.zip"


def test_bundle_contains_four_files():
    z = bundle_artifact(
        network_code="nfkb_axis",
        semver="0.1.0",
        sbml_bytes=b"<sbml/>",
        edges_csv=b"a,b\n1,2\n",
        evidence_csv=b"x,y\n3,4\n",
        readme_md="# hi",
    )
    with zipfile.ZipFile(io.BytesIO(z)) as zf:
        names = set(zf.namelist())
    assert names == {
        "nfkb_axis_v0.1.0/model.sbml",
        "nfkb_axis_v0.1.0/edges.csv",
        "nfkb_axis_v0.1.0/evidence.csv",
        "nfkb_axis_v0.1.0/README.md",
    }


def test_bundle_preserves_sbml_bytes_exactly():
    sbml = b"<sbml><model id='foo'/></sbml>"
    z = bundle_artifact(
        network_code="nfkb_axis",
        semver="0.1.0",
        sbml_bytes=sbml,
        edges_csv=b"",
        evidence_csv=b"",
        readme_md="",
    )
    with zipfile.ZipFile(io.BytesIO(z)) as zf:
        assert zf.read("nfkb_axis_v0.1.0/model.sbml") == sbml


def test_generate_readme_includes_network_title(db, network, accepted_edges):
    # network.title is the human-readable name (reconciliation; Network has title not name)
    md = generate_readme(
        network=network,
        semver="0.3.2",
        n_species=3,
        n_reactions=2,
        n_edges=2,
        n_papers=5,
        edges=accepted_edges,
    )
    assert network.title in md
    assert "v0.3.2" in md


def test_generate_readme_mentions_loading_tools(db, network, accepted_edges):
    md = generate_readme(
        network=network,
        semver="0.1.0",
        n_species=3,
        n_reactions=2,
        n_edges=2,
        n_papers=5,
        edges=accepted_edges,
    )
    assert "GINsim" in md
    assert "CellNOpt" in md
    assert "Cytoscape" in md


def test_generate_readme_lists_column_schemas(db, network, accepted_edges):
    md = generate_readme(
        network=network,
        semver="0.1.0",
        n_species=3,
        n_reactions=2,
        n_edges=2,
        n_papers=5,
        edges=accepted_edges,
    )
    assert "edges.csv" in md
    assert "evidence.csv" in md
    assert "n_models_agreeing" in md  # column name
    assert "extraction_logprob" in md


def test_generate_readme_includes_citation_block(db, network, accepted_edges):
    md = generate_readme(
        network=network,
        semver="0.1.0",
        n_species=3,
        n_reactions=2,
        n_edges=2,
        n_papers=5,
        edges=accepted_edges,
    )
    assert "## Citation" in md or "## How to cite" in md
