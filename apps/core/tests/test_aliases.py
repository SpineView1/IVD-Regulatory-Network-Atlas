"""Tests for core.aliases — colloquial mention → official symbol mapping."""

from __future__ import annotations

import pytest

from core.aliases import alias_for


@pytest.mark.parametrize(
    ("mention", "expected"),
    [
        ("Collagen II", "COL2A1"),
        ("type II collagen", "COL2A1"),
        ("collagen type ii", "COL2A1"),
        ("Collagen I", "COL1A1"),
        ("Collagen X", "COL10A1"),
        ("aggrecan", "ACAN"),
        ("Wnt 3a", "WNT3A"),
        ("Wnt 3α", "WNT3A"),  # Greek-letter form transliterates to the same key
        ("WNT-3A", "WNT3A"),
        # batch 2
        ("LAMP2A", "LAMP2"),
        ("Tie2", "TEK"),
        ("Tie-2", "TEK"),
        ("ASIC1a", "ASIC1"),
        ("cleaved caspase-3", "CASP3"),
        ("caspase-3", "CASP3"),
        ("cleaved caspase-1", "CASP1"),
        ("miR-191-5p", "MIR191"),
    ],
)
def test_known_aliases_resolve(mention, expected):
    assert alias_for(mention) == expected


@pytest.mark.parametrize("mention", ["MMP13", "SOX9", "totally-unknown-thing", "", "   "])
def test_unknown_or_clean_mentions_return_none(mention):
    # Clean symbols and unknown text are left to the raw grounder (None here).
    assert alias_for(mention) is None


def test_lookup_is_case_and_punctuation_insensitive():
    assert alias_for("  COLLAGEN   type-II  ") == "COL2A1"


import pytest as _pytest
from core.aliases import mirna_symbol


@_pytest.mark.parametrize(
    ("mention", "expected"),
    [
        ("miR-191-5p", "MIR191"),
        ("miR-21", "MIR21"),
        ("hsa-miR-191-5p", "MIR191"),
        ("microRNA-140", "MIR140"),
        ("miR-29a", "MIR29A"),
        ("miR-200b-3p", "MIR200B"),
        ("miR140", "MIR140"),
    ],
)
def test_mirna_symbol_normalizes(mention, expected):
    assert mirna_symbol(mention) == expected


@_pytest.mark.parametrize("mention", ["MMP13", "circVMA21", "let-7a", "LINC00638", "miR", "", "SOX9"])
def test_mirna_symbol_ignores_non_mirna(mention):
    # Conservative: only canonical miR-<number> mentions match; everything else None.
    assert mirna_symbol(mention) is None
