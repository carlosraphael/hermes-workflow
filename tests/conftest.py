# tests/conftest.py
import os, sys, pathlib, pytest

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
