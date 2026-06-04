import subprocess

import pytest

from hermes_workflow.runview import RunView
from hermes_workflow.materialize import materialize
from hermes_workflow.tools import (
    workflow_abandon,
    workflow_approve,
    workflow_reconcile,
    workflow_start,
)

pytestmark = pytest.mark.integration


# scan -> fix (fan-out) -> approve (human gate) -> report. Same demo as conftest's
# DEMO_TPL; fix is a worktree stage so materialize needs a real git repo.
DEMO_TPL_INLINE = """
name: demo
version: 0.1.0
params: { repo: { type: string, required: true } }
roles: { scout: { lane: profile }, fixer: { lane: codex }, reporter: { lane: profile } }
stages:
  - { id: scan, role: scout, title: "scan ${params.repo}", workspace: "dir:${params.repo}",
      expand_out: { key: flaky, max: 50, item: { test_id: string, file: string } } }
  - { id: fix, role: fixer, needs: [scan], expand: { over: scan.flaky, as: t },
      title: "fix ${t.test_id}", body: "fix ${t.file}", workspace: "worktree:${params.repo}" }
  - { id: approve, needs: [fix], gate: human }
  - { id: report, role: reporter, needs: [approve, fix], title: "report" }
"""


def _init_git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    (repo / "f").write_text("x")
    subprocess.run(["git", "add", "f"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=a@b.c", "-c", "user.name=a", "commit", "-m", "init"],
        cwd=repo, check=True, capture_output=True,
    )
    return repo


# --- local helpers bound to fake_ctx/tmp_board -----------------------------

def _start(fake_ctx, tmp_board, repo):
    return workflow_start(
        fake_ctx,
        template_text=DEMO_TPL_INLINE,
        params={"repo": str(repo)},
        bindings={"scout": "designer", "fixer": "coder", "reporter": "writer"},
        board=tmp_board.name,
    )["root_id"]


def _advance_to_fanout(fake_ctx, tmp_board, root_id):
    rv = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=root_id)
    scan = rv.card_id_for(("scan", 0, 0))
    tmp_board.complete(scan, metadata={"flaky": [
        {"test_id": "T1", "file": "a.py"},
        {"test_id": "T2", "file": "b.py"},
    ]})
    rv2 = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=root_id)
    materialize(fake_ctx, board=tmp_board.name, root_id=root_id, runview=rv2)


@pytest.fixture(autouse=True)
def _stub_preflight(monkeypatch):
    monkeypatch.delenv("HERMES_KANBAN_TASK", raising=False)
    monkeypatch.setattr(
        "hermes_workflow.tools.probe_profiles",
        lambda profiles, **kw: {p: {"ok": True, "error": None} for p in profiles},
    )


def test_approve_completes_gate_and_promotes_downstream(fake_ctx, tmp_board, tmp_path):
    repo = _init_git_repo(tmp_path)
    root = _start(fake_ctx, tmp_board, repo)
    _advance_to_fanout(fake_ctx, tmp_board, root)

    rv = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=root)
    fix0 = rv.card_id_for(("fix", 0, 0))
    fix1 = rv.card_id_for(("fix", 1, 0))
    approve = rv.card_id_for(("approve", 0, 0))

    # Complete both fix instances so the approve gate becomes ready.
    tmp_board.complete(fix0, metadata={})
    tmp_board.complete(fix1, metadata={})
    assert tmp_board.status(approve) == "ready"

    r = workflow_approve(fake_ctx, gate_card=approve, board=tmp_board.name)
    assert r == {"approved": approve}
    assert tmp_board.status(approve) == "done"


def test_abandon_archives_run_leaves_first_and_audits_orphans(fake_ctx, tmp_board, tmp_path):
    repo = _init_git_repo(tmp_path)
    root = _start(fake_ctx, tmp_board, repo)
    _advance_to_fanout(fake_ctx, tmp_board, root)

    r = workflow_abandon(
        fake_ctx, root_id=root, board=tmp_board.name,
        kb=tmp_board.kb, conn=tmp_board.conn,
    )

    assert "orphaned_branches" in r
    assert any("/fix/" in b for b in r["orphaned_branches"])

    rv = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=root)
    assert all(rv.status[c] == "archived" for c in rv.by_identity.values())
    assert tmp_board.status(root) == "archived"


def test_abandon_is_resilient_to_archive_failure(fake_ctx, tmp_board, tmp_path, monkeypatch):
    from hermes_workflow.board import HostBoard

    repo = _init_git_repo(tmp_path)
    root = _start(fake_ctx, tmp_board, repo)
    _advance_to_fanout(fake_ctx, tmp_board, root)

    # Inject a failure on the FIRST archive only; delegate to the real archive after.
    real_archive = HostBoard.archive
    calls = {"n": 0}

    def flaky_archive(self, cid):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return real_archive(self, cid)

    monkeypatch.setattr(HostBoard, "archive", flaky_archive)

    r = workflow_abandon(
        fake_ctx, root_id=root, board=tmp_board.name,
        kb=tmp_board.kb, conn=tmp_board.conn,
    )

    # The injected failure surfaced ...
    assert r["failures"]
    assert any(f["op"] == "archive" for f in r["failures"])
    # ... and the sweep CONTINUED past it (root still gets archived).
    assert tmp_board.status(root) == "archived"


