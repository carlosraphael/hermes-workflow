# Spike findings (confirmed Hermes v0.15.1 @ c47b9d12 signatures/behaviors)
Each spike records the exact signature/behavior the coupled tasks depend on.

## Spike 1 — pre_tool_call veto blocks `kanban_complete`; a raising hook fails OPEN

Confirmed against real source (Hermes v0.15.1 @ c47b9d12). Test:
`tests/integration/test_spike_veto.py`.

**Coverage legend** — each finding below is tagged:
- **[test]** = directly asserted by `test_spike_veto.py`.
- **[source]** = confirmed by reading the pinned Hermes source, but NOT exercised
  by a test (don't assume regression coverage for these — re-verify if Hermes moves).

### Registration mechanism
- There is NO module-level `plugins.register_hook(...)`. The plan's example is
  WRONG. `register_hook(hook_name, callback)` is a method of **`PluginContext`**
  (`hermes_cli/plugins.py:935-950`); `list_plugins` is a method of `PluginManager`.
- Hooks are stored in a process-global singleton:
  `get_plugin_manager()._hooks` — a `dict[str, list[callable]]`
  (`get_plugin_manager()` at `plugins.py:1625`).
- We register by appending directly to that list (exactly what
  `PluginContext.register_hook` does internally at `plugins.py:949`:
  `self._manager._hooks.setdefault(hook_name, []).append(callback)`):
  ```python
  plugins.get_plugin_manager()._hooks.setdefault("pre_tool_call", []).append(cb)
  ```
  This is encapsulated in the `register_pre_hook` fixture (`tests/conftest.py`),
  which removes EXACTLY the callbacks it appended in `finally` teardown — no
  whole-dict reset — to keep the global singleton uncorrupted across tests.

### Block-check signature + return contract (`plugins.py:1666-1707`) **[test + source]**
The return value of `get_pre_tool_call_block_message` is what the two tests assert
directly (block message surfaces for `kanban_complete`; `None` for a non-targeted
tool and for a raising hook). The signature/internals below are **[source]**.

```python
get_pre_tool_call_block_message(
    tool_name: str,
    args: Optional[Dict[str, Any]],
    task_id: str = "",
    session_id: str = "",
    tool_call_id: str = "",
) -> Optional[str]
```
- Internally calls `invoke_hook("pre_tool_call", tool_name=, args=, task_id=,
  session_id=, tool_call_id=)`. (`args` coerced to `{}` if not a dict.)
- Iterates results; returns the FIRST result that is a `dict` with
  `result.get("action") == "block"` AND a non-empty `str` `result.get("message")`.
  Otherwise returns `None`. Non-dict / wrong-action / empty-message results are
  silently ignored (observer-only hooks are unaffected).
- Also enforces a thread-local tool whitelist before invoking hooks
  (`plugins.py:1684-1687`), unrelated to our gate.

### Block-directive shape (the dict a hook returns to veto)
```python
{"action": "block", "message": "<non-empty reason string>"}
```

### model_tools behavior (`model_tools.py:914-943`, file is top-level, not under hermes_cli/) **[source]**
(NOTE: this no-dispatch path is confirmed by source read, NOT exercised by a test —
the tests only check `get_pre_tool_call_block_message`'s return, not `model_tools` dispatch.)
- When `not skip_pre_tool_call_hook` and `get_pre_tool_call_block_message(...)`
  returns a non-`None` message, the tool returns
  `json.dumps({"error": block_message}, ensure_ascii=False)` and `registry.dispatch`
  (the real `kanban_complete`) is **NOT** called. The block message surfaces to
  the caller as `{"error": ...}`.

### Confirmed fail-open rule (CRITICAL for our gate design) **[test for layer 1, source for layer 2]**
A raising hook ⇒ NO block, at TWO layers (layer 1 is asserted by the fail-open test
via the `None` return; layer 2 is source-confirmed only):
1. `PluginManager.invoke_hook` (`plugins.py:1534-1568`) wraps each callback in its
   own `try/except`, logs a warning, and continues. A raising callback contributes
   no result, so `get_pre_tool_call_block_message` sees nothing to block on → `None`.
2. `model_tools.py:939-940`: even if `get_pre_tool_call_block_message` itself raised,
   the outer `try/except` leaves `block_message=None` → dispatch proceeds.

**Implication for downstream tasks:** our gate MUST veto by RETURNING
`{"action":"block","message":...}`. It must NEVER rely on raising — a raised
exception fails open (no block).
