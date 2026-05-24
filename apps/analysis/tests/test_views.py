"""Tests for the analysis explorer views (FakeGraphBackend via settings)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from django.test import Client


@pytest.fixture
def authed_client() -> Client:
    return Client(HTTP_REMOTE_USER="fchemorion")


@pytest.fixture
def patch_services_backend(projected_atlas):
    """Make every services.get_backend() call return the projected atlas."""
    with patch("analysis.services.get_backend", return_value=projected_atlas):
        yield projected_atlas


def test_explorer_page_renders(db, authed_client, settings):
    settings.ANALYSIS_GRAPH_BACKEND = "fake"
    r = authed_client.get("/analysis/")
    assert r.status_code == 200
    assert b"cytoscape" in r.content.lower()
    assert b"htmx" in r.content.lower()


def test_neighborhood_json(db, authed_client, accepted_edge, patch_services_backend):
    r = authed_client.get(f"/analysis/neighborhood.json?entity_id={accepted_edge.source_id}&k=1")
    assert r.status_code == 200
    data = r.json()
    assert "nodes" in data and "edges" in data
    assert len(data["edges"]) == 1


def test_crosstalk_json(db, authed_client, patch_services_backend):
    r = authed_client.get("/analysis/crosstalk.json?network_a=nfkb_axis&network_b=nfkb_axis")
    assert r.status_code == 200
    assert "edges" in r.json()


def test_paths_json_shortest(db, authed_client, accepted_edge, patch_services_backend):
    r = authed_client.get(
        f"/analysis/paths.json?source={accepted_edge.source_id}"
        f"&target={accepted_edge.target_id}&mode=shortest&max_len=3"
    )
    assert r.status_code == 200
    assert isinstance(r.json()["paths"], list)


def test_analysis_panel_partial_is_htmx(db, authed_client, patch_services_backend):
    r = authed_client.get("/analysis/panel/?measure=pagerank&max_len=4")
    assert r.status_code == 200
    # Returns an HTML fragment (no <html> shell) suitable for hx-target swap.
    assert b"<html" not in r.content.lower()
    assert b"Centrality" in r.content or b"centrality" in r.content


def test_neighborhood_json_requires_entity_id(db, authed_client, settings):
    settings.ANALYSIS_GRAPH_BACKEND = "fake"
    r = authed_client.get("/analysis/neighborhood.json")
    assert r.status_code == 400
