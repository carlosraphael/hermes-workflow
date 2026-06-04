# tests/integration/test_spike_abandon.py
# Spike 5 — abandon: leaves-first archive, host-only archive, worktree preserved.
# Behaviors pre-confirmed by the controller (live runs); these encode them against
# the real hermes_cli.kanban_db (no LLM). See tests/SPIKES.md "Spike 5".
import pathlib

import pytest

pytestmark = pytest.mark.integration


def test_leaves_first_archive_avoids_transient_ready(tmp_board, mk_card):
    parent = mk_card(title="parent")                                    # no parents -> ready
    child = mk_card(title="leaf", parents=[parent], assignee="real-profile")  # -> todo
    assert tmp_board.status(child) == "todo"
    # SAFE order: archive the leaf child FIRST, then the parent.
    assert tmp_board.archive(child) is True
    assert tmp_board.status(child) == "archived"
    assert tmp_board.archive(parent) is True
    # the parent's archive triggers recompute_ready, but the child is already
    # archived, so it must NOT be transiently promoted to 'ready'
    assert tmp_board.status(child) == "archived"
    assert tmp_board.status(parent) == "archived"


def test_parent_first_archive_transiently_promotes_child(tmp_board, mk_card):
    # Documents WHY leaves-first matters: archiving a parent first DOES promote
    # the todo child to 'ready' (the transient-ready hazard abandon must avoid).
    parent = mk_card(title="parent")
    child = mk_card(title="leaf", parents=[parent], assignee="real-profile")
    assert tmp_board.status(child) == "todo"
    assert tmp_board.archive(parent) is True
    assert tmp_board.status(child) == "ready"        # <-- the hazard, confirmed
    # and archiving an already-archived task returns False (idempotent guard)
    assert tmp_board.archive(parent) is False


def test_archive_preserves_dir_workspace(tmp_board, mk_card, tmp_path):
    # archive_task contains NO _cleanup_workspace call (cleanup is a COMPLETION
    # path behavior, and even then only removes 'scratch'). A 'dir' workspace
    # with a sentinel file must survive an archive untouched.
    ws = tmp_path / "ws_dir"
    ws.mkdir()
    sentinel = ws / "keepme.txt"
    sentinel.write_text("preserved")
    card = mk_card(title="dir-ws", workspace_kind="dir", workspace_path=str(ws))
    assert tmp_board.archive(card) is True
    assert tmp_board.status(card) == "archived"
    assert pathlib.Path(sentinel).exists()
    assert pathlib.Path(sentinel).read_text() == "preserved"
