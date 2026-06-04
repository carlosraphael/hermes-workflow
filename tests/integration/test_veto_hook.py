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


def test_pre_blocks_bad_expand_out_shape(fake_ctx, tmp_board, seed_run):
    from hermes_workflow.hooks import on_tool_pre
    seeded = seed_run()  # scan is an expand_source (key=flaky, item={test_id,file})
    d = on_tool_pre(ctx=fake_ctx, tool_name="kanban_complete",
                    args={"task_id": seeded.scan_id, "metadata": {"flaky": [{"test_id": "T1"}]}},  # missing file
                    task_id=seeded.scan_id)
    assert d and d["action"] == "block" and "file" in d["message"]


def test_pre_passes_valid_expand_out(fake_ctx, tmp_board, seed_run):
    from hermes_workflow.hooks import on_tool_pre
    seeded = seed_run()
    d = on_tool_pre(ctx=fake_ctx, tool_name="kanban_complete",
                    args={"task_id": seeded.scan_id, "metadata": {"flaky": [{"test_id": "T1", "file": "a.py"}]}},
                    task_id=seeded.scan_id)
    assert d is None


def test_pre_blocks_over_max_via_hook(fake_ctx, tmp_board, seed_run):
    # over-max through the wired hook: the scan stage's expand_out.max is 50.
    from hermes_workflow.hooks import on_tool_pre
    seeded = seed_run()
    too_many = [{"test_id": f"T{i}", "file": f"f{i}.py"} for i in range(51)]
    d = on_tool_pre(ctx=fake_ctx, tool_name="kanban_complete",
                    args={"task_id": seeded.scan_id, "metadata": {"flaky": too_many}},
                    task_id=seeded.scan_id)
    assert d and d["action"] == "block" and "max" in d["message"]


def test_pre_passes_non_workflow_and_non_complete(fake_ctx, tmp_board):
    from hermes_workflow.hooks import on_tool_pre
    plain = tmp_board.create(title="plain")  # no sentinel
    assert on_tool_pre(ctx=fake_ctx, tool_name="kanban_complete", args={"task_id": plain}, task_id=plain) is None
    assert on_tool_pre(ctx=fake_ctx, tool_name="kanban_show", args={}, task_id="t") is None


def test_pre_blocks_on_version_mismatch(fake_ctx, tmp_board, seed_run):
    from hermes_workflow.hooks import on_tool_pre
    seeded = seed_run(schema_version="9.9")
    d = on_tool_pre(ctx=fake_ctx, tool_name="kanban_complete",
                    args={"task_id": seeded.scan_id, "metadata": {"flaky": [{"test_id": "T1", "file": "a.py"}]}},
                    task_id=seeded.scan_id)
    assert d and d["action"] == "block"


def test_pre_commit_clean_blocks_uncommitted_worktree(fake_ctx, tmp_board, seed_run, as_worker, tmp_path):
    from hermes_workflow.hooks import on_tool_done, on_tool_pre
    from hermes_workflow.runview import RunView
    from hermes_workflow.board import WorkerBoard
    repo = _init_git_repo(tmp_path)
    seeded = seed_run(params={"repo": str(repo)})
    tmp_board.complete(seeded.scan_id, metadata={"flaky": [{"test_id": "T1", "file": "a.py"}]})
    with as_worker(seeded.scan_id):                  # fan out -> fix cards get provisioned worktrees
        on_tool_done(ctx=fake_ctx, tool_name="kanban_complete",
                     args={"task_id": seeded.scan_id}, result=json.dumps({"ok": True}), task_id=seeded.scan_id)
    rv = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=seeded.root_id)
    fix0 = rv.card_id_for(("fix", 0, 0))
    fix0_card = WorkerBoard(fake_ctx, board=tmp_board.name).show(fix0)
    wt = fix0_card["workspace_path"]
    # freshly-provisioned worktree is clean -> pass
    assert on_tool_pre(ctx=fake_ctx, tool_name="kanban_complete", args={"task_id": fix0}, task_id=fix0) is None
    # introduce an uncommitted change -> block
    (pathlib.Path(wt) / "dirty.txt").write_text("x")
    d = on_tool_pre(ctx=fake_ctx, tool_name="kanban_complete", args={"task_id": fix0}, task_id=fix0)
    assert d and d["action"] == "block" and "commit" in d["message"].lower()


# D6-01: on_tool_pre is the workflow's ONLY blocking channel (a pre_tool_call veto).
# Per Spike 1 (tests/SPIKES.md), a pre_tool_call hook that RAISES fails OPEN — Hermes
# swallows the exception and allows the tool. So the hook's own except MUST veto by
# RETURNING a block dict and must NEVER raise / return None. These two tests drive that
# except branch by monkeypatching a post-sentinel call to raise on a real seeded card.
def test_pre_fails_closed_when_parse_root_body_raises(fake_ctx, tmp_board, seed_run, monkeypatch):
    from hermes_workflow import hooks
    seeded = seed_run()
    def _boom(*a, **k):
        raise RuntimeError("simulated internal failure after sentinel resolution")
    # call site (A): runs right after sentinel resolution (hooks.py).
    monkeypatch.setattr(hooks, "parse_root_body", _boom)
    d = hooks.on_tool_pre(ctx=fake_ctx, tool_name="kanban_complete",
                          args={"task_id": seeded.scan_id,
                                "metadata": {"flaky": [{"test_id": "T1", "file": "a.py"}]}},
                          task_id=seeded.scan_id)
    # The only blocking channel must FAIL CLOSED: a block dict, never None, never a raise.
    assert isinstance(d, dict)
    assert d.get("action") == "block"
    # Hermes blocks ONLY on a non-empty STR message (plugins.py get_pre_tool_call_block_message
    # checks isinstance(message, str) and truthiness); a non-str/empty message fails OPEN.
    assert isinstance(d.get("message"), str) and d["message"]


def test_pre_fails_closed_when_stage_gate_inputs_raises(fake_ctx, tmp_board, seed_run, monkeypatch):
    from hermes_workflow import hooks
    seeded = seed_run()
    def _boom(*a, **k):
        raise RuntimeError("simulated internal failure after sentinel resolution")
    # call site (B): runs AFTER parse_root_body + the version check have already succeeded.
    monkeypatch.setattr(hooks, "_stage_gate_inputs", _boom)
    d = hooks.on_tool_pre(ctx=fake_ctx, tool_name="kanban_complete",
                          args={"task_id": seeded.scan_id,
                                "metadata": {"flaky": [{"test_id": "T1", "file": "a.py"}]}},
                          task_id=seeded.scan_id)
    # The only blocking channel must FAIL CLOSED: a block dict, never None, never a raise.
    assert isinstance(d, dict)
    assert d.get("action") == "block"
    # Hermes blocks ONLY on a non-empty STR message (plugins.py get_pre_tool_call_block_message
    # checks isinstance(message, str) and truthiness); a non-str/empty message fails OPEN.
    assert isinstance(d.get("message"), str) and d["message"]
