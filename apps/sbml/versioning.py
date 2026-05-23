"""Semver bump rules per spec §7.

The bump is computed from two edge snapshots: the set generated for the
prior ``ModelVersion`` and the set we are about to write for the new one.

    PATCH  = Edges added; existing signs unchanged; no edges removed
    MINOR  = An edge changed sign, OR an edge was rejected/removed by integration
    MAJOR  = Curator action: edges added/removed manually, or network
             flipped to ``verified``

A change classified as MINOR resets PATCH to 0; a MAJOR resets both.

These are **pure functions** — no DB access, no side-effects.  The
``bump_semver`` function is the spec-level gate; ``diff_edge_sets`` is an
intermediate helper exposed for testing.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EdgeSnapshot:
    """Identity tuple for an edge at a point in time.

    ``edge_id`` lets us pair the same row across versions; the
    ``relation`` field lets us detect sign flips.  ``(source_id,
    target_id)`` is the topological key — an edge that moves from
    ``activates`` to ``inhibits`` has the same topology but a different
    sign.
    """

    edge_id: int
    source_id: int
    target_id: int
    relation: str  # canonical name (edge.relation on the DB model)


@dataclass(frozen=True)
class SignFlip:
    """A single edge whose relation changed between two versions."""

    before: EdgeSnapshot
    after: EdgeSnapshot


@dataclass(frozen=True)
class EdgeDiff:
    """Result of comparing two edge snapshot sets."""

    added: frozenset[EdgeSnapshot] = field(default_factory=frozenset)
    removed: frozenset[EdgeSnapshot] = field(default_factory=frozenset)
    sign_flipped: frozenset[SignFlip] = field(default_factory=frozenset)

    @property
    def is_empty(self) -> bool:
        return not (self.added or self.removed or self.sign_flipped)


def diff_edge_sets(
    prev: set[EdgeSnapshot],
    new: set[EdgeSnapshot],
) -> EdgeDiff:
    """Classify the change between two edge snapshot sets.

    Rules:
    - An edge present only in *new* → ``added``
    - An edge present only in *prev* → ``removed``
    - An edge in both but with a different ``relation`` → ``sign_flipped``
    - An edge in both with the same ``relation`` → unchanged (not returned)
    """
    prev_by_id = {e.edge_id: e for e in prev}
    new_by_id = {e.edge_id: e for e in new}

    added: set[EdgeSnapshot] = set()
    removed: set[EdgeSnapshot] = set()
    flips: set[SignFlip] = set()

    for eid, e_after in new_by_id.items():
        e_before = prev_by_id.get(eid)
        if e_before is None:
            added.add(e_after)
        elif e_before.relation != e_after.relation:
            flips.add(SignFlip(before=e_before, after=e_after))

    for eid, e_before in prev_by_id.items():
        if eid not in new_by_id:
            removed.add(e_before)

    return EdgeDiff(
        added=frozenset(added),
        removed=frozenset(removed),
        sign_flipped=frozenset(flips),
    )


def _parse(semver: str) -> tuple[int, int, int]:
    major, minor, patch = (int(p) for p in semver.split("."))
    return major, minor, patch


def bump_semver(
    *,
    prev: str | None,
    prev_edges: set[EdgeSnapshot],
    new_edges: set[EdgeSnapshot],
    triggered_by_curator: bool = False,
) -> str:
    """Return the next semver string for a ``ModelVersion`` row.

    Behaviour matrix (spec §7):

    +-------------------------+-----------------------+-----------+
    | Trigger                 | Edge-set change       | Bump      |
    +=========================+=======================+===========+
    | First ever version      | (any)                 | 0.1.0     |
    +-------------------------+-----------------------+-----------+
    | Curator action          | (any)                 | MAJOR     |
    +-------------------------+-----------------------+-----------+
    | Auto regenerate         | none                  | unchanged |
    +-------------------------+-----------------------+-----------+
    | Auto regenerate         | only adds             | PATCH     |
    +-------------------------+-----------------------+-----------+
    | Auto regenerate         | sign flip or removal  | MINOR     |
    +-------------------------+-----------------------+-----------+

    When multiple categories apply simultaneously (e.g. sign flip + new
    edge), the highest-severity wins (MINOR > PATCH).
    """
    if prev is None:
        return "0.1.0"

    major, minor, patch = _parse(prev)

    if triggered_by_curator:
        return f"{major + 1}.0.0"

    diff = diff_edge_sets(prev_edges, new_edges)

    if diff.is_empty:
        return prev

    # MINOR takes precedence over PATCH when both apply
    if diff.sign_flipped or diff.removed:
        return f"{major}.{minor + 1}.0"

    # Only additions remain
    if diff.added:
        return f"{major}.{minor}.{patch + 1}"

    return prev  # unreachable — keeps mypy happy
