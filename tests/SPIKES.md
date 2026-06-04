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

## Spike 2 — per-profile load-status probe (`enabled` != merely configured)

Confirmed against real source (Hermes v0.15.1 @ c47b9d12). Test:
`tests/integration/test_spike_preflight.py`.

The future `workflow_start` preflight probe needs to know, per profile, whether
a plugin actually **loaded** (`enabled`) and, if not, **why** (`error`). That
truth is process-local and home-scoped — read it in-process under the target
`HERMES_HOME`.

### How to read load status (the CONFIRMED API) **[test + source]**
- `list_plugins()` is a **method of `PluginManager`**, NOT a module-level
  function. The plan's `plugins.list_plugins()` is WRONG. Call it via the
  singleton: `plugins.get_plugin_manager().list_plugins()` (`plugins.py:1574`).
- It returns **`List[Dict[str, Any]]`** — a list of DICTS, NOT objects with
  `.name/.enabled/.error`. (`plugins.py:1574-1593`.) **[test]** asserts
  `isinstance(lst, list)` and, for each entry, `isinstance(entry, dict)` with
  keys `name`/`enabled`/`error` (`enabled` a `bool`, `error` `Optional[str]`).
- Exact key set (all 11 keys, observed in a real run under a tmp home):
  `['commands', 'description', 'enabled', 'error', 'hooks', 'key', 'kind',
  'name', 'source', 'tools', 'version']`.
- Read `(enabled, error)` by name via a dict keyed on `"name"`:
  ```python
  by_name = {e["name"]: e for e in lst}
  entry = by_name["hermes-workflow"]      # KeyError if not discovered
  enabled, error = entry["enabled"], entry["error"]
  ```

### Observed shape from a real run (HERMES_HOME=tmp, project plugins on) **[test run]**
- `type(lst).__name__ == 'list'`, **35 entries**, each a `dict`. 28 enabled, 7
  carrying a non-`None` `error`.
- Sample ENABLED entry (`error is None`):
  ```json
  {"name": "nous", "key": "dashboard_auth/nous", "kind": "backend",
   "version": "1.0.0", "description": "Dashboard auth provider …",
   "source": "bundled", "enabled": true, "tools": 0, "hooks": 0,
   "commands": 0, "error": null}
  ```
- Sample DISABLED entry — note this is **our own plugin**, discovered via the
  `entrypoint` source (the `hermes_agent.plugins` entry point in
  `pyproject.toml`), `enabled: false`, with a human-readable `error` reason:
  ```json
  {"name": "hermes-workflow", "key": "hermes-workflow", "kind": "standalone",
   "version": "", "description": "", "source": "entrypoint",
   "enabled": false, "tools": 0, "hooks": 0, "commands": 0,
   "error": "not enabled in config (run `hermes plugins enable hermes-workflow` to activate)"}
  ```
  So `error` is exactly the preflight signal: present + descriptive when a
  plugin is discovered but not loaded.

### Underlying truth **[source]**
`list_plugins()` is the public projection of `LoadedPlugin.enabled` /
`LoadedPlugin.error` (`plugins.py:278-279`); internally
`get_plugin_manager()._plugins` is a `dict[key, LoadedPlugin]`
(iterated, `sorted` by key, at `plugins.py:1577`).

### Env vars the probe sets **[test + source]**
- `HERMES_HOME` → the profile root. Plugin load runs under this home (user
  plugins scanned at `<HERMES_HOME>/plugins`, `plugins.py:1078`), so load
  status is per-profile and only visible in-process under that home.
- `HERMES_ENABLE_PROJECT_PLUGINS=1` → gates scanning of `./.hermes/plugins/`
  (CWD-relative project plugins) during discovery (`plugins.py:1085-1090`, via
  `_env_enabled` → `env_var_enabled`). Set explicitly so the scan is
  deterministic.
- The test sets both via pytest `monkeypatch.setenv`, so they auto-restore on
  teardown (no `os.environ` mutation left behind).

### CRITICAL caching caveat — must `force=True` **[source + test]**
`discover_plugins(force=False)` → `discover_and_load(force=False)` is
**idempotent**: `if self._discovered and not force: return` (`plugins.py:1034`).
The PluginManager singleton is **process-global**, so once any earlier test in
the same process has discovered, a plain `discover_plugins()` is a **no-op** and
will NOT rescan under your new `HERMES_HOME`. The probe MUST call
`discover_plugins(force=True)` (or `discover_and_load(force=True)`) to actually
rescan. `force=True` first clears cached state, including `self._hooks.clear()`
(`plugins.py:1038`) — harmless for this suite because Spike 1's
`register_pre_hook` fixture removes its own hooks in teardown rather than
relying on the dict surviving.

**Singleton residue note:** force-discovering under a tmp home leaves the
process-global manager pointed at that (now-deleted) tmp home's plugin list. No
other Phase-0 test depends on the manager's plugin LIST, so this is low-risk;
the full suite (`pytest -q`) stays green after this test runs. The real
preflight probe per §9 of the design should run in a **fresh spawned process**
per profile (cleanest isolation) rather than reusing the in-process singleton.

### Why an in-process / spawned probe is required — `hermes plugins list` is config-only **[source]**
`hermes plugins list` (`plugins_cmd.py:806 cmd_list`) does NOT reflect runtime
load status. It calls `_discover_all_plugins()` (a filesystem manifest scan) and
labels each entry with `_plugin_status()` (`plugins_cmd.py:784-790`), which only
checks the config `enabled`/`disabled` SETS — it never reads `LoadedPlugin.enabled`
and never attempts to load a plugin. So a plugin can be "enabled" in config yet
fail to load (import error, etc.), and the CLI would still show "enabled". To
learn the actual load result (`enabled` + `error`), you must read
`PluginManager.list_plugins()` in-process under the target home (or in a spawned
process). That is precisely what this spike pins down.
