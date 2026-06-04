# hermes_workflow/board.py
"""Board adapter: two surfaces over the Hermes Kanban.

WorkerBoard wraps the worker/hook *model-tool* surface (kanban_create/link/
comment/show) via ``ctx.dispatch_tool(name, args) -> JSON string``. Every call
gets an explicit ``board`` injected so it never relies on ambient env routing.

HostBoard wraps the orchestrator/CLI *host* surface (kb.* functions) for the
operations that have NO model tool — archive/unlink (Hermes finding Y) — plus a
board-wide list/reclaim. It is constructed with an already board-scoped conn.
"""
import json

from hermes_workflow.version import SENTINEL_ROOT_ASSIGNEE


class WorkerBoard:
    """Model-tool surface, reached through a dispatch context.

    ``ctx`` only needs ``dispatch_tool(tool_name, args, **kwargs) -> str``.
    """

    def __init__(self, ctx, board):
        self.ctx = ctx
        self.board = board

    def _call(self, tool, args):
        """Dispatch a kanban tool with an explicit board, return parsed JSON.

        Immutability: build a NEW args dict — never mutate the caller's.
        """
        payload = {**args, "board": self.board}
        return json.loads(self.ctx.dispatch_tool(tool, payload))

    def create(self, *, title, parents=(), assignee=SENTINEL_ROOT_ASSIGNEE,
               workspace_kind="scratch", workspace_path=None, body="",
               skills=None, idempotency_key=None):
        # Always pass workspace_kind explicitly: if BOTH workspace_kind and
        # workspace_path are omitted, _handle_create INHERITS the calling
        # worker's workspace (kanban_tools.py:746-794). Passing them keeps the
        # child's workspace deterministic.
        r = self._call("kanban_create", {
            "title": title,
            "assignee": assignee,
            "parents": list(parents) if parents else [],
            "workspace_kind": workspace_kind,
            "workspace_path": workspace_path,
            "body": body,
            "skills": skills,
            "idempotency_key": idempotency_key,
        })
        if not r.get("ok"):
            raise BoardError(f"kanban_create failed: {r}")
        return r["task_id"]

    def link(self, parent_id, child_id):
        r = self._call("kanban_link", {"parent_id": parent_id, "child_id": child_id})
        if not r.get("ok"):
            raise BoardError(f"kanban_link failed: {r}")
        return r

    def comment(self, task_id, body):
        r = self._call("kanban_comment", {"task_id": task_id, "body": body})
        if not r.get("ok"):
            raise BoardError(f"kanban_comment failed: {r}")
        return r

    def complete(self, *, task_id, summary=None):
        r = self._call("kanban_complete", {"task_id": task_id, "summary": summary})
        if not r.get("ok"):
            raise BoardError(f"kanban_complete failed: {r}")
        return r

    def show(self, task_id):
        """Return a FLAT card dict.

        kanban_show (kanban_tools.py:339-412) returns a NESTED shape:
        ``{"task": {...}, "parents": [...], "children": [...], "runs": [...],
        "comments": [...], ...}`` — NOT an _ok envelope. Downstream Phase-2 code
        (RunView/materializer/hooks) wants a single flat card, so this is the
        one place we normalize: merge the ``task`` sub-dict up to the top level
        and re-attach the link/run/comment lists.
        """
        raw = self._call("kanban_show", {"task_id": task_id})
        if "task" not in raw:
            # Error envelope ({"error": ...}/{"ok": false}) or a missing card.
            raise BoardError(f"kanban_show returned no task for {task_id!r}: {raw}")
        task = raw["task"]
        return {
            **task,
            "parents": raw.get("parents", []),
            "children": raw.get("children", []),
            "runs": raw.get("runs", []),
            "comments": raw.get("comments", []),
        }


class HostBoard:
    """Host kb.* surface for orchestrator/CLI-only operations.

    The ``conn`` is already board-scoped, so kb.* calls take no ``board=``
    kwarg. ``board`` is retained for identity/logging.
    """

    def __init__(self, kb, conn, board):
        self.kb = kb
        self.conn = conn
        self.board = board

    def list(self):
        """Board-wide sweep (the conn is already board-scoped)."""
        return self.kb.list_tasks(self.conn)

    def archive(self, task_id):
        return self.kb.archive_task(self.conn, task_id)

    def unlink(self, parent_id, child_id):
        return self.kb.unlink_tasks(self.conn, parent_id, child_id)

    def reclaim(self, task_id):
        return self.kb.reclaim_task(self.conn, task_id)


class BoardError(RuntimeError):
    """Raised when a kanban model-tool call returns a non-ok / error payload."""
