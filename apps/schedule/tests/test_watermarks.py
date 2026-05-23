"""Tests for schedule.watermarks helpers."""

from __future__ import annotations

from datetime import date

from schedule.models import Watermark
from schedule.watermarks import (
    advance_watermark,
    get_watermark,
    reset_watermark,
)


def test_get_watermark_creates_if_missing(db):
    wm = get_watermark("pubmed")
    assert wm.source == "pubmed"
    assert wm.last_pmid_seen is None
    assert Watermark.objects.count() == 1


def test_get_watermark_returns_existing(db):
    Watermark.objects.create(source="pubmed", last_pmid_seen=12345)
    wm = get_watermark("pubmed")
    assert wm.last_pmid_seen == 12345
    assert Watermark.objects.count() == 1


def test_advance_watermark_sets_pmid(db):
    wm = advance_watermark("pubmed", last_pmid_seen=39000000)
    assert wm.last_pmid_seen == 39000000


def test_advance_watermark_only_moves_forward(db):
    advance_watermark("pubmed", last_pmid_seen=39000000)
    wm = advance_watermark("pubmed", last_pmid_seen=12345)
    # Lower PMID must NOT regress the watermark
    assert wm.last_pmid_seen == 39000000


def test_advance_watermark_sets_entrez_date(db):
    wm = advance_watermark("pubmed", last_entrez_date=date(2026, 5, 1))
    assert wm.last_entrez_date == date(2026, 5, 1)


def test_advance_watermark_entrez_date_only_moves_forward(db):
    advance_watermark("pubmed", last_entrez_date=date(2026, 5, 1))
    wm = advance_watermark("pubmed", last_entrez_date=date(2025, 1, 1))
    assert wm.last_entrez_date == date(2026, 5, 1)


def test_reset_watermark_clears_fields(db):
    advance_watermark("pubmed", last_pmid_seen=39000000)
    reset_watermark("pubmed")
    wm = Watermark.objects.get(source="pubmed")
    assert wm.last_pmid_seen is None
    assert wm.last_entrez_date is None
    assert wm.resumption_token == ""
