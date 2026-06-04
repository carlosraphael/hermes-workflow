# tests/integration/test_spike_version_gate.py
"""Spike 4 — worker cross-task comment (version-gate "visible refuse" basis).

Confirms against the REAL tool handler + board (tools.kanban_tools +
hermes_cli.kanban_db, no LLM) the two facts the §2 version gate depends on
(Hermes v0.15.1 @ c47b9d12):

  1. A WORKER (process with HERMES_KANBAN_TASK pinned to its OWN card) may
     kanban_comment on a FOREIGN card (e.g. the workflow root) — cross-task
     commenting is DELIBERATELY unrestricted (the handoff channel). This is
     the basis for the gate's "visible refuse": on a version mismatch the
     hook posts a comment on the root and the veto blocks, neither raising.
  2. The comment author is FORCED from the worker's runtime identity
     (HERMES_PROFILE or "worker"), NOT from caller-supplied args["author"].
     A worker cannot forge an authoritative-looking author like
     "hermes-system" to poison the next worker's injected context.

Contrast (NOT exercised here, recorded in SPIKES.md from source): kanban_complete
/ kanban_block DO enforce worker ownership via _enforce_worker_task_ownership
and reject foreign task ids. Comments are the exception.

See tests/SPIKES.md "Spike 4" for the recorded signatures/behaviors.
"""
import json
import os

import pytest

pytestmark = pytest.mark.integration


def test_worker_can_comment_on_foreign_root(tmp_board, mk_card, as_worker):
    root = mk_card(title="root", assignee="_workflow_root")
    other = mk_card(title="worker card")
    with as_worker(other):                   # simulate running as the 'other' worker
        from tools import kanban_tools
        res = kanban_tools._handle_comment(
            {"task_id": root, "body": "schema_version mismatch: refusing"}
        )
    parsed = json.loads(res)
    assert parsed.get("ok") is True          # foreign-root comment ALLOWED (cross-task unrestricted)
    assert "comment_id" in parsed


def test_comment_author_is_forced_not_taken_from_args(tmp_board, mk_card, as_worker):
    """A worker cannot forge the author via args — it's pinned to its runtime id."""
    root = mk_card(title="root", assignee="_workflow_root")
    other = mk_card(title="worker card")
    with as_worker(other):
        from tools import kanban_tools
        res = kanban_tools._handle_comment(
            {"task_id": root, "body": "veto note", "author": "hermes-system"}
        )
    parsed = json.loads(res)
    assert parsed.get("ok") is True

    # Read the persisted comment back via the same board file.
    comments = tmp_board.kb.list_comments(tmp_board.conn, root)
    assert len(comments) == 1
    recorded_author = comments[0].author
    assert recorded_author != "hermes-system"          # the forged value is IGNORED
    assert recorded_author == (os.environ.get("HERMES_PROFILE") or "worker")
