# src/hermes_workflow/tools.py
"""Orchestrator-facing workflow tools.

The six ``workflow_*`` tool functions plus their small private helpers. The rest
of the surface lives in sibling modules: schemas (:mod:`hermes_workflow.schemas`),
the ``COMMANDS`` table + CLI/slash dispatch (:mod:`hermes_workflow.cli`), and the
collapse-planner board glue (:mod:`hermes_workflow.reconcile_exec`).

``workflow_start`` validates a template + its bindings, runs a per-profile
pre-flight loadability probe, and — only once every profile is confirmed
loadable — seeds the run: it writes the root blackboard (a completed card
carrying the compiled snapshot) and materializes the dynamic-free prefix
(entry stages that have no fan-out dependency yet).

Pre-flight is fail-closed and zero-cards-on-failure: if ANY bound profile
can't load the plugin (or a codex lane is missing its binary/skill), we return
a remediation map and create NOTHING. Cards are only ever created after the
probe is fully green.
"""
import os
import subprocess

from hermes_workflow.board import BoardError, WorkerBoard
from hermes_workflow.engine.provenance import build_root_body
from hermes_workflow.engine.template import (
    TemplateError,
    parse_template,
    validate_template,
)
from hermes_workflow.sweep import reverse_topo_order
from hermes_workflow.materialize import MaterializeError, materialize
from hermes_workflow.preflight import probe_profiles, _remediation
from hermes_workflow.runview import RunView
from hermes_workflow.worktree import _orphaned_branches
from hermes_workflow.version import (
    PLUGIN_VERSION,
    SCHEMA_VERSION,
    SENTINEL_ROOT_ASSIGNEE,
)
from hermes_workflow.reconcile_exec import (
    _collapse_duplicates,
    _host_board,
    _relink_created_to_joins,
)

_CODEX_LANE = "codex"
_DEFAULT_BOARD = "default"


def _require_orchestrator(tool):
    """Refuse to run inside a dispatcher-spawned worker (it has HERMES_KANBAN_TASK)."""
    if os.environ.get("HERMES_KANBAN_TASK"):
        return {"error": f"{tool} must run in orchestrator context (no HERMES_KANBAN_TASK)"}
    return None


def _capture_base_ref(t, params):
    """Pin the run's worktree repo HEAD at start so fan-out worktrees branch from
    a fixed commit even if HEAD moves mid-run (0.1.0 locked decision). Returns a
    commit sha, or None when there is no single worktree repo or git can't resolve
    it (then provisioning falls back to live HEAD — current behavior, no regression).
    """
    from hermes_workflow.engine.interpolate import interpolate
    repos = set()
    for s in t.stages:
        if s.workspace.startswith("worktree:"):
            try:
                repos.add(interpolate(s.workspace, params=params, expand_vars={}).partition(":")[2])
            except Exception:
                return None
    if len(repos) != 1:           # 0 worktree stages, or (out-of-0.1.0-scope) multiple distinct repos
        return None
    repo = next(iter(repos))
    try:
        r = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                           capture_output=True, text=True, check=True)
        return r.stdout.strip() or None
    except Exception:
        return None


