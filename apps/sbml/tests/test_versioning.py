"""Tests for sbml.versioning — semver bump rules per spec §7."""

from __future__ import annotations

from sbml.versioning import EdgeSnapshot, bump_semver, diff_edge_sets


def _es(edge_id: int, src: int, tgt: int, rel: str) -> EdgeSnapshot:
    return EdgeSnapshot(edge_id=edge_id, source_id=src, target_id=tgt, relation=rel)


def test_first_ever_version_is_0_1_0() -> None:
    assert (
        bump_semver(prev=None, prev_edges=set(), new_edges={_es(1, 1, 2, "activates")}) == "0.1.0"
    )


def test_no_change_returns_prev_unchanged() -> None:
    s = {_es(1, 1, 2, "activates")}
    assert bump_semver(prev="0.1.0", prev_edges=s, new_edges=s) == "0.1.0"


def test_edges_added_bumps_patch() -> None:
    prev = {_es(1, 1, 2, "activates")}
    new = {_es(1, 1, 2, "activates"), _es(2, 2, 3, "activates")}
    assert bump_semver(prev="0.1.0", prev_edges=prev, new_edges=new) == "0.1.1"


def test_sign_flipped_bumps_minor() -> None:
    prev = {_es(1, 1, 2, "activates")}
    new = {_es(1, 1, 2, "inhibits")}
    assert bump_semver(prev="0.1.0", prev_edges=prev, new_edges=new) == "0.2.0"


def test_edge_rejected_bumps_minor() -> None:
    prev = {_es(1, 1, 2, "activates"), _es(2, 2, 3, "activates")}
    new = {_es(1, 1, 2, "activates")}
    assert bump_semver(prev="0.1.0", prev_edges=prev, new_edges=new) == "0.2.0"


def test_curator_action_bumps_major() -> None:
    prev = {_es(1, 1, 2, "activates")}
    new = {_es(1, 1, 2, "activates"), _es(2, 2, 3, "activates")}
    assert (
        bump_semver(prev="0.1.0", prev_edges=prev, new_edges=new, triggered_by_curator=True)
        == "1.0.0"
    )


def test_curator_action_from_0_x_lands_on_1_0_0() -> None:
    assert (
        bump_semver(prev="0.9.42", prev_edges=set(), new_edges=set(), triggered_by_curator=True)
        == "1.0.0"
    )


def test_curator_action_from_1_x_increments_major() -> None:
    assert (
        bump_semver(prev="1.2.3", prev_edges=set(), new_edges=set(), triggered_by_curator=True)
        == "2.0.0"
    )


def test_minor_bump_resets_patch() -> None:
    prev = {_es(1, 1, 2, "activates"), _es(2, 2, 3, "activates")}
    new = {_es(1, 1, 2, "activates")}
    assert bump_semver(prev="0.1.7", prev_edges=prev, new_edges=new) == "0.2.0"


def test_minor_takes_precedence_over_patch_when_both_apply() -> None:
    prev = {_es(1, 1, 2, "activates")}
    new = {_es(1, 1, 2, "inhibits"), _es(2, 2, 3, "activates")}
    # sign flipped AND a new edge added — minor wins
    assert bump_semver(prev="0.1.0", prev_edges=prev, new_edges=new) == "0.2.0"


def test_diff_edge_sets_classifies_changes() -> None:
    prev = {_es(1, 1, 2, "activates"), _es(2, 2, 3, "activates")}
    new = {_es(1, 1, 2, "inhibits"), _es(3, 3, 4, "activates")}
    diff = diff_edge_sets(prev, new)
    # edge 1 changed sign, edge 2 was removed, edge 3 is new
    assert diff.added == frozenset({_es(3, 3, 4, "activates")})
    assert diff.removed == frozenset({_es(2, 2, 3, "activates")})
    assert {(d.before.edge_id, d.before.relation, d.after.relation) for d in diff.sign_flipped} == {
        (1, "activates", "inhibits")
    }
