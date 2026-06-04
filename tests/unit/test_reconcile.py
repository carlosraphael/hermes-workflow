import pytest
from hermes_workflow.engine.reconcile import pick_winner, CardRow


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