def workflow_start(ctx, *, template_text, params, bindings, board=None):
    """Validate, pre-flight, then seed a workflow run (root + dynamic-free prefix).

    Immutability: every collection returned is freshly built; inputs are never
    mutated. Returns ``{"root_id", "board"}`` on success, else ``{"error", ...}``.
    """
    guard = _require_orchestrator("workflow_start")
    if guard is not None:
        return guard

    try:
        t = parse_template(template_text)
        validate_template(t)
    except TemplateError as e:
        return {"error": f"template invalid: {e}"}

    missing = [n for n, p in t.params.items() if p.required and n not in params]
    if missing:
        return {"error": f"missing required params: {missing}"}

    unbound = [r for r in t.roles if r not in bindings]
    if unbound:
        return {"error": f"unbound roles: {unbound}"}

    profiles = {bindings[r] for r in t.roles}
    codex_profiles = {bindings[r] for r in t.roles if t.roles[r].lane == _CODEX_LANE}
    probe = probe_profiles(profiles, codex_profiles=codex_profiles)
    bad = {p: info["error"] for p, info in probe.items() if not info["ok"]}
    if bad:
        return {
            "error": "per-profile pre-flight failed (zero cards created)",
            "profiles": bad,
            "remediation": {p: _remediation(p, err) for p, err in bad.items()},
        }

    board = board or os.environ.get("HERMES_KANBAN_BOARD", _DEFAULT_BOARD)
    wb = WorkerBoard(ctx, board=board)
    base_ref = _capture_base_ref(t, params)
    root_body = build_root_body(template_text, params, bindings, PLUGIN_VERSION, SCHEMA_VERSION, base_ref)
    # Post-pre-flight seeding is guarded: a board-write or worktree-provision
    # failure returns a flat error (mirrors the reconcile guard) instead of a raw
    # traceback. A partial seed is safe — workflow_reconcile re-drives missing cards.
    # (The root is a completed blackboard: an orchestrator may complete any card,
    # and a no-parent root is `ready`, which complete_task accepts.)
    try:
        root_id = wb.create(
            title=f"workflow:{t.name}",
            assignee=SENTINEL_ROOT_ASSIGNEE,
            workspace_kind="scratch",
            body=root_body,
        )
        wb.complete(task_id=root_id, summary="workflow root blackboard")
        rv = RunView.from_root(ctx, board=board, root_id=root_id)
        materialize(ctx, board=board, root_id=root_id, runview=rv, base_ref=base_ref)
    except (BoardError, MaterializeError, subprocess.CalledProcessError) as e:
        return {"error": f"workflow seed failed after pre-flight: {e}"}
    return {"root_id": root_id, "board": board}


# ---------------------------------------------------------------------------
# Read-only status/validate + the reconcile orchestrator (Phase 3).
# ---------------------------------------------------------------------------


class WorkflowError(Exception):
    """A workflow-domain failure (e.g. a card that is not a workflow root)."""


def _root_snapshot(ctx, board, root_id):
    """Read+parse the root blackboard snapshot. GUARDS parse_root_body (NOT total).

    A card whose body lacks the snapshot marker (i.e. not a workflow root) raises
    a clear WorkflowError instead of a bare JSONDecodeError.
    """
    from hermes_workflow.engine.provenance import parse_root_body
    body = WorkerBoard(ctx, board=board).show(root_id).get("body") or ""
    try:
        return parse_root_body(body)
    except Exception as e:
        raise WorkflowError(f"{root_id} is not a workflow root blackboard: {e}") from e


def workflow_validate(ctx, *, template_text):
    """Deterministic template gatekeeper (read-only).

    Defers entirely to ``validate_template`` — which already rejects verify/retry
    and nested-expand — and reports the first failure as a flat error string.
    """
    try:
        t = parse_template(template_text)
        validate_template(t)
    except TemplateError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True}


def _review_required(card) -> bool:
    """True iff this card is a worker-initiated review-required sticky block.

    Card is `blocked` AND its most-recent blocked/unblocked event is `blocked`
    with a reason starting `review-required`.
    """
    if card.get("status") != "blocked":
        return False
    block_events = [e for e in (card.get("events") or []) if e.get("kind") in ("blocked", "unblocked")]
    if not block_events or block_events[-1].get("kind") != "blocked":
        return False
    reason = ((block_events[-1].get("payload") or {}).get("reason") or "")
    return reason.startswith("review-required")


def _rollup(states):
    """Roll a stage's instance statuses up to one state: most-active wins.

    `done` is last so an all-`done` set returns `done`; any mixed set returns
    the most-active status present.
    """
    for st in ("running", "ready", "blocked", "todo", "done"):
        if st in states:
            return st
    return states[0] if states else "pending"


