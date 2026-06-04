# hermes_workflow/hooks.py
"""post_tool_call fan-out driver.

Runs in the COMPLETING worker's process, right after ``kanban_complete``
returned (model_tools.py:993-1006). It is a pure side effect — it NEVER raises
(fail-open): Hermes ignores the return and already swallows hook exceptions, so
a crash here must not break the worker's completion. The whole body is one
``try/except`` that logs and swallows.

Flow: gate on ``kanban_complete`` + a successful result -> resolve the completed
card's sentinel -> read its workflow root snapshot -> version-gate (a mismatch
posts a VISIBLE refuse comment on the root and stops, no fan-out) -> drive the
materializer to create the next layer of cards (fan-out + R5 join).

The hook only ever calls ``kanban_create``/``kanban_link``/``kanban_comment``
(via WorkerBoard/materialize), never ``kanban_complete``/``complete_task`` with
``created_cards``, so it can never trip the hallucination gate (Task 17 §14).
"""
import json
import logging
import os

from hermes_workflow.board import WorkerBoard
from hermes_workflow.engine.provenance import extract_sentinel, parse_root_body, is_version_compatible
from hermes_workflow.materialize import materialize
from hermes_workflow.runview import RunView
from hermes_workflow.version import SUPPORTED_SCHEMA_VERSIONS

log = logging.getLogger("hermes_workflow.hooks")

_COMPLETE_TOOL = "kanban_complete"
_DEFAULT_BOARD = "default"


def _board_of():
    """The worker's board (in tests ``tmp_board`` sets it to ``test``)."""
    return os.environ.get("HERMES_KANBAN_BOARD", _DEFAULT_BOARD)


def on_tool_done(*, ctx, tool_name, args, result, task_id, **kwargs):
    """Fan out the next workflow layer when a workflow stage completes.

    Side-effect only; never raises (fail-open). ``**kwargs`` absorbs the real
    Hermes payload (``session_id``/``tool_call_id``/``duration_ms``).

    Note: Hermes' ``invoke_hook`` calls the registered callback as
    ``cb(**kwargs)`` with ``tool_name/args/result/task_id/...`` and does NOT
    pass ``ctx``. Phase-3 ``register(ctx)`` binds ``ctx`` via a closure before
    registering, so the live callback Hermes sees is effectively
    ``(*, tool_name, args, result, task_id, **kwargs)``.
    """
    try:
        if tool_name != _COMPLETE_TOOL:
            return  # self-gate hard: only react to a completion

        parsed = json.loads(result) if isinstance(result, str) else {}
        if not isinstance(parsed, dict) or parsed.get("error") or not parsed.get("ok", True):
            return  # only act on a successful complete

        cid = task_id or (args or {}).get("task_id")
        if not cid:
            return

        wb = WorkerBoard(ctx, board=_board_of())
        card = wb.show(cid)
        sentinel = extract_sentinel(card.get("body") or "")
        if not sentinel:
            return  # not a workflow card

        root = wb.show(sentinel.workflow_root)
        snap = parse_root_body(root["body"])

        if not is_version_compatible(snap, SUPPORTED_SCHEMA_VERSIONS):
            wb.comment(
                task_id=sentinel.workflow_root,
                body=(
                    f"hermes-workflow: schema_version {snap.schema_version} unsupported "
                    f"by this worker's plugin; refusing to fan out card {cid}. "
                    "Drain & align versions."
                ),
            )
            return  # visible refuse: NO fan-out, NO raise

        rv = RunView.from_root(ctx, board=wb.board, root_id=sentinel.workflow_root)
        materialize(ctx, board=wb.board, root_id=sentinel.workflow_root, runview=rv)
    except Exception:
        log.exception("hermes-workflow fan-out hook failed (swallowed)")
