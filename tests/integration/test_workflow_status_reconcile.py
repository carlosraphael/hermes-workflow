import subprocess

import pytest

from hermes_workflow.board import HostBoard, WorkerBoard
from hermes_workflow.runview import RunView
from hermes_workflow.materialize import materialize
from hermes_workflow.tools import (
    workflow_reconcile,
    workflow_start,
    workflow_status,
    workflow_validate,
)

pytestmark = pytest.mark.integration


# scan -> fix (fan-out) -> approve (human gate) -> report. Copied from
# tests/conftest.py's DEMO_TPL; fix is a worktree stage so materialize needs
# a real git repo (see _init_git_repo).
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


def _drop_one_fix(fake_ctx, tmp_board, root_id):
    """Fully detach + archive fix1 so the link-walk can't reach it."""
    fix1 = RunView.from_root(
        fake_ctx, board=tmp_board.name, root_id=root_id).card_id_for(("fix", 1, 0))
    card = WorkerBoard(fake_ctx, board=tmp_board.name).show(fix1)
    hb = HostBoard(tmp_board.kb, tmp_board.conn, tmp_board.name)
    for p in card["parents"]:
        hb.unlink(p, fix1)
    for c in card["children"]:
        hb.unlink(fix1, c)
    hb.archive(fix1)


@pytest.fixture(autouse=True)
def _stub_preflight(monkeypatch):
    monkeypatch.delenv("HERMES_KANBAN_TASK", raising=False)
    monkeypatch.setattr(
        "hermes_workflow.tools.probe_profiles",
        lambda profiles, **kw: {p: {"ok": True, "error": None} for p in profiles},
    )


def test_status_rollup_includes_pending_blocked_awaiting(fake_ctx, tmp_board, tmp_path):
    repo = _init_git_repo(tmp_path)
    root = _start(fake_ctx, tmp_board, repo)

    st = workflow_status(fake_ctx, root_id=root, board=tmp_board.name)

    assert st["stages"]["scan"]["state"] in ("ready", "todo", "running", "done")
    assert st["stages"]["fix"]["state"] == "pending"
    assert "awaiting_approval" in st
    assert "blocked_stages" in st
    assert "review_required" in st


def test_status_detects_review_required_backstop(fake_ctx, tmp_board, tmp_path):
    repo = _init_git_repo(tmp_path)
    root = _start(fake_ctx, tmp_board, repo)
    _advance_to_fanout(fake_ctx, tmp_board, root)

    fix0 = RunView.from_root(
        fake_ctx, board=tmp_board.name, root_id=root).card_id_for(("fix", 0, 0))
    tmp_board.kb.block_task(
        tmp_board.conn, fix0, reason="review-required: please review the approach")

    st = workflow_status(fake_ctx, root_id=root, board=tmp_board.name)

    assert st["review_required"]
    entry = st["review_required"][0]
    assert entry["card"] == fix0
    assert "unblock" in entry["remediation"]
    assert any(b["card"] == fix0 for b in st["blocked_stages"])


def test_validate_rejects_verify_and_nested_expand(fake_ctx):
    # verify: block is deferred to 0.2.x
    verify_tpl = """
name: v
version: 0.1.0
roles: { r: { lane: profile } }
stages:
  - { id: s, role: r, verify: { command: "make test" } }
"""
    r = workflow_validate(fake_ctx, template_text=verify_tpl)
    assert r["ok"] is False
    assert "verify" in r["error"] or "0.2" in r["error"]

    # nested expand: `fix` expands over scan AND is itself an expand source for `chain`
    nested_tpl = """
name: n
version: 0.1.0
params: { repo: { type: string, required: true } }
roles: { r: { lane: profile } }
stages:
  - { id: scan, role: r, workspace: "dir:${params.repo}",
      expand_out: { key: flaky, item: { test_id: string } } }
  - { id: fix, role: r, needs: [scan], expand: { over: scan.flaky, as: t },
      workspace: "dir:${params.repo}",
      expand_out: { key: more, item: { sub: string } } }
  - { id: chain, role: r, needs: [fix], expand: { over: fix.more, as: m },
      workspace: "dir:${params.repo}" }
"""
    r2 = workflow_validate(fake_ctx, template_text=nested_tpl)
    assert r2["ok"] is False

    # a valid template -> ok True
    assert workflow_validate(fake_ctx, template_text=DEMO_TPL_INLINE) == {"ok": True}


def test_reconcile_recreates_missing_fanout_and_relinks_join(fake_ctx, tmp_board, tmp_path):
    repo = _init_git_repo(tmp_path)
    root = _start(fake_ctx, tmp_board, repo)
    _advance_to_fanout(fake_ctx, tmp_board, root)
    _drop_one_fix(fake_ctx, tmp_board, root)

    workflow_reconcile(fake_ctx, root_id=root, board=tmp_board.name)

    rv = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=root)
    assert rv.card_id_for(("fix", 0, 0))
    fix1 = rv.card_id_for(("fix", 1, 0))
    assert fix1  # the dropped instance was recreated

    approve = rv.card_id_for(("approve", 0, 0))
    parents = set(WorkerBoard(fake_ctx, board=tmp_board.name).show(approve)["parents"])
    assert fix1 in parents  # recreated fix re-linked to the pre-existing join


def test_reconcile_refuses_in_worker(as_worker, fake_ctx, tmp_board, tmp_path):
    repo = _init_git_repo(tmp_path)
    root = _start(fake_ctx, tmp_board, repo)
    with as_worker("t_w"):
        r = workflow_reconcile(fake_ctx, root_id=root, board=tmp_board.name)
    assert "orchestrator" in r["error"]


def test_status_errors_on_non_workflow_root(fake_ctx, tmp_board):
    plain = tmp_board.create(title="plain", body="no snapshot here")
    r = workflow_status(fake_ctx, root_id=plain, board=tmp_board.name)
    assert "error" in r
