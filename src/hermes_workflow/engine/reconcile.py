from __future__ import annotations
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hermes_workflow.engine.graph import Identity
    from hermes_workflow.engine.model import Template

_STATUS_RANK = {"done": 5, "running": 4, "ready": 3, "todo": 2, "blocked": 1, "archived": 0}
_ARCHIVED = "archived"
_RUNNING = "running"


@dataclass(frozen=True)
class CardRow:
    card_id: str
    status: str
    latest_run_id: int | None = None
    created_at: float = 0.0


def pick_winner(rows: list[CardRow]) -> CardRow:
    """Deterministic winner among duplicates sharing one sentinel identity.
    A 'done' duplicate wins unconditionally (status rank); tiebreak by
    latest_run_id -> created_at -> min(card_id). Falls back to status rank
    when none is 'done'.
    """
    if not rows:
        raise ValueError("pick_winner: no rows")
    # Sort key for min(): negate the higher-is-better fields (status rank, run_id,
    # created_at) so the largest wins; card_id stays plain so the smallest (min) wins.
    return min(rows, key=lambda r: (
        -_STATUS_RANK.get(r.status, 0),
        -(r.latest_run_id if r.latest_run_id is not None else -1),
        -r.created_at,
        r.card_id,
    ))


@dataclass(frozen=True)
class CardNode:
    """A board card projected into exactly what the collapse planner reasons over.

    Built at the ``tools.py`` boundary from a flat card dict; the planner never
    touches the board, so every input it needs travels here: the sentinel
    ``Identity`` (the grouping key), ``status`` and the ``pick_winner`` tiebreak
    keys, and the link edges (``parents``/``children``) used to re-point joins.
    """
    card_id: str
    identity: Identity
    status: str
    latest_run_id: int | None = None
    created_at: float = 0.0
    parents: tuple = ()
    children: tuple = ()


@dataclass(frozen=True)
class CollapsePlan:
    """The board-free description of one duplicate-collapse pass.

    ``relink`` re-points a winner onto a loser's join (``(winner_id, join_id)``,
    parent=winner) and is emitted ONLY for edges that do not already exist;
    ``reclaim`` lists running losers whose worker must be reclaimed BEFORE the
    card is archived; ``archive`` lists every loser to retire. The executor
    applies relink first (a join must keep a live parent before archive's
    ready-sweep runs), then reclaim, then archive — but if any relink fails it
    DEFERS the whole reclaim+archive phase (losers stay live for a self-healing
    retry) rather than archive a join's loser onto a missing winner-edge.
    """
    relink: tuple = ()      # tuple[tuple[str, str]]  (winner_id, join_id)
    archive: tuple = ()     # tuple[str]              loser ids
    reclaim: tuple = ()     # tuple[str]              running loser ids


def _row(node: CardNode) -> CardRow:
    return CardRow(node.card_id, node.status, node.latest_run_id, node.created_at)


def _identity_key(ident) -> tuple:
    return (ident.stage_id, ident.fan_index, ident.attempt)


def _is_join(template: Template, source_ident, child_ident) -> bool:
    """A child is a join of the source iff its stage fans in over the source's stage.

    Mirrors ``reconcile_exec._relink_created_to_joins`` (``source in child_stage.needs``) so
    create-relink and collapse-relink share one join-detection rule. An unknown
    child stage is treated as a non-join (conservative: never re-point blindly).
    """
    try:
        child_stage = template.stage(child_ident.stage_id)
    except KeyError:
        return False
    return source_ident.stage_id in child_stage.needs


def plan_collapse(template: Template, nodes) -> CollapsePlan:
    """Plan the collapse of every sentinel Identity that has more than one live card.

    Pure and total over ``nodes`` (the run's sentinel cards) + the compiled
    ``template``. For each identity with >1 live (non-archived) card it picks a
    deterministic winner (``pick_winner``) and, per loser, emits: a re-point of the
    winner onto each loser JOIN child the winner does not already parent, a reclaim
    if the loser is still running, and the loser's archival. A loser's non-join
    children are left untouched — only a fan-in join must keep a live parent once
    the loser is gone. Never mutates ``nodes``; output ordering is deterministic.
    """
    by_id = {n.card_id: n for n in nodes}
    groups: dict = {}
    for n in nodes:
        groups.setdefault(n.identity, []).append(n)

    relink: list = []
    archive: list = []
    reclaim: list = []
    seen_edges: set = set()
    for ident in sorted(groups, key=_identity_key):
        live = [n for n in groups[ident] if n.status != _ARCHIVED]
        if len(live) < 2:
            continue
        winner = pick_winner([_row(n) for n in live])
        for loser in live:
            if loser.card_id == winner.card_id:
                continue
            for child_id in loser.children:
                join = by_id.get(child_id)
                if join is None or not _is_join(template, loser.identity, join.identity):
                    continue
                edge = (winner.card_id, join.card_id)
                if winner.card_id in join.parents or edge in seen_edges:
                    continue
                seen_edges.add(edge)
                relink.append(edge)
            if loser.status == _RUNNING:
                reclaim.append(loser.card_id)
            archive.append(loser.card_id)
    return CollapsePlan(tuple(sorted(relink)), tuple(sorted(archive)), tuple(sorted(reclaim)))
