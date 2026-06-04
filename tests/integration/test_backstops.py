# tests/integration/test_backstops.py
import json
import pytest

pytestmark = pytest.mark.integration

_FLAKY2 = {"flaky": [{"test_id": "T1", "file": "a.py"}, {"test_id": "T2", "file": "b.py"}]}


def _advance_to_fanout(fake_ctx, tmp_board, root):
    """Complete `scan` with two flaky items and materialize the `fix` fan-out."""
    from hermes_workflow.runview import RunView
    from hermes_workflow.materialize import materialize
    rv = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=root)
    scan = rv.card_id_for(("scan", 0, 0))
    tmp_board.complete(scan, metadata=_FLAKY2)
    rv2 = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=root)
    materialize(fake_ctx, board=tmp_board.name, root_id=root, runview=rv2)


def test_review_required_block_is_surfaced(fake_ctx, tmp_board, started_run):
    from hermes_workflow.tools import workflow_status
    from hermes_workflow.runview import RunView
    root = started_run()
    _advance_to_fanout(fake_ctx, tmp_board, root)

    fix0 = RunView.from_root(
        fake_ctx, board=tmp_board.name, root_id=root).card_id_for(("fix", 0, 0))
    # a fix worker follows the always-on habit and blocks for review instead of completing
    tmp_board.kb.block_task(
        tmp_board.conn, fix0, reason="review-required: please review the approach")

    st = workflow_status(fake_ctx, root_id=root, board=tmp_board.name)
    assert st["review_required"]
    entry = st["review_required"][0]
    assert entry["card"] == fix0
    assert f"unblock {fix0}" in entry["remediation"]
    assert any(b["card"] == fix0 for b in st["blocked_stages"])


def test_version_mismatch_refuses_visibly(fake_ctx, tmp_board, started_run, monkeypatch):
    from hermes_workflow import hooks
    from hermes_workflow.runview import RunView
    from hermes_workflow.board import WorkerBoard
    monkeypatch.setattr("hermes_workflow.hooks.SUPPORTED_SCHEMA_VERSIONS", frozenset({"9.9"}))
    root = started_run()

    rv = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=root)
    scan = rv.card_id_for(("scan", 0, 0))
    meta = {"flaky": [{"test_id": "T1", "file": "a.py"}]}
    tmp_board.complete(scan, metadata=meta)
    # the hook must comment-and-refuse (no fan-out, no raise) under a version mismatch
    hooks.on_tool_done(ctx=fake_ctx, tool_name="kanban_complete",
                       args={"task_id": scan, "metadata": meta},
                       result=json.dumps({"ok": True, "task_id": scan}), task_id=scan)

    rv2 = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=root)
    assert rv2.card_id_for(("fix", 0, 0)) is None   # refused: no fan-out under version mismatch
    root_card = WorkerBoard(fake_ctx, board=tmp_board.name).show(root)
    assert any("schema_version" in (c.get("body") or "") for c in root_card["comments"])


def test_reconcile_recreates_and_dedups(fake_ctx, tmp_board, partial_fanout):
    from hermes_workflow.tools import workflow_reconcile
    from hermes_workflow.runview import RunView
    from hermes_workflow.board import WorkerBoard
    pf = partial_fanout()
    result = workflow_reconcile(fake_ctx, root_id=pf.root, board=tmp_board.name)

    rv = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=pf.root)
    wb = WorkerBoard(fake_ctx, board=tmp_board.name)

    # the empty duplicate was archived; the 'done' winner survives live
    assert pf.dup in result["deduped"]
    assert len(result["deduped"]) == 1
    assert wb.show(pf.winner)["status"] == "done"

    # the missing instance was recreated as a live (non-archived) card
    fix1 = rv.card_id_for(("fix", 1, 0))
    assert fix1 and rv.status[fix1] != "archived"
