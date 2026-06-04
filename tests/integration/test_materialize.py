import pathlib
import subprocess

import pytest

pytestmark = pytest.mark.integration


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


def test_materialize_creates_join_wired_to_all_instances(fake_ctx, tmp_board, seed_run, tmp_path):
    from hermes_workflow.materialize import materialize
    from hermes_workflow.runview import RunView
    from hermes_workflow.board import WorkerBoard

    repo = _init_git_repo(tmp_path)
    seeded = seed_run(params={"repo": str(repo)})
    flaky = [{"test_id": "T1", "file": "a.py"}, {"test_id": "T2", "file": "b.py"}]
    tmp_board.complete(seeded.scan_id, metadata={"flaky": flaky})

    rv = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=seeded.root_id)
    materialize(fake_ctx, board=tmp_board.name, root_id=seeded.root_id, runview=rv)

    rv2 = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=seeded.root_id)
    fix0, fix1 = rv2.card_id_for(("fix", 0, 0)), rv2.card_id_for(("fix", 1, 0))
    approve_cid = rv2.card_id_for(("approve", 0, 0))
    assert fix0 and fix1 and approve_cid

    wb = WorkerBoard(fake_ctx, board=tmp_board.name)
    approve = wb.show(approve_cid)
    assert set(approve["parents"]) >= {fix0, fix1}     # join wired to ALL instances (R5)
    assert tmp_board.status(approve_cid) == "todo"     # gated until both fix done
    assert approve["title"] == "approve"               # title falls back to stage_id (gate has no title)

    # worktree -> dir conversion: each fix card has a provisioned dir workspace
    fix0_card = wb.show(fix0)
    assert fix0_card["workspace_kind"] == "dir"
    assert fix0_card["workspace_path"] and pathlib.Path(fix0_card["workspace_path"], ".git").exists()


def test_materialize_is_idempotent(fake_ctx, tmp_board, seed_run, tmp_path):
    from hermes_workflow.materialize import materialize
    from hermes_workflow.runview import RunView

    repo = _init_git_repo(tmp_path)
    seeded = seed_run(params={"repo": str(repo)})
    tmp_board.complete(seeded.scan_id, metadata={"flaky": [{"test_id": "T1", "file": "a.py"}]})

    rv = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=seeded.root_id)
    first = materialize(fake_ctx, board=tmp_board.name, root_id=seeded.root_id, runview=rv)
    assert first  # created some cards

    rv2 = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=seeded.root_id)
    second = materialize(fake_ctx, board=tmp_board.name, root_id=seeded.root_id, runview=rv2)
    assert second == {}  # nothing new to create (cards_for_run excludes existing identities)


def test_materialized_body_carries_lifecycle_preamble(fake_ctx, tmp_board, seed_run, tmp_path):
    # materialize.py:93 prepends LIFECYCLE_PREAMBLE to every materialized card's
    # body. Pin it on a card the ENGINE materialized (a fix instance) so a future
    # regression that drops the lifecycle instructions is caught.
    from hermes_workflow.materialize import materialize, LIFECYCLE_PREAMBLE
    from hermes_workflow.runview import RunView
    from hermes_workflow.board import WorkerBoard

    repo = _init_git_repo(tmp_path)
    seeded = seed_run(params={"repo": str(repo)})
    tmp_board.complete(seeded.scan_id, metadata={"flaky": [{"test_id": "T1", "file": "a.py"}]})

    rv = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=seeded.root_id)
    materialize(fake_ctx, board=tmp_board.name, root_id=seeded.root_id, runview=rv)

    rv2 = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=seeded.root_id)
    fix0 = rv2.card_id_for(("fix", 0, 0))
    assert fix0

    body = WorkerBoard(fake_ctx, board=tmp_board.name).show(fix0)["body"]
    assert LIFECYCLE_PREAMBLE.strip().split(chr(10))[0] in body   # the "## workflow stage" heading
    assert "## workflow stage" in body
    assert "kanban_complete" in body                              # the complete-via instruction


