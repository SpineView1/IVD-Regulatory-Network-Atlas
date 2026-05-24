"""Tests for graph.detect_affected_networks."""

from __future__ import annotations

import pytest
from django.db import IntegrityError

from corpus.models import Paper, PaperRelevance
from graph.models import NetworkEdgeMembership
from graph.tasks import detect_affected_networks
from networks.models import Network


@pytest.fixture
def two_networks(db):
    n1 = Network.objects.create(code="nfkb_axis", title="NF-κB")
    n2 = Network.objects.create(code="wnt", title="Wnt")
    return n1, n2


@pytest.fixture
def paper_with_relevance(db, two_networks):
    n1, n2 = two_networks
    p = Paper.objects.create(pmid=11111111, title="t", abstract="a")
    PaperRelevance.objects.create(paper=p, network=n1, score=0.92)
    PaperRelevance.objects.create(paper=p, network=n2, score=0.10)  # below threshold
    return p


@pytest.mark.django_db
def test_detect_marks_only_relevant_networks(paper_with_relevance, two_networks):
    n1, n2 = two_networks
    result = detect_affected_networks(paper_with_relevance.pk)
    assert n1.pk in result["affected_network_ids"]
    assert n2.pk not in result["affected_network_ids"]


@pytest.mark.django_db
def test_detect_creates_membership_rows_with_pending_flag(paper_with_relevance, two_networks):
    n1, _ = two_networks
    detect_affected_networks(paper_with_relevance.pk)
    rows = NetworkEdgeMembership.objects.filter(
        network=n1, pending_paper_id=paper_with_relevance.pk
    )
    assert rows.exists()
    assert all(r.pending_extraction for r in rows)


@pytest.mark.django_db
def test_detect_is_idempotent(paper_with_relevance, two_networks):
    detect_affected_networks(paper_with_relevance.pk)
    detect_affected_networks(paper_with_relevance.pk)
    # Second call must not create duplicate pending rows
    rows = NetworkEdgeMembership.objects.filter(
        pending_paper_id=paper_with_relevance.pk, pending_extraction=True
    )
    assert rows.count() == 1


@pytest.mark.django_db
def test_detect_returns_empty_for_paper_with_no_relevance(db, two_networks):
    p = Paper.objects.create(pmid=22222222, title="t", abstract="a")
    result = detect_affected_networks(p.pk)
    assert result["affected_network_ids"] == []


@pytest.mark.django_db
def test_db_constraint_prevents_duplicate_pending_rows(paper_with_relevance, two_networks):
    """DB-level UniqueConstraint blocks duplicate pending rows for (network, paper).

    This verifies Fix 2: even if app-level get_or_create is bypassed (e.g.
    concurrent workers race), the database will raise IntegrityError rather
    than silently creating a duplicate pending-extraction placeholder.
    """
    n1, _ = two_networks
    p = paper_with_relevance

    # Create the first pending row normally.
    NetworkEdgeMembership.objects.create(
        network=n1,
        pending_paper_id=p.pk,
        pending_extraction=True,
        edge=None,
    )

    # A second insert with the same (network, pending_paper_id, edge=NULL) must fail.
    with pytest.raises(IntegrityError):
        NetworkEdgeMembership.objects.create(
            network=n1,
            pending_paper_id=p.pk,
            pending_extraction=True,
            edge=None,
        )
