# tests/integration/test_register_surfaces.py
"""Task 22: register(ctx) wires every surface (tools, hooks, CLI, slash, skills).

Uses a RECORDING ctx that captures registration names without touching any
process-global registry/hook singleton, so the suite stays leak-free.
"""
import json

import pytest

from hermes_workflow import tools

pytestmark = pytest.mark.integration


@pytest.fixture
def recording_ctx():
    class _Rec:
        def __init__(self):
            self.tools = set()
            self.hooks = set()
            self.cli = set()
            self.slash = set()
            self.skills = set()

            class _Log:
                def info(self, *a, **k):
                    pass

            self.log = _Log()

        def register_tool(self, *, name, toolset, schema, handler, **kw):
            self.tools.add(name)

        def register_hook(self, hook_name, callback):
            self.hooks.add(hook_name)

        def register_cli_command(self, name, **kw):
            self.cli.add(name)

        def register_command(self, name, *a, **kw):
            self.slash.add(name)

        def register_skill(self, name, path, **kw):
            self.skills.add(name)

    return _Rec()


def test_register_wires_tools_hooks_cli(recording_ctx):
    import hermes_workflow

    hermes_workflow.register(recording_ctx)

    assert {
        "workflow_start",
        "workflow_status",
        "workflow_validate",
        "workflow_reconcile",
        "workflow_approve",
        "workflow_abandon",
    } <= recording_ctx.tools
    assert {"post_tool_call", "pre_tool_call"} <= recording_ctx.hooks
    assert "workflow" in recording_ctx.cli
    assert "workflow" in recording_ctx.slash


def test_tool_handler_serializes_and_never_raises(fake_ctx):
    handler = tools.make_tool_handler(fake_ctx, tools.workflow_validate)

    # A well-formed (but trivial) call returns a JSON string parsing to a dict.
    out = handler({"template_text": "{}"})
    assert isinstance(out, str)
    assert isinstance(json.loads(out), dict)

    # A bad arg shape must NOT raise — it becomes a JSON {"error": ...} envelope.
    bad = handler({"unexpected": 1})
    assert isinstance(bad, str)
    parsed = json.loads(bad)
    assert "error" in parsed


def test_slash_dispatch_validate(fake_ctx, tmp_path):
    tpl = tmp_path / "demo.yaml"
    tpl.write_text(
        "name: x\n"
        "version: 0.1.0\n"
        "roles: {r: {lane: profile}}\n"
        "stages:\n"
        "  - {id: a, role: r}\n"
    )

    r = tools.slash_dispatch(fake_ctx, f"validate --template {tpl}")
    assert json.loads(r) == {"ok": True}

    usage = tools.slash_dispatch(fake_ctx, "bogus")
    assert usage.startswith("usage")
