import pytest

pytestmark = pytest.mark.integration


def test_sentinel_assignees_are_nonspawnable(tmp_board, monkeypatch):
    # The design relies on ``_``-prefixed sentinel assignees (_workflow_root,
    # _workflow_gate) NEVER auto-spawning a worker. dispatch_once buckets a
    # ready card into DispatchResult.skipped_nonspawnable when its assignee is
    # not a real Hermes profile (kanban_db.py:5974-5986: a local
    # ``from hermes_cli.profiles import profile_exists`` + ``not
    # profile_exists(...)`` -> skipped_nonspawnable).
    #
    # CONTRAST: monkeypatch profile_exists so ONLY non-underscore names exist.
    # This proves the underscore rule specifically, independent of whether any
    # real profiles happen to live in the tmp HERMES_HOME.
    import hermes_cli.profiles as profiles
    monkeypatch.setattr(profiles, "profile_exists", lambda name: not str(name).startswith("_"))

    # Two no-parent cards (=> created directly 'ready', kanban_db.py:2021-2022):
    # a spawnable real-profile card and a sentinel gate card.
    real = tmp_board.create(title="real", assignee="designer")
    gate = tmp_board.create(title="gate", assignee="_workflow_gate")

    res = tmp_board.kb.dispatch_once(
        tmp_board.conn, dry_run=True,
        spawn_fn=lambda *a, **k: 12345, board=tmp_board.name,
    )

    # res.spawned elements are (id, assignee, "") tuples (kanban_db.py:6022).
    spawned_ids = {row[0] for row in res.spawned}

    assert gate in res.skipped_nonspawnable      # sentinel never spawns
    assert gate not in spawned_ids
    assert real in spawned_ids                   # a real profile WOULD spawn (dry-run)
    assert real not in res.skipped_nonspawnable
