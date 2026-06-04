# tests/integration/test_board_adapter.py
"""Board adapter: WorkerBoard (dispatch_tool surface) + HostBoard (kb.* surface).

These exercise the real kanban model tools via a tiny dispatch context
(fake_ctx) and the real host kb layer (tmp_board.kb/conn) — no LLM.
"""
import pytest

pytestmark = pytest.mark.integration


def test_create_and_show_via_dispatch(fake_ctx, tmp_board, as_worker):
    from hermes_workflow.board import WorkerBoard

    wb = WorkerBoard(fake_ctx, board=tmp_board.name)
    parent = tmp_board.create(title="p")
    with as_worker(parent):
        cid = wb.create(title="child", parents=[parent], assignee="_workflow_root",
                        workspace_kind="scratch", body="b")
        shown = wb.show(cid)
    # show() normalizes the nested kanban_show shape into a flat card.
    assert shown["title"] == "child"
    assert shown["body"] == "b"
    assert shown["id"] == cid
    assert parent in shown["parents"]


def test_link_adds_edge_via_dispatch(fake_ctx, tmp_board):
    from hermes_workflow.board import WorkerBoard

    wb = WorkerBoard(fake_ctx, board=tmp_board.name)
    parent = wb.create(title="p2", assignee="_workflow_root", workspace_kind="scratch")
    child = wb.create(title="c2", assignee="_workflow_root", workspace_kind="scratch")
    wb.link(parent, child)
    assert parent in wb.show(child)["parents"]


def test_comment_returns_ok_via_dispatch(fake_ctx, tmp_board):
    from hermes_workflow.board import WorkerBoard

    wb = WorkerBoard(fake_ctx, board=tmp_board.name)
    tid = wb.create(title="c3", assignee="_workflow_root", workspace_kind="scratch")
    result = wb.comment(tid, "a note")
    assert result["ok"] is True
    assert result["task_id"] == tid


def test_worker_board_does_not_mutate_caller_args(fake_ctx, tmp_board):
    from hermes_workflow.board import WorkerBoard

    wb = WorkerBoard(fake_ctx, board=tmp_board.name)
    args = {"title": "c4", "assignee": "_workflow_root", "workspace_kind": "scratch"}
    snapshot = dict(args)
    wb.create(**args)
    assert args == snapshot  # _call must build a new dict, never mutate input


def test_host_board_archive(tmp_board):
    from hermes_workflow.board import HostBoard

    hb = HostBoard(tmp_board.kb, tmp_board.conn, tmp_board.name)
    tid = tmp_board.create(title="to-archive")
    assert hb.archive(tid) is True
    assert tmp_board.kb.get_task(tmp_board.conn, tid).status == "archived"


def test_host_board_list(tmp_board):
    from hermes_workflow.board import HostBoard

    hb = HostBoard(tmp_board.kb, tmp_board.conn, tmp_board.name)
    a = tmp_board.create(title="a")
    b = tmp_board.create(title="b")
    ids = {t.id for t in hb.list()}
    assert {a, b} <= ids


def test_host_board_unlink(tmp_board):
    from hermes_workflow.board import HostBoard

    hb = HostBoard(tmp_board.kb, tmp_board.conn, tmp_board.name)
    parent = tmp_board.create(title="hp")
    child = tmp_board.create(title="hc")
    tmp_board.link(parent, child)
    assert hb.unlink(parent, child) is True
    assert parent not in tmp_board.kb.parent_ids(tmp_board.conn, child)


def test_show_missing_card_raises(fake_ctx, tmp_board):
    from hermes_workflow.board import WorkerBoard, BoardError
    wb = WorkerBoard(fake_ctx, board=tmp_board.name)
    with pytest.raises(BoardError):
        wb.show("does-not-exist")
