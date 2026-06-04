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