def workflow_status(ctx, *, root_id, board=None):
    """Read-only run summary: per-stage rollup + blocked/awaiting/review-required.

    A missing or non-workflow root must not crash — it returns a flat ``error``.
    """
    board = board or os.environ.get("HERMES_KANBAN_BOARD", _DEFAULT_BOARD)
    try:
        rv = RunView.from_root(ctx, board=board, root_id=root_id)
        t = parse_template(_root_snapshot(ctx, board, root_id).template_yaml)
    except (WorkflowError, BoardError, TemplateError) as e:
        return {"error": str(e)}

    wb = WorkerBoard(ctx, board=board)
    stages = {}
    blocked_stages = []
    awaiting_approval = []  # human-gate cards parked in ready/todo: the native stranded-in-ready signal
    review_required = []

    for s in t.stages:
        instance_idents = [i for i in rv.existing if i.stage_id == s.id]
        if not instance_idents:
            stages[s.id] = {"state": "pending"}
            continue

        states = [rv.status[rv.by_identity[i]] for i in instance_idents]
        stages[s.id] = {"state": _rollup(states), "instances": len(instance_idents)}

        for i in instance_idents:
            cid = rv.by_identity[i]
            if rv.status[cid] == "blocked":
                blocked_stages.append({"stage": s.id, "card": cid})
                if _review_required(wb.show(cid)):
                    review_required.append({"stage": s.id, "card": cid,
                                            "remediation": f"hermes kanban unblock {cid}"})
            if s.gate == "human" and rv.status[cid] in ("ready", "todo"):
                awaiting_approval.append({"stage": s.id, "card": cid})

    return {
        "root_id": root_id,
        "stages": stages,
        "blocked_stages": blocked_stages,
        "awaiting_approval": awaiting_approval,
        "review_required": review_required,
    }


def workflow_reconcile(ctx, *, root_id, board=None, kb=None, conn=None):
    """Re-run the engine graph from durable inputs: create-missing + re-link + diagnose.

    Mutating — refuses to run inside a dispatcher-spawned worker. Re-materializes
    absent cards (idempotent worktree re-provision), re-links each created child to
    any pre-existing downstream join, and surfaces review-required stalls. Finally,
    a progress-aware dedup pass collapses genuine concurrent duplicates (two live
    cards sharing one sentinel identity — e.g. the create-key race).
    """
    guard = _require_orchestrator("workflow_reconcile")
    if guard is not None:
        return guard

    board = board or os.environ.get("HERMES_KANBAN_BOARD", _DEFAULT_BOARD)
    try:
        snap = _root_snapshot(ctx, board, root_id)
        t = parse_template(snap.template_yaml)
        rv = RunView.from_root(ctx, board=board, root_id=root_id)
        created = materialize(ctx, board=board, root_id=root_id, runview=rv, base_ref=snap.base_ref)
        rv2 = RunView.from_root(ctx, board=board, root_id=root_id)
    except (WorkflowError, BoardError, TemplateError, MaterializeError, subprocess.CalledProcessError) as e:
        return {"error": str(e)}

    # Re-link each created child to its already-existing downstream join.
    wb = WorkerBoard(ctx, board=board)
    relinked = _relink_created_to_joins(wb, t, created, rv2)

    # Diagnosis: surface review-required stalls (the spec-required backstop).
    review_required = []
    for ident in rv2.existing:
        cid = rv2.by_identity[ident]
        if rv2.status.get(cid) == "blocked" and _review_required(wb.show(cid)):
            review_required.append({"stage": ident.stage_id, "card": cid,
                                    "remediation": f"hermes kanban unblock {cid}"})

    # Progress-aware collapse: retire duplicate cards sharing one sentinel identity.
    # Guarded so an enumeration error can't discard the create/relink progress above
    # (best-effort: per-op failures travel back in `failures`, the call never raises).
    deduped, dedup_failures = [], []
    try:
        deduped, dedup_failures = _collapse_duplicates(ctx, board, root_id, wb, t, kb, conn)
    except (BoardError, WorkflowError) as e:
        dedup_failures = [{"card": root_id, "op": "collapse", "error": str(e)}]

    return {
        "root_id": root_id,
        "created": [str(c) for c in created.values()],
        "relinked": [list(p) for p in relinked],
        "deduped": deduped,
        "failures": dedup_failures,
        "diagnosis": {"review_required": review_required},
    }


