# hermes_workflow/tools.py
"""Orchestrator-facing workflow tools.

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

from hermes_workflow.board import BoardError, WorkerBoard
from hermes_workflow.engine.provenance import build_root_body
from hermes_workflow.engine.template import (
    TemplateError,
    parse_template,
    validate_template,
)
from hermes_workflow.materialize import materialize
from hermes_workflow.preflight import probe_profiles
from hermes_workflow.runview import RunView
from hermes_workflow.version import (
    PLUGIN_VERSION,
    SCHEMA_VERSION,
    SENTINEL_ROOT_ASSIGNEE,
)

_CODEX_LANE = "codex"
_DEFAULT_BOARD = "default"


def _require_orchestrator(tool):
    """Refuse to run inside a dispatcher-spawned worker (it has HERMES_KANBAN_TASK)."""
    if os.environ.get("HERMES_KANBAN_TASK"):
        return {"error": f"{tool} must run in orchestrator context (no HERMES_KANBAN_TASK)"}
    return None


def _remediation(profile: str, err) -> str:
    """Map a bad-profile error to an actionable hint.

    A not-discovered / not-enabled / missing error means the plugin just needs
    enabling under that profile; anything else is a genuine load error.
    """
    if err is None or err == "not-discovered" or "not enabled" in err:
        return f"hermes -p {profile} plugins enable hermes-workflow"
    return f"load error: {err}"


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
    root_body = build_root_body(template_text, params, bindings, PLUGIN_VERSION, SCHEMA_VERSION)
    root_id = wb.create(
        title=f"workflow:{t.name}",
        assignee=SENTINEL_ROOT_ASSIGNEE,
        workspace_kind="scratch",
        body=root_body,
    )

    # The root is a completed blackboard: an orchestrator may complete any card,
    # and a no-parent root is `ready`, which complete_task accepts.
    try:
        wb.complete(task_id=root_id, summary="workflow root blackboard")
    except BoardError as e:
        return {"error": f"could not complete workflow root: {e}"}

    rv = RunView.from_root(ctx, board=board, root_id=root_id)
    materialize(ctx, board=board, root_id=root_id, runview=rv)
    return {"root_id": root_id, "board": board}
