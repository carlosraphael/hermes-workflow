# tests/integration/test_register_surfaces.py
"""Task 22: register(ctx) wires every surface (tools, hooks, CLI, slash, skills).

Uses a RECORDING ctx that captures registration names without touching any
process-global registry/hook singleton, so the suite stays leak-free.
"""
import argparse
import json

import pytest

from hermes_workflow import tools

pytestmark = pytest.mark.integration

# Inlined verbatim from test_workflow_start.py's DEMO_TPL_INLINE (conftest isn't importable).
DEMO_TPL_INLINE = """
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


def _parse(argv):
    p = argparse.ArgumentParser(prog="workflow", add_help=False)
    tools.cli_setup(p)
    return p.parse_args(argv)


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


def test_registration_and_cli_derived_from_single_command_source(recording_ctx):
    # Issue #15: the registered tool set AND the CLI subparser set are both
    # derived from the single COMMANDS source — no hand-maintained second list.
    # `==` (not `<=`) asserts there is no extra surface beyond COMMANDS.
    import hermes_workflow

    hermes_workflow.register(recording_ctx)

    assert recording_ctx.tools == {cmd.name for cmd in tools.COMMANDS}

    parser = argparse.ArgumentParser(prog="workflow", add_help=False)
    tools.cli_setup(parser)
    sub = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    assert set(sub.choices) == {cmd.cli_name for cmd in tools.COMMANDS}


def test_register_discovers_bundled_skills(recording_ctx):
    import hermes_workflow

    hermes_workflow.register(recording_ctx)

    assert {"workflow-author", "workflow-orchestrator"} <= recording_ctx.skills


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


# ---------------------------------------------------------------------------
# Flat-error contract (audit §6 #10 + D3-03/01/02): tool/CLI/slash surfaces must
# return a flat {"error": ...} envelope, never leak a raw Python traceback.
# ---------------------------------------------------------------------------


def test_cli_dispatch_bad_template_returns_flat_error(fake_ctx, tmp_path):
    # A nonexistent --template makes _read_template raise FileNotFoundError;
    # cli_dispatch must catch it and return a flat {"error": ...}, not raise.
    ns = _parse(["start", "--template", str(tmp_path / "nope.yaml"), "--bindings", "{}"])

    r = tools.cli_dispatch(fake_ctx, ns)

    assert isinstance(r, dict)
    assert "error" in r
    assert "start" in r["error"]


def test_slash_dispatch_bad_template_returns_flat_error(fake_ctx, tmp_path):
    # The slash surface must likewise turn a bad --template path into flat JSON.
    r = tools.slash_dispatch(fake_ctx, f"start --template {tmp_path / 'nope.yaml'} --bindings '{{}}'")

    assert isinstance(r, str)
    parsed = json.loads(r)
    assert isinstance(parsed, dict)
    assert "error" in parsed


def test_slash_dispatch_unexpected_exception_returns_flat_error(
    fake_ctx, tmp_board, tmp_path, stub_preflight_ok, monkeypatch
):
    # D3-02: a MaterializeError raised during seeding is NOT an OSError/JSONDecodeError,
    # so the pre-fix narrow except tuple let it bubble as a raw traceback. The broadened
    # `except Exception` must instead surface it as flat JSON. (Pre-fix, workflow_start's
    # own unguarded materialize call raised here too; both fixes converge on flat error.)
    from hermes_workflow.materialize import MaterializeError

    monkeypatch.setattr(
        "hermes_workflow.tools.materialize",
        lambda *a, **k: (_ for _ in ()).throw(MaterializeError("boom")),
    )
    tpl = tmp_path / "demo.yaml"
    tpl.write_text(DEMO_TPL_INLINE)
    bindings = '{"scout": "designer", "fixer": "coder", "reporter": "writer"}'

    r = tools.slash_dispatch(
        fake_ctx,
        f"start --template {tpl} --params '{{\"repo\": \"/r\"}}' "
        f"--bindings '{bindings}' --board {tmp_board.name}",
    )

    assert isinstance(r, str)
    parsed = json.loads(r)
    assert isinstance(parsed, dict)
    assert "error" in parsed


def test_slash_dispatch_broadened_except_catches_unexpected_exception(fake_ctx, monkeypatch):
    # D3-02 teeth: an exception type OUTSIDE the old narrow (OSError, json.JSONDecodeError)
    # tuple raised by _dispatch_ns must still be caught and surfaced as flat JSON, not
    # propagate as a raw traceback. Monkeypatch _dispatch_ns so the raise happens at the
    # exact layer slash_dispatch's except guards.
    from hermes_workflow import tools

    def _boom(ctx, ns):
        raise RuntimeError("simulated unexpected dispatch failure")

    monkeypatch.setattr(tools, "_dispatch_ns", _boom)
    # 'validate --template X' parses cleanly, so parse_args succeeds and _dispatch_ns is reached.
    r = tools.slash_dispatch(fake_ctx, "validate --template whatever.yaml")
    assert isinstance(r, str)
    parsed = json.loads(r)
    assert isinstance(parsed, dict)
    assert "error" in parsed
    assert "validate" in parsed["error"]   # message includes the subcommand


def test_workflow_start_flat_error_on_materialize_failure(
    fake_ctx, tmp_board, stub_preflight_ok, monkeypatch
):
    # D3-03: a worktree-provision failure inside materialize (post-pre-flight
    # seeding) must return a flat {"error": ...}, not propagate a raw traceback.
    from hermes_workflow.materialize import MaterializeError

    monkeypatch.setattr(
        "hermes_workflow.tools.materialize",
        lambda *a, **k: (_ for _ in ()).throw(MaterializeError("boom")),
    )

    r = tools.workflow_start(
        fake_ctx,
        template_text=DEMO_TPL_INLINE,
        params={"repo": "/r"},
        bindings={"scout": "designer", "fixer": "coder", "reporter": "writer"},
        board=tmp_board.name,
    )

    assert isinstance(r, dict)
    assert "error" in r
