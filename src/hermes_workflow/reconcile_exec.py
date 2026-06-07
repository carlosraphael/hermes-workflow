# src/hermes_workflow/reconcile_exec.py
"""Board-execution glue for the pure duplicate-collapse planner.

These helpers *apply* the board-free engine (``engine/reconcile.py::plan_collapse``)
against the live Kanban board: link-walk the run, project flat card dicts into the
engine's ``CardNode`` value objects, then execute the returned plan
(relink -> reclaim -> archive). ``_host_board`` is the single sanctioned host-side
connection opener (``kanban_db.connect_closing``; closes the FD on exit —
Hermes #33159). Consumed by ``tools.py`` (``workflow_reconcile`` / ``workflow_abandon``).
"""
import contextlib

from hermes_workflow.board import BoardError, HostBoard, WorkerBoard
from hermes_workflow.engine.provenance import extract_sentinel
from hermes_workflow.engine.reconcile import CardNode, plan_collapse


def _relink_created_to_joins(wb, t, created, rv):
    """Link each freshly-created card to any pre-existing downstream join.

    materialize wires a created card to its PARENTS; a pre-existing join that
    fans in over the created card's stage is NOT recreated, so its edge to the
    new card is missing. We add it (kanban_link demotes a `ready` join to `todo`).
    Each join's current parents are fetched once and cached.
    """
    parents_of = {}        # join_cid -> set(parent_cids), fetched once per join
    relinked = []
    for ident, child_cid in created.items():
        for s in t.stages:
            if ident.stage_id not in s.needs:
                continue
            for join_ident in [i for i in rv.existing if i.stage_id == s.id]:
                join_cid = rv.by_identity.get(join_ident)
                if not join_cid:
                    continue
                if join_cid not in parents_of:
                    parents_of[join_cid] = set(wb.show(join_cid).get("parents") or [])
                if child_cid not in parents_of[join_cid]:
                    wb.link(child_cid, join_cid)        # link(parent=created child, child=join)
                    parents_of[join_cid].add(child_cid)  # keep cache consistent
                    relinked.append((child_cid, join_cid))
    return relinked


@contextlib.contextmanager
def _host_board(board, kb, conn):
    """Yield a HostBoard for the host-only kb.* ops (archive/reclaim — Hermes finding Y).

    A caller-supplied kb/conn (tests) is used as-is and NOT closed (the caller owns it).
    Otherwise open a host connection via connect_closing, which closes the FD on exit
    (Hermes #33159 — bare connect() leaks FDs in long-lived orchestrator processes).
    """
    if kb is not None and conn is not None:
        yield HostBoard(kb, conn, board)
        return
    from hermes_cli import kanban_db as _kb
    with _kb.connect_closing(board=board) as opened:
        yield HostBoard(_kb, opened, board)


def _enumerate_cards(ctx, board, root_id):
    """Link-walk the run from the root, returning every sentinel-stamped card dict.

    Keeps ALL cards (including archived ones): the collapse planner must see the
    full duplicate set per identity and each loser's join children to decide what
    to re-point. The root (no sentinel) is walked for its children but excluded.
    """
    wb = WorkerBoard(ctx, board=board)
    cards, seen, stack = [], set(), [root_id]
    while stack:
        cid = stack.pop()
        if cid in seen:
            continue
        seen.add(cid)
        card = wb.show(cid)
        stack.extend(card.get("children") or [])
        if extract_sentinel(card.get("body") or "") is None:
            continue
        cards.append(card)
    return cards


def _card_node(card):
    """Project a flat board card dict into the engine's CardNode value object."""
    from hermes_workflow.engine.graph import Identity
    s = extract_sentinel(card.get("body") or "")
    runs = card.get("runs") or []
    latest = max((r.get("id", 0) for r in runs), default=None)
    return CardNode(
        card_id=card["id"],
        identity=Identity(s.stage_id, s.fan_index, s.attempt),
        status=card.get("status"),
        latest_run_id=latest,
        created_at=card.get("created_at") or 0.0,
        parents=tuple(card.get("parents") or []),
        children=tuple(card.get("children") or []),
    )


def _collapse_duplicates(ctx, board, root_id, wb, t, kb, conn):
    """Plan duplicate-collapse purely (``plan_collapse``), then apply the plan.

    The engine decides winner / relink edges / reclaim / archive over board-free
    CardNodes; this executor only applies them. Relink runs FIRST so each join
    keeps a live winner-parent before any archive triggers a ready-sweep; if ANY
    relink fails the retire phase is DEFERRED (losers stay live, next reconcile
    retries) so a join is never archived off its loser onto a missing winner-edge.
    Otherwise running losers are reclaimed before archival (a detached worker
    outlives its card). Every op is failure-isolated into ``failures`` (best-effort,
    like abandon). Returns ``(archived_ids, failures)``.
    """
    nodes = [_card_node(c) for c in _enumerate_cards(ctx, board, root_id)]
    plan = plan_collapse(t, nodes)
    if not plan.archive:
        return [], []

    failures = []
    for winner_id, join_id in plan.relink:
        try:
            wb.link(winner_id, join_id)   # link(parent=winner, child=join)
        except BoardError as e:           # best-effort: isolate per-edge failure
            failures.append({"card": join_id, "op": "relink", "error": str(e)})

    # A failed relink means a winner is NOT yet parenting some join. Archiving any
    # loser now would let archive's ready-sweep (kanban recompute_ready) promote that
    # join off its archived (== satisfied) loser-parent with no live producer. Defer
    # the WHOLE retire phase: losers stay live, so the next reconcile re-plans the
    # collapse cleanly (idempotent). Dedup is best-effort — one rare deferral is safe.
    if failures:
        return [], failures

    archived = []
    with _host_board(board, kb, conn) as hb:
        for loser_id in plan.reclaim:     # reclaim running losers before archiving
            try:
                hb.reclaim(loser_id)
            except Exception as e:
                failures.append({"card": loser_id, "op": "reclaim", "error": str(e)})
        for loser_id in plan.archive:
            try:
                hb.archive(loser_id)
                archived.append(loser_id)
            except Exception as e:
                failures.append({"card": loser_id, "op": "archive", "error": str(e)})
    return archived, failures