def test_materialize_empty_fanout_wires_join_to_source(fake_ctx, tmp_board, seed_run, tmp_path):
    # Empty fan-out: the engine wires the consumer (approve) to the fan-out
    # SOURCE (scan) instead of any fix instances. Verify the materializer
    # resolves that scan identity and creates NO fix cards.
    from hermes_workflow.materialize import materialize
    from hermes_workflow.runview import RunView
    from hermes_workflow.board import WorkerBoard

    repo = _init_git_repo(tmp_path)
    seeded = seed_run(params={"repo": str(repo)})
    tmp_board.complete(seeded.scan_id, metadata={"flaky": []})

    rv = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=seeded.root_id)
    materialize(fake_ctx, board=tmp_board.name, root_id=seeded.root_id, runview=rv)

    rv2 = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=seeded.root_id)
    assert rv2.card_id_for(("fix", 0, 0)) is None       # no fix cards on empty fan-out
    approve_cid = rv2.card_id_for(("approve", 0, 0))
    assert approve_cid

    wb = WorkerBoard(fake_ctx, board=tmp_board.name)
    approve = wb.show(approve_cid)
    assert seeded.scan_id in approve["parents"]          # join wired to the fan-out source


# A minimal gate-less join: ``collect`` needs the ``work`` fan-out directly (it is
# a child of EVERY work instance, no human gate). ``dir:`` workspaces need no git
# repo. Drives the join promotion (todo -> ready only when ALL fan-out done).
JOIN_TPL = """
name: join-demo
version: 0.1.0
params: { repo: { type: string, required: true } }
roles: { scout: { lane: profile }, worker: { lane: profile } }
stages:
  - { id: scan, role: scout, title: "scan", workspace: "dir:${params.repo}",
      expand_out: { key: items, max: 50, item: { id: string } } }
  - { id: work, role: worker, needs: [scan], expand: { over: scan.items, as: it },
      title: "work ${it.id}", workspace: "dir:${params.repo}" }
  - { id: collect, role: worker, needs: [work], title: "collect" }
"""


def test_gateless_join_waits_for_all_fanout_instances(fake_ctx, tmp_board, tmp_path, monkeypatch):
    from hermes_workflow.tools import workflow_start
    from hermes_workflow.materialize import materialize
    from hermes_workflow.runview import RunView

    # Stub the per-profile preflight probe green (scout/worker aren't real
    # profiles) and clear the orchestrator-context guard so workflow_start seeds.
    monkeypatch.delenv("HERMES_KANBAN_TASK", raising=False)
    monkeypatch.setattr(
        "hermes_workflow.tools.probe_profiles",
        lambda profiles, **kw: {p: {"ok": True, "error": None} for p in profiles},
    )

    root = workflow_start(
        fake_ctx, template_text=JOIN_TPL, params={"repo": str(tmp_path)},
        bindings={"scout": "designer", "worker": "coder"}, board=tmp_board.name,
    )["root_id"]

    # Complete scan with 2 items, then materialize the fan-out (work0, work1) + join.
    rv = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=root)
    scan = rv.card_id_for(("scan", 0, 0))
    tmp_board.complete(scan, metadata={"items": [{"id": "A"}, {"id": "B"}]})
    rv2 = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=root)
    materialize(fake_ctx, board=tmp_board.name, root_id=root, runview=rv2)

    rv3 = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=root)
    work0 = rv3.card_id_for(("work", 0, 0))
    work1 = rv3.card_id_for(("work", 1, 0))
    collect = rv3.card_id_for(("collect", 0, 0))
    assert work0 and work1 and collect

    # Two incomplete work parents -> the gate-less join stays todo.
    assert tmp_board.status(collect) == "todo"

    # Completing ONE work instance is not enough: still todo.
    tmp_board.complete(work0, metadata={})
    assert tmp_board.status(collect) == "todo"

    # Completing the OTHER instance promotes the join to ready (all parents done).
    tmp_board.complete(work1, metadata={})
    assert tmp_board.status(collect) == "ready"
