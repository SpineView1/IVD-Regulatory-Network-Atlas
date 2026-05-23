"""Tests for networks.models."""

from __future__ import annotations

import pytest
from django.db import IntegrityError

from networks.models import FamilyFilter, Network, NetworkQuery


def test_network_round_trip(db):
    n = Network.objects.create(
        code="nfkb_axis",
        category="I",
        title="NF-κB Axis",
        description="Canonical NF-κB pathway driving catabolic gene expression.",
        is_active=True,
    )
    assert n.pk is not None
    assert n.pipeline_status == "idle"


def test_network_code_is_unique(db):
    Network.objects.create(code="nfkb_axis", category="I", title="NF-κB Axis")
    with pytest.raises(IntegrityError):
        Network.objects.create(code="nfkb_axis", category="I", title="dup")


def test_network_keywords_list(db):
    n = Network.objects.create(
        code="nfkb_axis",
        category="I",
        title="NF-κB Axis",
        keywords=["NF-kB", "RELA", "p65", "IKK"],
    )
    n.refresh_from_db()
    assert "RELA" in n.keywords


def test_network_root_entity_aliases(db):
    n = Network.objects.create(
        code="nfkb_axis",
        category="I",
        title="NF-κB Axis",
        root_entity_aliases=["NFKB1", "NFKB2", "RELA", "RELB"],
    )
    n.refresh_from_db()
    assert "NFKB1" in n.root_entity_aliases


def test_network_pipeline_status_choices(db):
    n = Network.objects.create(code="nfkb_axis", category="I", title="NF-κB Axis")
    for status in ["idle", "refreshing", "stale", "version_draft", "verified"]:
        n.pipeline_status = status
        n.save()
        n.refresh_from_db()
        assert n.pipeline_status == status


def test_network_query_round_trip(db):
    n = Network.objects.create(code="nfkb_axis", category="I", title="NF-κB Axis")
    q = NetworkQuery.objects.create(
        network=n,
        purpose="discovery",
        query='"NF-kB"[TIAB] OR RELA[TIAB]',
    )
    assert q.pk is not None
    assert q.network == n


def test_network_query_purpose_choices(db):
    n = Network.objects.create(code="nfkb_axis", category="I", title="NF-κB Axis")
    for p in ["discovery", "triage_cheap", "expansion"]:
        NetworkQuery.objects.create(network=n, purpose=p, query="x")


def test_family_filter_round_trip(db):
    n = Network.objects.create(code="nfkb_axis", category="I", title="NF-κB Axis")
    f = FamilyFilter.objects.create(
        network=n,
        family_name="NF-kB transcription factors",
        uniprot_family_id="UF000123",
        members=["NFKB1", "NFKB2", "RELA", "RELB", "REL"],
    )
    assert f.pk is not None
    assert "REL" in f.members


def test_network_str(db):
    n = Network.objects.create(code="nfkb_axis", category="I", title="NF-κB Axis")
    assert "nfkb_axis" in str(n)
