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
