# tests/integration/test_spike_veto.py
"""Spike 1 — pre_tool_call veto + fail-open contract (real Hermes source).

Confirms against Hermes v0.15.1 @ c47b9d12 that:
  1. A pre_tool_call hook returning {"action":"block","message":str} causes
     get_pre_tool_call_block_message() to surface that message. (Per source read
     — NOT asserted here — model_tools then returns {"error": message} and never
     dispatches the real tool; see SPIKES.md, tagged [source].)
  2. A hook that RAISES contributes no result -> no block (fail-open). Our
     future gate must therefore never rely on raising.

Registration uses the singleton's hook list via the `register_pre_hook`
fixture (conftest.py), which is exactly what PluginContext.register_hook does
internally (plugins.py:949). The plan's `plugins.register_hook(...)` does not
exist as a module-level function — register_hook is a PluginContext method.
"""
import pytest

pytestmark = pytest.mark.integration


def test_pre_tool_call_block_prevents_completion(hermes_root, register_pre_hook):
    from hermes_cli import plugins

    blocked = {"action": "block", "message": "veto: precondition failed"}
    # Block only kanban_complete; leave every other tool untouched.
    register_pre_hook(
        lambda **kw: blocked if kw.get("tool_name") == "kanban_complete" else None
    )

    msg = plugins.get_pre_tool_call_block_message(
        tool_name="kanban_complete", args={}, task_id="t_x"
    )
    assert msg and "veto" in msg

    # A different tool must NOT be blocked by this hook.
    assert (
        plugins.get_pre_tool_call_block_message(
            tool_name="kanban_show", args={}, task_id="t_x"
        )
        is None
    )


def test_pre_tool_call_exception_fails_open(hermes_root, register_pre_hook):
    from hermes_cli import plugins

    def boom(**kw):
        raise RuntimeError("hook bug")

    register_pre_hook(boom)

    msg = plugins.get_pre_tool_call_block_message(
        tool_name="kanban_complete", args={}, task_id="t_x"
    )
    # A raising hook must NOT block -> our gate must never rely on raising.
    assert msg is None
