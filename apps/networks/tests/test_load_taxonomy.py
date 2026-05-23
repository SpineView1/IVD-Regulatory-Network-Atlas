"""Tests for networks.management.commands.load_network_taxonomy."""

from __future__ import annotations

from io import StringIO

from django.core.management import call_command

from networks.models import Network


def test_load_taxonomy_creates_networks(db):
    call_command("load_network_taxonomy", stdout=StringIO(), stderr=StringIO())
    assert Network.objects.count() >= 170


def test_load_taxonomy_is_idempotent(db):
    call_command("load_network_taxonomy", stdout=StringIO(), stderr=StringIO())
    count_first = Network.objects.count()
    call_command("load_network_taxonomy", stdout=StringIO(), stderr=StringIO())
    assert Network.objects.count() == count_first


def test_load_taxonomy_populates_keywords(db):
    call_command("load_network_taxonomy", stdout=StringIO(), stderr=StringIO())
    n = Network.objects.get(code="nfkb_axis")
    assert isinstance(n.keywords, list)
    assert len(n.keywords) > 0


def test_load_taxonomy_populates_root_aliases(db):
    call_command("load_network_taxonomy", stdout=StringIO(), stderr=StringIO())
    n = Network.objects.get(code="nfkb_axis")
    assert isinstance(n.root_entity_aliases, list)
    assert len(n.root_entity_aliases) > 0


def test_load_taxonomy_categories_use_roman_numerals(db):
    call_command("load_network_taxonomy", stdout=StringIO(), stderr=StringIO())
    categories = set(Network.objects.values_list("category", flat=True))
    roman = {
        "I",
        "II",
        "III",
        "IV",
        "V",
        "VI",
        "VII",
        "VIII",
        "IX",
        "X",
        "XI",
        "XII",
        "XIII",
        "XIV",
        "XV",
        "XVI",
        "XVII",
    }
    assert categories <= roman
