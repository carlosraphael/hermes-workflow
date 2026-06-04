# tests/conftest.py
import contextlib, os, sys, pathlib, pytest

HERMES_ROOT = pathlib.Path(
    os.environ.get("HERMES_AGENT_ROOT", "/Users/carlos/cortex-workspace/hermes-agent")
)


@pytest.fixture(scope="session")
def hermes_root():
    if not (HERMES_ROOT / "hermes_cli").is_dir():
        pytest.skip(f"Hermes checkout not found at {HERMES_ROOT}; set HERMES_AGENT_ROOT")
    if str(HERMES_ROOT) not in sys.path:
        sys.path.insert(0, str(HERMES_ROOT))
    return HERMES_ROOT


@pytest.fixture
def register_pre_hook(hermes_root):
    """Register pre_tool_call callbacks on the global PluginManager singleton
    and guarantee exact removal in teardown.

    Hooks live in a process-global singleton (get_plugin_manager()._hooks),
    so any leak corrupts every subsequent test in the session. Teardown
    removes EXACTLY the callbacks this fixture appended (not a dict reset),
    and runs even if a test assertion fails.
    """
    from hermes_cli import plugins

    hooks = plugins.get_plugin_manager()._hooks.setdefault("pre_tool_call", [])
    added = []

    def _reg(cb):
        hooks.append(cb)
        added.append(cb)
        return cb

    try:
        yield _reg
    finally:
        for cb in added:
            try:
                hooks.remove(cb)
            except ValueError:
                pass


# ---------------------------------------------------------------------------
# Board fixtures (Spike 3) — thin wrapper over hermes_cli.kanban_db.
# Phase 1 Task 6 will extract a Board class into tests/integration/board.py;
# this inline _Board is the minimal precursor. CRITICAL: get_task(...) returns
# a Task OBJECT (attribute access .status, NOT ["status"]); create_task is
# keyword-only after conn; complete_task is keyword-only after task_id.
# ---------------------------------------------------------------------------


class _Board:
    def __init__(self, kb, conn, name):
        self.kb, self.conn, self.name = kb, conn, name

    def create(self, title, parents=(), assignee="_workflow_root", workspace_kind="scratch",
               workspace_path=None, body="", skills=None, idempotency_key=None):
        return self.kb.create_task(self.conn, title=title, body=body, assignee=assignee,
                                   parents=tuple(parents), workspace_kind=workspace_kind,
                                   workspace_path=workspace_path, skills=skills,
                                   idempotency_key=idempotency_key, board=self.name)

    def complete(self, tid, summary="done", metadata=None):
        return self.kb.complete_task(self.conn, tid, summary=summary, metadata=metadata or {})

    def link(self, parent, child):
        return self.kb.link_tasks(self.conn, parent_id=parent, child_id=child)

    def archive(self, tid):
        return self.kb.archive_task(self.conn, tid)

    def status(self, tid):
        return self.kb.get_task(self.conn, tid).status  # ATTRIBUTE access, not ["status"]


@pytest.fixture
def tmp_board(hermes_root, tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_KANBAN_BOARD", "test")
    from hermes_cli import kanban_db as kb

    conn = kb.connect(board="test")
    return _Board(kb, conn, "test")


@pytest.fixture
def mk_card(tmp_board):
    def _mk(**kw):
        return tmp_board.create(**kw)

    return _mk


@pytest.fixture
def complete_card(tmp_board):
    def _c(tid, **kw):
        return tmp_board.complete(tid, **kw)

    return _c


@pytest.fixture
def as_worker():
    """Run a block as a dispatcher-spawned worker scoped to ``task_id``.

    Sets ``HERMES_KANBAN_TASK`` (what _enforce_worker_task_ownership reads to
    decide a process is a worker, and what _handle_comment ignores for author)
    for the duration, restoring the prior value on exit. Self-contained
    save/restore so it composes with tests that don't otherwise touch the env.
    """
    @contextlib.contextmanager
    def _ctx(task_id):
        prev = os.environ.get("HERMES_KANBAN_TASK")
        os.environ["HERMES_KANBAN_TASK"] = task_id
        try:
            yield
        finally:
            if prev is None:
                os.environ.pop("HERMES_KANBAN_TASK", None)
            else:
                os.environ["HERMES_KANBAN_TASK"] = prev
    return _ctx
