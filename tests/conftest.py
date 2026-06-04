# tests/conftest.py
import contextlib, os, subprocess, sys, pathlib, pytest

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
# The Board class lives in tests/integration/board.py. We import it as the
# top-level module ``board`` (the integration dir is added to sys.path below)
# rather than via the dotted ``tests.integration.board``: the hermes_root
# fixture puts hermes-agent on sys.path, which ships its own regular ``tests``
# package (tests/__init__.py) that shadows our namespace ``tests`` and makes the
# dotted import unresolvable. CRITICAL: get_task(...) returns a Task OBJECT
# (attribute access .status, NOT ["status"]); create_task is keyword-only after
# conn; complete_task is keyword-only after task_id.
# ---------------------------------------------------------------------------

_INTEGRATION_DIR = str(pathlib.Path(__file__).parent / "integration")
if _INTEGRATION_DIR not in sys.path:
    sys.path.insert(0, _INTEGRATION_DIR)


def _init_git_repo(base_dir, name="wf_repo"):
    """Create a genuinely-initialized git repo with one commit.

    Used by the ``wf_repo`` fixture to back ``worktree:`` workspaces (materialize
    runs a real ``git worktree add``).
    """
    repo = base_dir / name
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    (repo / "f").write_text("x")
    subprocess.run(["git", "add", "f"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=a@b.c", "-c", "user.name=a", "commit", "-m", "init"],
        cwd=repo, check=True, capture_output=True,
    )
    return repo


@pytest.fixture
def tmp_board(hermes_root, tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_KANBAN_BOARD", "test")
    from hermes_cli import kanban_db as kb
    from board import Board

    conn = kb.connect(board="test")
    board = Board(kb, conn, "test")
    try:
        yield board
    finally:
        conn.close()


@pytest.fixture
def wf_repo(tmp_board, tmp_path):
    """A real git repo backing ``worktree:`` workspaces, attached as ``tmp_board.repo``.

    Opt-in (only runs that actually provision worktrees need it) so the ~47
    integration tests that never touch ``tmp_board.repo`` don't pay for a git
    init. Uses the ``wf_repo`` subdir, distinct from the ``tmp_path/"repo"`` that
    some test-local helpers create, to avoid a mkdir collision.
    """
    tmp_board.repo = _init_git_repo(tmp_path)
    return tmp_board.repo


@pytest.fixture
def stub_preflight_ok(monkeypatch):
    """Force the per-profile pre-flight probe green so workflow_start seeds cards.

    workflow_start otherwise spawns a real subprocess probe per bound profile
    (designer/coder/writer aren't real profiles -> probe fails -> zero cards).
    Also clears HERMES_KANBAN_TASK so the orchestrator-context guard passes.
    """
    monkeypatch.delenv("HERMES_KANBAN_TASK", raising=False)
    monkeypatch.setattr(
        "hermes_workflow.tools.probe_profiles",
        lambda profiles, **kw: {p: {"ok": True, "error": None} for p in profiles},
    )


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


# ---------------------------------------------------------------------------
# seed_run — a completed-root blackboard + a sentinel-stamped ``scan`` stage
# card. Reusable across Tasks 14, 15 & 17. Returns a Seeded(root_id, scan_id).
# ---------------------------------------------------------------------------

DEMO_TPL = """
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
DEMO_PARAMS = {"repo": "/r"}
DEMO_BINDINGS = {"scout": "designer", "fixer": "coder", "reporter": "writer"}


@pytest.fixture
def seed_run(tmp_board):
    from collections import namedtuple
    from hermes_workflow.engine.provenance import build_root_body, embed_sentinel, Sentinel
    from hermes_workflow.version import PLUGIN_VERSION, SCHEMA_VERSION, SENTINEL_ROOT_ASSIGNEE
    Seeded = namedtuple("Seeded", "root_id scan_id")

    def _seed(template_yaml=DEMO_TPL, params=DEMO_PARAMS, bindings=DEMO_BINDINGS,
              schema_version=SCHEMA_VERSION):
        root_body = build_root_body(template_yaml, params, bindings, PLUGIN_VERSION, schema_version)
        root_id = tmp_board.create(title="wf root", assignee=SENTINEL_ROOT_ASSIGNEE, body=root_body)
        tmp_board.complete(root_id)  # root is a completed blackboard
        scan_sent = Sentinel(root_id, "scan", 0, 0, "demo", "0.1.0", PLUGIN_VERSION, schema_version)
        scan_body = embed_sentinel("scan body", scan_sent)
        scan_id = tmp_board.create(title="scan /r", parents=[root_id], assignee="designer",
                                   workspace_kind="dir", workspace_path=params["repo"], body=scan_body)
        return Seeded(root_id, scan_id)

    return _seed


@pytest.fixture
def started_run(fake_ctx, tmp_board, wf_repo, stub_preflight_ok):
    """Return a ``started_run()`` callable: starts the shipped fix-flaky-tests
    template against the real ``tmp_board.repo`` and returns the run root id.

    Depends on ``wf_repo`` (real git repo for the ``fix`` worktree stage) and
    ``stub_preflight_ok`` (the per-profile probe + orchestrator-context guard).
    """
    from hermes_workflow.tools import workflow_start

    def _start():
        tpl = (pathlib.Path(__file__).resolve().parents[1] / "examples"
               / "fix-flaky-tests.workflow.yaml").read_text()
        r = workflow_start(
            fake_ctx, template_text=tpl, params={"repo": str(tmp_board.repo)},
            bindings={"scout": "designer", "fixer": "coder", "reporter": "writer"},
            board=tmp_board.name,
        )
        return r["root_id"]

    return _start


@pytest.fixture
def partial_fanout(fake_ctx, tmp_board, started_run):
    """Return a ``partial_fanout()`` callable producing the reconcile fixture state:

    a fanned-out run where the ``fix`` ("fix",1,0) instance is MISSING (unlinked +
    archived) and ("fix",0,0) has a DUPLICATE sharing its sentinel identity — the
    original is ``done`` (a real run = the progress winner), the duplicate is empty.
    Returns a ``Partial(root, winner, dup)`` namedtuple: the run root id, the
    done-winner fix0 id, and the empty duplicate id. ``workflow_reconcile`` should
    recreate the missing instance and the progress-aware dedup should archive the
    empty duplicate.
    """
    from collections import namedtuple
    from hermes_workflow.runview import RunView
    from hermes_workflow.materialize import materialize
    from hermes_workflow.board import WorkerBoard, HostBoard
    Partial = namedtuple("Partial", "root winner dup")

    def _make():
        root = started_run()
        # advance scan -> materialize the fix fan-out (fix0, fix1) + the joins
        rv = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=root)
        scan = rv.card_id_for(("scan", 0, 0))
        tmp_board.complete(scan, metadata={"flaky": [
            {"test_id": "T1", "file": "a.py"}, {"test_id": "T2", "file": "b.py"}]})
        rv2 = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=root)
        materialize(fake_ctx, board=tmp_board.name, root_id=root, runview=rv2)
        rv3 = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=root)
        fix0 = rv3.card_id_for(("fix", 0, 0))
        fix1 = rv3.card_id_for(("fix", 1, 0))

        wb = WorkerBoard(fake_ctx, board=tmp_board.name)
        # fix0 becomes the 'done' winner (a completed run carries progress)
        tmp_board.complete(fix0, metadata={"branch": "wf/done"})
        # DUPLICATE: a second live card sharing fix0's sentinel identity (create-race).
        # Reusing fix0's exact body re-embeds the same sentinel -> Identity ("fix",0,0).
        dup_body = wb.show(fix0)["body"]
        dup = tmp_board.create(title="fix dup", parents=[scan], assignee="coder", body=dup_body)
        # DROP ("fix",1,0): fully unlink + archive so the link-walk can't reach it
        # and reconcile must recreate it.
        card1 = wb.show(fix1)
        hb = HostBoard(tmp_board.kb, tmp_board.conn, tmp_board.name)
        for p in card1["parents"]:
            hb.unlink(p, fix1)
        for c in card1["children"]:
            hb.unlink(fix1, c)
        hb.archive(fix1)
        return Partial(root=root, winner=fix0, dup=dup)

    return _make


@pytest.fixture
def fake_ctx(hermes_root, tmp_board):
    """A tiny stand-in for a Hermes PluginContext exposing only dispatch_tool.

    Mirrors the tail of the production PluginContext.dispatch_tool
    (hermes_cli/plugins.py): it routes straight to the registry singleton.
    Importing ``tools.kanban_tools`` triggers the module-level
    registry.register(...) calls for kanban_create/link/comment/show, so the
    handlers exist before we dispatch. We skip the parent_agent wiring the real
    context does — kanban handlers ignore that kwarg (no LLM needed).

    Depends on hermes_root (puts hermes-agent on sys.path) and tmp_board (sets
    HERMES_HOME/HERMES_KANBAN_BOARD and opens the board). Each handler opens its
    own connection to the same board file, which is fine: separate connections
    to one sqlite board read each other's writes (proven by the version-gate
    spike).
    """
    class _FakeCtx:
        def dispatch_tool(self, tool_name, args, **kwargs):
            import tools.kanban_tools  # noqa: F401 — ensure handler registration
            from tools.registry import registry
            return registry.dispatch(tool_name, args, **kwargs)

    return _FakeCtx()


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
