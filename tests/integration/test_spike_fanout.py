# tests/integration/test_spike_fanout.py
"""Spike 3 — atomic create-with-parents + fan-in promotion + late-link demotion.

Confirms against the REAL board (hermes_cli.kanban_db, no LLM) the three
behaviors that make reconcile's late re-link safe (Hermes v0.15.1 @ c47b9d12):

  1. create_task(parents=[a, b]) lands the join's status ATOMICALLY from the
     CURRENT parent statuses (todo while any parent is not done).
  2. A join wired to all parents promotes to `ready` exactly when the LAST
     parent completes (complete_task -> recompute_ready).
  3. A late link_tasks(child=join) of an INCOMPLETE parent demotes a `ready`
     join back to `todo` (link_tasks demotion, distinct from recompute_ready).

See tests/SPIKES.md "Spike 3" for the recorded signatures/behaviors.
"""
import pytest

pytestmark = pytest.mark.integration


def test_join_created_with_all_parents_lands_todo_until_all_done(tmp_board, mk_card, complete_card):
    a = mk_card(title="child a")
    b = mk_card(title="child b")
    join = mk_card(title="join", parents=[a, b], assignee="_workflow_gate")
    assert tmp_board.status(join) == "todo"     # not ready: parents not done
    complete_card(a)
    assert tmp_board.status(join) == "todo"     # still gated on b
    complete_card(b)
    assert tmp_board.status(join) == "ready"    # promoted exactly when last parent done


def test_linking_incomplete_parent_demotes_ready_join(tmp_board, mk_card, complete_card):
    a = mk_card(title="a")
    complete_card(a)
    join = mk_card(title="join", parents=[a], assignee="_workflow_gate")
    assert tmp_board.status(join) == "ready"
    c = mk_card(title="late child")             # incomplete (no parents -> lands 'ready', not done)
    tmp_board.link(parent=c, child=join)
    assert tmp_board.status(join) == "todo"     # demoted; safe for reconcile late re-link
