from hermes_workflow.engine.template import parse_template
from hermes_workflow.engine.graph import cards_for_run, Identity

TPL = """
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


def _ctx():
    t = parse_template(TPL)
    params = {"repo": "/r"}
    bindings = {"scout": "designer", "fixer": "coder", "reporter": "writer"}
    return t, params, bindings


def test_prefix_only_at_start():
    t, params, bindings = _ctx()
    specs = cards_for_run(t, params, bindings, completed={}, existing=set())
    ids = {s.identity.stage_id for s in specs}
    assert ids == {"scan"}            # only the dynamic-free prefix
    assert specs[0].assignee == "designer"


def test_fanout_after_source_completes():
    t, params, bindings = _ctx()
    completed = {"scan": {"flaky": [{"test_id": "T1", "file": "a.py"}, {"test_id": "T2", "file": "b.py"}]}}
    existing = {Identity("scan", 0, 0)}
    specs = cards_for_run(t, params, bindings, completed=completed, existing=existing)
    fix = sorted([s for s in specs if s.identity.stage_id == "fix"], key=lambda s: s.identity.fan_index)
    assert [s.identity.fan_index for s in fix] == [0, 1]
    assert fix[0].title == "fix T1" and fix[0].body == "fix a.py"
    assert fix[0].assignee == "coder" and fix[0].skills == ["kanban-codex-lane"]
    approve = next(s for s in specs if s.identity.stage_id == "approve")
    assert approve.gate is True and approve.assignee == "_workflow_gate"
    # join 'approve' is parented to BOTH fix instances
    assert set(approve.parent_identities) == {Identity("fix", 0, 0), Identity("fix", 1, 0)}
    report = next(s for s in specs if s.identity.stage_id == "report")
    assert Identity("approve", 0, 0) in report.parent_identities
    assert {Identity("fix", 0, 0), Identity("fix", 1, 0)} <= set(report.parent_identities)


def test_empty_fanout_wires_join_to_source():
    t, params, bindings = _ctx()
    completed = {"scan": {"flaky": []}}
    existing = {Identity("scan", 0, 0)}
    specs = cards_for_run(t, params, bindings, completed=completed, existing=existing)
    assert not any(s.identity.stage_id == "fix" for s in specs)   # no children
    approve = next(s for s in specs if s.identity.stage_id == "approve")
    assert approve.parent_identities == [Identity("scan", 0, 0)]  # gated on the source


def test_existing_cards_are_not_recreated():
    t, params, bindings = _ctx()
    completed = {"scan": {"flaky": [{"test_id": "T1", "file": "a.py"}]}}
    existing = {Identity("scan", 0, 0), Identity("fix", 0, 0), Identity("approve", 0, 0)}
    specs = cards_for_run(t, params, bindings, completed=completed, existing=existing)
    assert all(s.identity not in existing for s in specs)         # idempotent: only missing cards


def test_partial_fanout_reconcile_creates_only_missing_and_relinks_join():
    # scan emitted 3 items; fix#0 already exists. Reconcile must create ONLY the
    # missing fix instances and wire the join 'approve' to ALL three fix instances.
    t, params, bindings = _ctx()
    completed = {"scan": {"flaky": [
        {"test_id": "T1", "file": "a.py"},
        {"test_id": "T2", "file": "b.py"},
        {"test_id": "T3", "file": "c.py"},
    ]}}
    existing = {Identity("scan", 0, 0), Identity("fix", 0, 0)}
    specs = cards_for_run(t, params, bindings, completed=completed, existing=existing)

    created_fix = sorted(
        (s for s in specs if s.identity.stage_id == "fix"),
        key=lambda s: s.identity.fan_index,
    )
    assert [s.identity.fan_index for s in created_fix] == [1, 2]   # only the missing children
    assert Identity("fix", 0, 0) not in {s.identity for s in specs}  # existing not recreated

    approve = next(s for s in specs if s.identity.stage_id == "approve")
    assert set(approve.parent_identities) == {
        Identity("fix", 0, 0), Identity("fix", 1, 0), Identity("fix", 2, 0),
    }  # join re-linked across ALL instances, incl. the pre-existing one