# ---------------------------------------------------------------------------
# Approve / abandon orchestrator tools (Phase 3, Task 21).
# ---------------------------------------------------------------------------


def workflow_approve(ctx, *, gate_card, board=None):
    """Complete a human gate card so its downstream stages promote natively.

    Mutating — refuses to run inside a dispatcher-spawned worker. An orchestrator
    may complete any card; completing the gate promotes downstream via Hermes'
    native recompute_ready.
    """
    guard = _require_orchestrator("workflow_approve")
    if guard is not None:
        return guard

    board = board or os.environ.get("HERMES_KANBAN_BOARD", _DEFAULT_BOARD)
    try:
        WorkerBoard(ctx, board=board).complete(task_id=gate_card, summary="approved")
    except BoardError as e:
        return {"error": str(e)}
    return {"approved": gate_card}


def workflow_abandon(ctx, *, root_id, board=None, kb=None, conn=None):
    """Hazard-free teardown: reclaim running workers, then archive leaves-first.

    Mutating — refuses to run inside a dispatcher-spawned worker. Audits orphaned
    worktree branches BEFORE archiving (the link-walk is still live), comments the
    audit on the root (best-effort), reclaims/terminates running workers FIRST
    (archive does NOT kill them), then archives every run card and the root in
    reverse-topological (leaves-first) order so recompute_ready never transiently
    promotes an interior stage.
    """
    guard = _require_orchestrator("workflow_abandon")
    if guard is not None:
        return guard

    board = board or os.environ.get("HERMES_KANBAN_BOARD", _DEFAULT_BOARD)
    try:
        t = parse_template(_root_snapshot(ctx, board, root_id).template_yaml)
        rv = RunView.from_root(ctx, board=board, root_id=root_id)
    except (WorkflowError, BoardError, TemplateError) as e:
        return {"error": str(e)}

    wb = WorkerBoard(ctx, board=board)

    # Audit orphaned worktree branches BEFORE archiving (link-walk still live).
    orphaned = _orphaned_branches(t, rv, root_id)

    # Comment the audit on the root (best-effort; teardown proceeds regardless).
    try:
        wb.comment(root_id, f"hermes-workflow abandon: archiving run; "
                            f"orphaned worktree branches: {orphaned}")
    except BoardError:
        pass

    run_cards = list(rv.by_identity.values())
    card_set = set(run_cards) | {root_id}
    def children_of(cid):
        return [c for c in (wb.show(cid).get("children") or []) if c in card_set]

    failures = []
    with _host_board(board, kb, conn) as hb:
        # Reclaim/terminate running workers FIRST (archive does NOT kill them).
        for cid in run_cards:
            if rv.status.get(cid) == "running":
                try:
                    hb.reclaim(cid)
                except Exception as e:
                    failures.append({"card": cid, "op": "reclaim", "error": str(e)})
        # Archive leaves-first, including the root. Per-card resilience: a mid-sweep
        # failure must NOT abort the leaves-first order (a partial sweep can leave an
        # interior stage transiently promotable). Re-running abandon is idempotent.
        for cid in reverse_topo_order(card_set, children_of):
            try:
                hb.archive(cid)
            except Exception as e:
                failures.append({"card": cid, "op": "archive", "error": str(e)})

    return {"abandoned": root_id, "orphaned_branches": orphaned, "failures": failures}
