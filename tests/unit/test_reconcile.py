import pytest
from hermes_workflow.engine.graph import Identity
from hermes_workflow.engine.reconcile import CardNode, CardRow, pick_winner, plan_collapse
from hermes_workflow.engine.template import parse_template


def _row(cid, status, run_id=None, created_at=0):
    return CardRow(card_id=cid, status=status, latest_run_id=run_id, created_at=created_at)


def test_done_beats_running_regardless_of_id():
    rows = [_row("t_z", "done", run_id=5), _row("t_a", "running")]
    assert pick_winner(rows).card_id == "t_z"


def test_multi_done_tiebreak_by_run_id_then_created_then_id():
    rows = [_row("t_b", "done", run_id=10, created_at=2), _row("t_a", "done", run_id=20, created_at=1)]
    assert pick_winner(rows).card_id == "t_a"   # higher run_id wins


def test_no_done_ranks_by_status_then_id():
    rows = [_row("t_y", "todo"), _row("t_x", "running")]
    assert pick_winner(rows).card_id == "t_x"   # running > todo


def test_created_at_tiebreak_when_run_id_equal():
    # equal status + equal run_id -> larger created_at wins
    rows = [_row("t_a", "done", run_id=5, created_at=1), _row("t_b", "done", run_id=5, created_at=9)]
    assert pick_winner(rows).card_id == "t_b"


def test_card_id_is_final_tiebreak_min_wins():
    # equal status/run_id/created_at -> smallest card_id wins (must be correct for prefix ids too)
    rows = [_row("t_ab", "done", run_id=7, created_at=3), _row("t_a", "done", run_id=7, created_at=3)]
    assert pick_winner(rows).card_id == "t_a"


def test_empty_rows_raises():
    with pytest.raises(ValueError):
        pick_winner([])


# ---------------------------------------------------------------------------
# plan_collapse: the pure duplicate-collapse planner (group -> winner -> plan).
# A fan-out template whose joins are template-derived: a child is a join of a
# stage iff its stage `needs` that stage. Joins of `fix`: approve, report.
# Joins of `approve`: report. `scan` is nobody's join; `fix` is scan's join.
# ---------------------------------------------------------------------------

TPL = """
name: demo
version: 0.1.0
params: { repo: { type: string, required: true } }
roles: { scout: { lane: profile }, fixer: { lane: codex }, reporter: { lane: profile } }
stages:
  - { id: scan, role: scout, expand_out: { key: flaky, max: 50, item: { test_id: string } } }
  - { id: fix, role: fixer, needs: [scan], expand: { over: scan.flaky, as: t } }
  - { id: approve, needs: [fix], gate: human }
  - { id: report, role: reporter, needs: [approve, fix] }
"""


def _node(card_id, stage, *, fan=0, attempt=0, status="todo", run_id=None,
          created=0.0, parents=(), children=()):
    return CardNode(card_id=card_id, identity=Identity(stage, fan, attempt),
                    status=status, latest_run_id=run_id, created_at=created,
                    parents=tuple(parents), children=tuple(children))


def test_no_duplicates_yields_empty_plan():
    t = parse_template(TPL)
    nodes = [_node("c_scan", "scan", status="done"), _node("c_fix", "fix", status="running")]
    plan = plan_collapse(t, nodes)
    assert plan.relink == () and plan.archive == () and plan.reclaim == ()


def test_collapse_archives_losers_keeps_winner():
    t = parse_template(TPL)
    nodes = [_node("fix_done", "fix", status="done", run_id=5),
             _node("fix_dup", "fix", status="todo")]
    plan = plan_collapse(t, nodes)
    assert plan.archive == ("fix_dup",)        # the non-winner is retired
    assert "fix_done" not in plan.archive       # the winner survives
    assert plan.reclaim == ()                    # no running loser


def test_archived_duplicate_is_not_recollapsed():
    # Only one LIVE card for the identity -> nothing to collapse.
    t = parse_template(TPL)
    nodes = [_node("fix_done", "fix", status="done", run_id=5),
             _node("fix_old", "fix", status="archived")]
    plan = plan_collapse(t, nodes)
    assert plan.archive == ()


def test_relink_emitted_only_for_missing_join_edges():
    # loser's join 'approve' is not yet parented by the winner -> emit the edge;
    # loser's join 'report' is ALREADY parented by the winner -> idempotent skip.
    t = parse_template(TPL)
    approve = _node("c_approve", "approve", parents=("fix_dup",))
    report = _node("c_report", "report", parents=("fix_done", "fix_dup"))
    fix_done = _node("fix_done", "fix", status="done", run_id=9, children=("c_report",))
    fix_dup = _node("fix_dup", "fix", status="todo", children=("c_approve", "c_report"))
    plan = plan_collapse(t, [fix_done, fix_dup, approve, report])
    assert ("fix_done", "c_approve") in plan.relink      # missing edge re-pointed
    assert ("fix_done", "c_report") not in plan.relink   # winner already parents it
    assert plan.archive == ("fix_dup",)


def test_relink_filters_non_join_children():
    # A loser's child that does NOT fan in over the loser's stage must not be
    # re-pointed (it is a successor, not a join). 'report' needs approve -> join;
    # 'fix' needs scan, not approve -> NOT a join of approve.
    t = parse_template(TPL)
    c_report = _node("c_report", "report")
    c_fix = _node("c_fix", "fix")
    ap_done = _node("ap_done", "approve", status="done", run_id=3)
    ap_dup = _node("ap_dup", "approve", status="todo", children=("c_report", "c_fix"))
    plan = plan_collapse(t, [ap_done, ap_dup, c_report, c_fix])
    assert ("ap_done", "c_report") in plan.relink     # genuine fan-in join
    assert ("ap_done", "c_fix") not in plan.relink     # non-join child left alone


def test_running_loser_is_reclaimed_and_archived():
    t = parse_template(TPL)
    nodes = [_node("fix_done", "fix", status="done", run_id=5),
             _node("fix_run", "fix", status="running")]
    plan = plan_collapse(t, nodes)
    assert plan.reclaim == ("fix_run",)
    assert plan.archive == ("fix_run",)


def test_distinct_identities_collapse_independently():
    t = parse_template(TPL)
    nodes = [_node("a_done", "fix", fan=0, status="done", run_id=1),
             _node("a_dup", "fix", fan=0, status="todo"),
             _node("b_done", "fix", fan=1, status="done", run_id=1),
             _node("b_dup", "fix", fan=1, status="todo")]
    plan = plan_collapse(t, nodes)
    assert set(plan.archive) == {"a_dup", "b_dup"}


def test_shared_join_relinked_once():
    # Two losers of one identity share a single join; the winner is re-pointed
    # to it exactly once (no duplicate edge).
    t = parse_template(TPL)
    c_join = _node("c_approve", "approve")
    winner = _node("fix_w", "fix", status="done", run_id=9)
    l1 = _node("fix_l1", "fix", status="todo", children=("c_approve",))
    l2 = _node("fix_l2", "fix", status="todo", children=("c_approve",))
    plan = plan_collapse(t, [winner, l1, l2, c_join])
    assert plan.relink.count(("fix_w", "c_approve")) == 1
    assert set(plan.archive) == {"fix_l1", "fix_l2"}
