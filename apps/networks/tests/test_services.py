"""Tests for networks.services."""

from __future__ import annotations

import pytest

from networks.models import Network
from networks.services import (
    NetworkNotFound,
    get_network,
    list_active_networks,
    networks_by_category,
)


@pytest.fixture
def seeded_networks(db):
    a = Network.objects.create(code="nfkb_axis", category="I", title="NF-κB Axis")
    b = Network.objects.create(code="tgfb_bmp_smad", category="I", title="TGF-β/BMP/SMAD")
    c = Network.objects.create(code="archived_x", category="I", title="Archived", is_active=False)
    return a, b, c


def test_get_network_returns_match(db, seeded_networks):
    n = get_network("nfkb_axis")
    assert n.code == "nfkb_axis"


def test_get_network_unknown_raises(db):
    with pytest.raises(NetworkNotFound):
        get_network("does_not_exist")


def test_list_active_networks_excludes_inactive(db, seeded_networks):
    codes = {n.code for n in list_active_networks()}
    assert "nfkb_axis" in codes
    assert "archived_x" not in codes


def test_networks_by_category_groups(db, seeded_networks):
    by_cat = networks_by_category()
    assert "I" in by_cat
    codes = {n.code for n in by_cat["I"]}
    assert "nfkb_axis" in codes
    assert "tgfb_bmp_smad" in codes