def test_abandon_reclaims_running_worker_before_archiving(fake_ctx, tmp_board, tmp_path, monkeypatch):
    from hermes_workflow.board import HostBoard
    repo = _init_git_repo(tmp_path)
    root = _start(fake_ctx, tmp_board, repo)
    _advance_to_fanout(fake_ctx, tmp_board, root)

    rv = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=root)
    fix0 = rv.card_id_for(("fix", 0, 0))

    # Drive a fan-out card into 'running' via a real claim (ready -> running).
    claimed = tmp_board.kb.claim_task(tmp_board.conn, fix0)
    assert claimed is not None
    assert tmp_board.status(fix0) == "running"

    # Spy on reclaim AND archive into one ordered event log to prove the running
    # worker is reclaimed FIRST — before any archive in the leaves-first sweep.
    real_reclaim, real_archive = HostBoard.reclaim, HostBoard.archive
    events = []
    def spy_reclaim(self, cid):
        events.append(("reclaim", cid))
        return real_reclaim(self, cid)
    def spy_archive(self, cid):
        events.append(("archive", cid))
        return real_archive(self, cid)
    monkeypatch.setattr(HostBoard, "reclaim", spy_reclaim)
    monkeypatch.setattr(HostBoard, "archive", spy_archive)

    r = workflow_abandon(fake_ctx, root_id=root, board=tmp_board.name,
                         kb=tmp_board.kb, conn=tmp_board.conn)

    # the running fix card was reclaimed, with NO reclaim failures ...
    reclaimed = [c for op, c in events if op == "reclaim"]
    assert fix0 in reclaimed
    assert not any(f["op"] == "reclaim" for f in r["failures"])
    # ... and that reclaim ran BEFORE the first archive (reclaim-running-FIRST).
    reclaim_fix0_idx = next(i for i, (op, c) in enumerate(events) if op == "reclaim" and c == fix0)
    first_archive_idx = next(i for i, (op, _c) in enumerate(events) if op == "archive")
    assert reclaim_fix0_idx < first_archive_idx
    # ... and the whole run + root archived (full teardown).
    rv2 = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=root)
    assert all(rv2.status[c] == "archived" for c in rv2.by_identity.values())
    assert tmp_board.status(root) == "archived"


def test_abandon_refuses_in_worker(as_worker, fake_ctx, tmp_board):
    with as_worker("t_w"):
        r = workflow_abandon(fake_ctx, root_id="t_x", board=tmp_board.name)
    assert "orchestrator" in r["error"]


def test_approve_refuses_in_worker(as_worker, fake_ctx, tmp_board):
    with as_worker("t_w"):
        r = workflow_approve(fake_ctx, gate_card="t_x", board=tmp_board.name)
    assert "orchestrator" in r["error"]


def test_reconcile_dedup_keeps_done_duplicate(fake_ctx, tmp_board, tmp_path):
    from hermes_workflow.engine.provenance import Sentinel, embed_sentinel
    from hermes_workflow.version import PLUGIN_VERSION, SCHEMA_VERSION

    repo = _init_git_repo(tmp_path)
    root = _start(fake_ctx, tmp_board, repo)
    _advance_to_fanout(fake_ctx, tmp_board, root)

    rv = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=root)
    fix0 = rv.card_id_for(("fix", 0, 0))
    scan = rv.card_id_for(("scan", 0, 0))
    approve = rv.card_id_for(("approve", 0, 0))

    # A second LIVE card sharing fix0's sentinel identity (the create-key race).
    sent = Sentinel(root, "fix", 0, 0, "demo", "0.1.0", PLUGIN_VERSION, SCHEMA_VERSION)
    dup = tmp_board.create(title="dup fix", parents=[scan], assignee="coder",
                           workspace_kind="dir", workspace_path=str(repo),
                           body=embed_sentinel("dup", sent))
    tmp_board.link(dup, approve)            # dup is also a parent of the join
    tmp_board.complete(fix0, metadata={})   # the ORIGINAL fix0 is done; dup stays ready

    r = workflow_reconcile(fake_ctx, root_id=root, board=tmp_board.name,
                           kb=tmp_board.kb, conn=tmp_board.conn)

    assert tmp_board.status(fix0) == "done"        # the done duplicate kept
    assert tmp_board.status(dup) == "archived"     # the empty duplicate archived
    assert dup in r["deduped"]
