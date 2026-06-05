import json
import subprocess
import pathlib
import pytest
pytestmark = pytest.mark.integration


def _head(repo):
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()


def _commit(repo, fn, content):
    (pathlib.Path(repo) / fn).write_text(content)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=a@b.c", "-c", "user.name=a",
                    "commit", "-m", "move HEAD"], check=True, capture_output=True)


def test_base_ref_pins_fanout_worktrees_across_head_move(fake_ctx, tmp_board, started_run, as_worker):
    from hermes_workflow.tools import _root_snapshot
    from hermes_workflow.runview import RunView
    from hermes_workflow.hooks import on_tool_done
    from hermes_workflow.board import WorkerBoard

    # 1. Start the run against the real repo and capture HEAD-at-start.
    root = started_run()
    repo = tmp_board.repo
    c0 = _head(repo)

    # 2. The snapshot must have pinned the start commit.
    snap = _root_snapshot(fake_ctx, tmp_board.name, root)
    assert snap.base_ref == c0

    # 3. Move HEAD AFTER start (simulate the repo advancing mid-run).
    _commit(repo, "new.txt", "x")
    c1 = _head(repo)
    assert c1 != c0

    # 4. Complete scan with 2 flaky tests and drive the fan-out hook as a worker.
    rv = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=root)
    scan = rv.card_id_for(("scan", 0, 0))
    tmp_board.complete(scan, metadata={"flaky": [
        {"test_id": "T1", "file": "a.py"}, {"test_id": "T2", "file": "b.py"}]})
    with as_worker(scan):
        on_tool_done(ctx=fake_ctx, tool_name="kanban_complete",
                     args={"task_id": scan}, result=json.dumps({"ok": True}), task_id=scan)

    # 5. Both fix worktrees must branch from the PINNED base c0, not the moved HEAD c1.
    rv2 = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=root)
    wb = WorkerBoard(fake_ctx, board=tmp_board.name)
    for i in (0, 1):
        fix = rv2.card_id_for(("fix", i, 0))
        wt = wb.show(fix)["workspace_path"]
        assert _head(wt) == c0      # pinned base
        assert _head(wt) != c1      # NOT the moved live HEAD
