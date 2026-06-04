# tests/integration/test_workflow_start.py
"""Integration tests for the ``workflow_start`` orchestrator tool.

Covers the orchestrator guard, the seed-root-and-prefix happy path (probe
stubbed), fail-fast-on-unloadable-profile with zero cards created, and the
REAL subprocess probe end-to-end (PYTHONPATH propagation + per-profile env).
"""
import pytest

pytestmark = pytest.mark.integration

# Inlined verbatim from tests/conftest.py's DEMO_TPL (conftest isn't importable).
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

_BINDINGS = {"scout": "designer", "fixer": "coder", "reporter": "writer"}


def test_start_refuses_in_worker_context(fake_ctx, tmp_board, monkeypatch):
    from hermes_workflow.tools import workflow_start

    monkeypatch.setenv("HERMES_KANBAN_TASK", "t_worker")
    r = workflow_start(
        fake_ctx,
        template_text=DEMO_TPL_INLINE,
        params={"repo": "/r"},
        bindings=_BINDINGS,
    )
    assert r["error"]
    assert "orchestrator" in r["error"]


def test_start_seeds_root_and_prefix(fake_ctx, tmp_board, monkeypatch):
    from hermes_workflow.tools import workflow_start
    from hermes_workflow.runview import RunView

    monkeypatch.delenv("HERMES_KANBAN_TASK", raising=False)
    # Patch the name in the tools namespace (tools.py does `from ... import probe_profiles`).
    monkeypatch.setattr(
        "hermes_workflow.tools.probe_profiles",
        lambda profiles, **kw: {p: {"ok": True, "error": None} for p in profiles},
    )

    r = workflow_start(
        fake_ctx,
        template_text=DEMO_TPL_INLINE,
        params={"repo": "/r"},
        bindings=_BINDINGS,
        board=tmp_board.name,
    )
    assert "error" not in r, r
    assert r["root_id"]
    assert r["board"] == tmp_board.name

    rv = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=r["root_id"])
    assert rv.card_id_for(("scan", 0, 0))        # prefix created + reachable from root
    assert rv.card_id_for(("fix", 0, 0)) is None  # fan-out not yet materialized


def test_start_fails_fast_on_unloadable_profile(fake_ctx, tmp_board, monkeypatch):
    from hermes_workflow.tools import workflow_start
    from hermes_workflow.board import HostBoard

    monkeypatch.delenv("HERMES_KANBAN_TASK", raising=False)
    monkeypatch.setattr(
        "hermes_workflow.tools.probe_profiles",
        lambda profiles, **kw: {
            "designer": {"ok": True, "error": None},
            "coder": {"ok": False, "error": "not enabled in config"},
            "writer": {"ok": True, "error": None},
        },
    )

    r = workflow_start(
        fake_ctx,
        template_text=DEMO_TPL_INLINE,
        params={"repo": "/r"},
        bindings=_BINDINGS,
        board=tmp_board.name,
    )
    assert r["error"]
    assert "pre-flight" in r["error"] or "zero cards" in r["error"]
    assert "coder" in r["profiles"]
    assert "plugins enable" in r["remediation"]["coder"]

    # ZERO cards created (no root, no prefix).
    host = HostBoard(tmp_board.kb, tmp_board.conn, tmp_board.name)
    assert host.list() == []


def test_probe_profiles_detects_disabled_plugin(hermes_root, tmp_board):
    # REAL subprocess probe: under tmp_board, HERMES_HOME=tmp; the spawned probe
    # discovers `hermes-workflow` via its entrypoint but it's not enabled in
    # config -> ok=False. Exercises subprocess + PYTHONPATH propagation end-to-end.
    from hermes_workflow.preflight import probe_profiles

    result = probe_profiles({"default"})
    assert result["default"]["ok"] is False
    assert isinstance(result["default"]["error"], str)
    assert result["default"]["error"]
