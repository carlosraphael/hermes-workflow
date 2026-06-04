import pytest
pytestmark = pytest.mark.integration


def test_runview_enumerates_existing_identities(fake_ctx, tmp_board, seed_run):
    from hermes_workflow.runview import RunView
    seeded = seed_run()
    rv = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=seeded.root_id)
    idents = {(i.stage_id, i.fan_index, i.attempt) for i in rv.existing}
    assert ("scan", 0, 0) in idents
    assert rv.card_id_for(("scan", 0, 0)) == seeded.scan_id
    # the root has no sentinel -> it is NOT a stage identity
    assert seeded.root_id not in rv.by_identity.values()


def test_runview_reads_completed_metadata_after_done(fake_ctx, tmp_board, seed_run):
    from hermes_workflow.runview import RunView
    seeded = seed_run()
    flaky = [{"test_id": "T1", "file": "a.py"}, {"test_id": "T2", "file": "b.py"}]
    tmp_board.complete(seeded.scan_id, metadata={"flaky": flaky})
    rv = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=seeded.root_id)
    assert rv.completed["scan"] == {"flaky": flaky}
    assert rv.status[seeded.scan_id] == "done"


def test_runview_omits_completed_for_not_done_stage(fake_ctx, tmp_board, seed_run):
    from hermes_workflow.runview import RunView
    seeded = seed_run()
    rv = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=seeded.root_id)
    assert "scan" not in rv.completed


def test_runview_reads_completed_metadata_via_db_handle(fake_ctx, tmp_board, seed_run):
    # Exercises the kb.latest_run branch of _latest_done_metadata (Fix 1): a
    # normally-completed card's latest run IS its completing run, so the db path
    # returns the same metadata the worker-context path would.
    from hermes_workflow.runview import RunView
    seeded = seed_run()
    flaky = [{"test_id": "T1", "file": "a.py"}, {"test_id": "T2", "file": "b.py"}]
    tmp_board.complete(seeded.scan_id, metadata={"flaky": flaky})
    rv = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=seeded.root_id,
                           kb=tmp_board.kb, conn=tmp_board.conn)
    assert rv.completed["scan"] == {"flaky": flaky}


def test_runview_dedups_diamond_join(fake_ctx, tmp_board, seed_run):
    # A join card reached via two parents must be walked exactly once (the
    # seen-set dedup). The test passing at all proves no infinite loop.
    from hermes_workflow.runview import RunView
    from hermes_workflow.engine.provenance import embed_sentinel, Sentinel
    from hermes_workflow.version import PLUGIN_VERSION, SCHEMA_VERSION
    seeded = seed_run()
    root_id = seeded.root_id

    def _stamp(stage_id, parents):
        sent = Sentinel(root_id, stage_id, 0, 0, "demo", "0.1.0",
                        PLUGIN_VERSION, SCHEMA_VERSION)
        return tmp_board.create(title=stage_id, parents=parents,
                                body=embed_sentinel(f"{stage_id} body", sent))

    a_id = _stamp("a", [root_id])
    b_id = _stamp("b", [root_id])
    j_id = _stamp("j", [a_id, b_id])  # join reachable from root via two paths

    rv = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=root_id)

    assert rv.card_id_for(("j", 0, 0)) == j_id
    assert len([i for i in rv.existing if i.stage_id == "j"]) == 1
