# tests/integration/test_end_to_end.py
import json, pathlib, pytest

pytestmark = pytest.mark.integration

# The fan-out smoke fixture owned by the integration suite (sibling fixtures/ dir).
EXAMPLE = pathlib.Path(__file__).parent / "fixtures" / "fanout-smoke.workflow.yaml"


def test_full_run(fake_ctx, tmp_board, wf_repo, stub_preflight_ok):
    from hermes_workflow.tools import workflow_start, workflow_status, workflow_approve
    from hermes_workflow.hooks import on_tool_done
    from hermes_workflow.runview import RunView

    tpl = EXAMPLE.read_text()
    r = workflow_start(fake_ctx, template_text=tpl, params={"repo": str(tmp_board.repo)},
                       bindings={"scout": "designer", "fixer": "coder", "reporter": "writer"},
                       board=tmp_board.name)
    root = r["root_id"]
    rv = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=root)
    scan = rv.card_id_for(("scan", 0, 0))

    # 1) scan worker completes with two flaky tests -> hook fans out
    meta = {"flaky": [{"test_id": "T1", "file": "a.py"}, {"test_id": "T2", "file": "b.py"}]}
    tmp_board.complete(scan, metadata=meta)
    on_tool_done(ctx=fake_ctx, tool_name="kanban_complete",
                 args={"task_id": scan, "metadata": meta},
                 result=json.dumps({"ok": True, "task_id": scan, "run_id": 1}), task_id=scan)

    rv = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=root)
    fix0, fix1 = rv.card_id_for(("fix", 0, 0)), rv.card_id_for(("fix", 1, 0))
    gate = rv.card_id_for(("approve", 0, 0))
    assert fix0 and fix1 and gate
    assert tmp_board.status(gate) == "todo"          # gated until both fix done

    # 2) both fix workers commit + complete
    for fcid in (fix0, fix1):
        tmp_board.complete(fcid, metadata={"branch": "wf/..."})
    rv = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=root)
    assert tmp_board.status(gate) == "ready"         # promoted; awaiting approval

    st = workflow_status(fake_ctx, root_id=root, board=tmp_board.name)
    assert st["awaiting_approval"]

    # 3) human approves -> report promotes
    workflow_approve(fake_ctx, gate_card=gate, board=tmp_board.name)
    assert tmp_board.status(gate) == "done"
