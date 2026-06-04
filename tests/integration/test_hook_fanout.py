import json, subprocess, pathlib, pytest
pytestmark = pytest.mark.integration


def _init_git_repo(tmp_path):
    repo = tmp_path / "repo"; repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    (repo / "f").write_text("x")
    subprocess.run(["git", "add", "f"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.email=a@b.c", "-c", "user.name=a", "commit", "-m", "init"],
                   cwd=repo, check=True, capture_output=True)
    return repo


def test_hook_fans_out_on_scan_complete(fake_ctx, tmp_board, seed_run, as_worker, tmp_path):
    from hermes_workflow.hooks import on_tool_done
    from hermes_workflow.runview import RunView
    repo = _init_git_repo(tmp_path)
    seeded = seed_run(params={"repo": str(repo)})
    meta = {"flaky": [{"test_id": "T1", "file": "a.py"}, {"test_id": "T2", "file": "b.py"}]}
    tmp_board.complete(seeded.scan_id, metadata=meta)
    # Fire the hook IN the worker's context (HERMES_KANBAN_TASK set) — this also
    # closes the §14 open question: hook-created cards via dispatch_tool must NOT
    # trip created_cards/HallucinatedCardsError.
    with as_worker(seeded.scan_id):
        on_tool_done(ctx=fake_ctx, tool_name="kanban_complete",
                     args={"task_id": seeded.scan_id, "metadata": meta},
                     result=json.dumps({"ok": True, "task_id": seeded.scan_id, "run_id": 1}),
                     task_id=seeded.scan_id)
    rv = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=seeded.root_id)
    assert rv.card_id_for(("fix", 0, 0)) and rv.card_id_for(("fix", 1, 0))   # fan-out happened
    assert rv.card_id_for(("approve", 0, 0))                                  # join created (R5)


def test_hook_never_raises_on_garbage(fake_ctx, tmp_board):
    from hermes_workflow.hooks import on_tool_done
    # pure side-effect: any internal error is swallowed (fail-open). Must not raise.
    on_tool_done(ctx=fake_ctx, tool_name="kanban_complete", args=None, result="not-json", task_id="t_x")
    on_tool_done(ctx=fake_ctx, tool_name="some_other_tool", args={}, result="{}", task_id="t_y")


def test_hook_version_mismatch_comments_root_and_does_not_fan_out(fake_ctx, tmp_board, seed_run, as_worker, tmp_path):
    from hermes_workflow.hooks import on_tool_done
    from hermes_workflow.runview import RunView
    from hermes_workflow.board import WorkerBoard
    repo = _init_git_repo(tmp_path)
    # seed a run whose ROOT snapshot stamps an UNSUPPORTED schema_version
    seeded = seed_run(params={"repo": str(repo)}, schema_version="9.9")
    meta = {"flaky": [{"test_id": "T1", "file": "a.py"}]}
    tmp_board.complete(seeded.scan_id, metadata=meta)
    with as_worker(seeded.scan_id):
        on_tool_done(ctx=fake_ctx, tool_name="kanban_complete",
                     args={"task_id": seeded.scan_id, "metadata": meta},
                     result=json.dumps({"ok": True, "task_id": seeded.scan_id}),
                     task_id=seeded.scan_id)
    rv = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=seeded.root_id)
    assert rv.card_id_for(("fix", 0, 0)) is None    # NO fan-out on version mismatch
    root = WorkerBoard(fake_ctx, board=tmp_board.name).show(seeded.root_id)
    assert any("schema_version" in c.get("body", "") for c in root["comments"])  # visible refuse
