# src/hermes_workflow/runview.py
"""RunView: the live picture of a workflow run, read from the board.

Built by link-walking DOWN from the workflow root (``WorkerBoard.show()``
exposes ``children``). For each sentinel-stamped card we recover its
``Identity``, its status, its card id, and — once the stage is done — the
metadata of its latest completed run. That ``completed`` map (stage_id ->
emitted-items metadata) is exactly what the engine graph function reads to
decide fan-out, so RunView is the bridge from board state to the pure engine.
"""
from __future__ import annotations
from dataclasses import dataclass

from hermes_workflow.board import WorkerBoard
from hermes_workflow.engine.graph import Identity
from hermes_workflow.engine.provenance import extract_sentinel

_DONE_STATUS = "done"
_COMPLETED_OUTCOME = "completed"


@dataclass
class RunView:
    existing: set         # set[Identity]
    by_identity: dict     # Identity -> card_id
    status: dict          # card_id -> status str
    completed: dict        # stage_id -> latest-done-run metadata dict
    root_id: str

    def card_id_for(self, ident_tuple):
        """ident_tuple = (stage_id, fan_index, attempt) -> card_id or None."""
        return self.by_identity.get(Identity(*ident_tuple))

    @classmethod
    def from_root(cls, ctx, *, board, root_id, kb=None, conn=None):
        wb = WorkerBoard(ctx, board=board)
        existing: set = set()
        by_identity: dict = {}
        status: dict = {}
        completed: dict = {}

        seen: set = set()
        stack = [root_id]
        while stack:
            cid = stack.pop()
            if cid in seen:
                continue
            seen.add(cid)

            card = wb.show(cid)  # BoardError propagates: a vanished child is a real inconsistency
            # Recurse into children regardless of sentinel (the root has children, no sentinel).
            stack.extend(card.get("children") or [])

            sentinel = extract_sentinel(card.get("body") or "")
            if sentinel is None:
                continue  # not a workflow stage card (e.g. the root)

            ident = Identity(sentinel.stage_id, sentinel.fan_index, sentinel.attempt)
            existing.add(ident)
            by_identity[ident] = cid
            status[cid] = card["status"]

            meta = _latest_done_metadata(card, kb, conn)
            if meta is not None:
                completed[sentinel.stage_id] = meta

        return cls(existing, by_identity, status, completed, root_id)


def _latest_done_metadata(card, kb, conn):
    """Metadata of the stage's latest completed run, or None if not done.

    A not-done stage returns None so the graph treats it as not materialized.
    A done stage with no metadata returns ``{}`` (correct: a non-emit stage has
    no items, and the graph only reads ``completed[src][key]`` for expand
    sources, which DO emit).
    """
    if card.get("status") != _DONE_STATUS:
        return None

    if kb is not None and conn is not None:
        # ``latest_run`` returns the most recent run regardless of outcome, so we
        # must gate on outcome to match the worker-context branch below (which
        # filters runs to ``completed``). This is safe because a workflow stage
        # card is terminal once ``done`` (Hermes finding S: a ``done`` card can
        # only be re-opened via the dashboard, never via the tool/CLI path the
        # workflow uses), so the latest run of a ``done`` card is its completing
        # run. Filtering on ``outcome == _COMPLETED_OUTCOME`` keeps the db path
        # identical in meaning to the worker-context path.
        run = kb.latest_run(conn, card["id"])
        if run is not None and run.outcome == _COMPLETED_OUTCOME:
            return run.metadata or {}
        return {}

    # Worker-context: no db handle -> read the normalized runs list.
    done = [r for r in (card.get("runs") or []) if r.get("outcome") == _COMPLETED_OUTCOME]
    if not done:
        return {}
    latest = max(done, key=lambda r: r.get("id", 0))  # don't assume ordering
    return latest.get("metadata") or {}
