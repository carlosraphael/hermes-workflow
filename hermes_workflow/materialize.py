# hermes_workflow/materialize.py
"""Materializer: turn engine CardSpecs into real board cards (the Phase-2 heart).

Given a workflow root and a live ``RunView``, recompile the template from the
root's snapshot, ask the engine which cards SHOULD exist up to the next dynamic
boundary (``cards_for_run`` already excludes identities that exist), then create
exactly those cards — each stamped with a provenance sentinel and a lifecycle
preamble, with worktree workspaces pre-provisioned into provisioned ``dir``
workspaces, and joins wired atomically to ALL their instance parents (R5).

Idempotent: a second call with a refreshed RunView creates nothing new, because
the engine omits already-existing identities and ``create`` carries a
deterministic idempotency key.
"""
from __future__ import annotations

import hashlib

from hermes_workflow.board import WorkerBoard
from hermes_workflow.engine.graph import cards_for_run
from hermes_workflow.engine.provenance import (
    Sentinel,
    embed_sentinel,
    parse_root_body,
)
from hermes_workflow.engine.template import parse_template
from hermes_workflow.version import PLUGIN_VERSION, SCHEMA_VERSION
from hermes_workflow.worktree import provision_worktree

class MaterializeError(RuntimeError):
    """A spec's parent identities never resolved to real cards (engine/board bug)."""


# A child whose parents are created earlier in the SAME pass is retried by
# re-queuing it; this caps the topo-drain loop so a (theoretically impossible)
# unresolvable parent can never spin forever — leftover pending then fails loud.
_MAX_PASSES = 10_000
_IDEM_LEN = 16
_WORKTREE_KIND = "worktree"
_DIR_KIND = "dir"
_SCRATCH_KIND = "scratch"

LIFECYCLE_PREAMBLE = (
    "## workflow stage\n"
    "- Complete via `kanban_complete` (even a no-op stage must complete, with empty metadata).\n"
    "- Emit the declared metadata when this stage feeds a fan-out.\n"
    "- Commit your work before completing (worktree stages are commit-checked).\n"
    "- Do NOT `kanban_block` for review — the workflow's human gate handles approval.\n\n"
)


def materialize(ctx, *, board, root_id, runview, base_ref=None) -> dict:
    """Create the cards the engine says should exist; return {Identity: card_id}.

    Immutability: never mutates ``runview``, the snapshot, or a CardSpec's
    lists — fresh ``parent_ids`` lists are built per spec.
    """
    wb = WorkerBoard(ctx, board=board)
    snap = parse_root_body(wb.show(root_id)["body"])
    t = parse_template(snap.template_yaml)

    specs = cards_for_run(
        t, snap.params, snap.bindings,
        completed=runview.completed, existing=runview.existing,
    )

    created: dict = {}
    # Topo-drain: each pass creates the specs whose parents are all resolvable
    # (already on the board or created earlier this pass) and re-queues the rest,
    # so parents are always created before their children.
    pending = list(specs)
    safety = 0
    while pending and safety < _MAX_PASSES:
        safety += 1
        spec = pending.pop(0)

        parent_ids = []
        missing = False
        for pid in spec.parent_identities:
            cid = runview.by_identity.get(pid) or created.get(pid)
            if cid is None:
                missing = True
                break
            parent_ids.append(cid)
        if missing:
            pending.append(spec)  # retry once its parents are created this pass
            continue

        if not parent_ids:
            parent_ids = [root_id]  # entry stage: descend from the run root so link-walk reaches it

        ws_kind, ws_path = _workspace(spec.workspace, root_id, spec.identity, base_ref)
        body = embed_sentinel(LIFECYCLE_PREAMBLE + spec.body, _sentinel(root_id, spec, t))

        cid = wb.create(
            title=spec.title or spec.identity.stage_id,  # gate stages have no title
            parents=parent_ids,
            assignee=spec.assignee,
            workspace_kind=ws_kind,
            workspace_path=ws_path,
            body=body,
            skills=(spec.skills or None),
            idempotency_key=_idem(root_id, spec.identity),
        )
        created[spec.identity] = cid

    if pending:  # fail loud rather than silently dropping cards with unresolvable parents
        raise MaterializeError(
            f"unresolvable parents for {[s.identity for s in pending]}"
        )
    return created


def _workspace(workspace: str, root_id: str, ident, base_ref):
    """Split a ``kind[:path]`` workspace string into (kind, path) for the card.

    A ``worktree:<repo>`` is provisioned NOW (provision-then-create) and lands
    on the card as a provisioned ``dir:<provisioned-path>``. A failed provision
    raises so the card is NOT created (reconcile handles it).
    """
    kind, _, path = workspace.partition(":")
    if kind == _WORKTREE_KIND:
        return _DIR_KIND, provision_worktree(root_id, ident, path, base_ref)
    if kind == _DIR_KIND:
        return _DIR_KIND, path
    return _SCRATCH_KIND, None


def _sentinel(root_id: str, spec, t) -> Sentinel:
    return Sentinel(
        root_id,
        spec.identity.stage_id,
        spec.identity.fan_index,
        spec.identity.attempt,
        t.name,
        t.version,
        PLUGIN_VERSION,
        SCHEMA_VERSION,
    )


def _idem(root_id: str, ident) -> str:
    raw = f"{root_id}:{ident.stage_id}:{ident.fan_index}:{ident.attempt}"
    return "wf_" + hashlib.sha1(raw.encode()).hexdigest()[:_IDEM_LEN]
