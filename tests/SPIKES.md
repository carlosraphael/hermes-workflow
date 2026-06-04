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

## Spike 3 — atomic create + fan-in promotion + late-link demotion

Confirmed against real source (Hermes v0.15.1 @ c47b9d12). Test:
`tests/integration/test_spike_fanout.py`. Board fixtures (`tmp_board`,
`mk_card`, `complete_card`) live in `tests/conftest.py` as an inline `_Board`
wrapper — Phase 1 Task 6 will extract these into `tests/integration/board.py`.

**Coverage legend** (same convention as Spikes 1–2):
- **[test]** = directly asserted by `test_spike_fanout.py`.
- **[source]** = confirmed by reading the pinned Hermes source, NOT exercised
  by a test (re-verify if Hermes moves).

### The three confirmed board behaviors **[test]**
All three reproduced exactly as pre-confirmed by the controller's live run; no
spike-stop:
1. `create_task(parents=[a, b])` with a, b incomplete → join lands `todo`
   ATOMICALLY at create (status computed from CURRENT parent statuses).
2. Complete only `a` → join still `todo` (gated on b). Complete `b` too → join
   `ready` (promoted exactly when the LAST parent completes).
3. `a` done; `create_task(parents=[a])` → `ready`; create incomplete `c`
   (no parents → lands `ready`, not `done`); `link_tasks(parent_id=c,
   child_id=join)` → join DEMOTED back to `todo`. This is what makes reconcile's
   late re-link safe.
- Sanity: a no-parent `create_task` lands `ready` (`create_task` docstring +
  :2156); used by the test's plain `mk_card(title=...)` children.

### CONFIRMED kb signatures (carry these to Task 6 / board.py)

`create_task` — **keyword-only after `conn`** (note the `*` at
`kanban_db.py:1997`). Returns the new task id (`str`):
```python
create_task(
    conn: sqlite3.Connection, *,
    title: str, body=None, assignee=None, created_by=None,
    workspace_kind="scratch", workspace_path=None, branch_name=None,
    tenant=None, priority=0, parents: Iterable[str]=(), triage=False,
    idempotency_key=None, max_runtime_seconds=None, skills=None,
    max_retries=None, goal_mode=False, goal_max_turns=None,
    initial_status="running", session_id=None, board=None,
) -> str
```
- Atomic status-from-parents block (`:2147-2168`): `initial_status="blocked"` →
  `blocked`; `triage=True` → `triage`; else default `ready`, but if `parents`
  and ANY parent row `status != "done"` → `todo`. So the rule is
  **"no parents → ready; some parents not done → todo; all parents done →
  ready"**, computed atomically inside the create write-txn from CURRENT parent
  statuses. **[source]**
- `initial_status` DEFAULT is `"running"`, but it is OVERRIDDEN by the
  status-from-parents block above for the normal (non-blocked, non-triage)
  path — a no-parent create still lands `ready`, NOT `running`. **[source]**
- Parent existence is validated by `_find_missing_parents` (`:2235-2245`);
  unknown parents raise `ValueError("unknown parent task(s): …")`. **[source]**

`complete_task` — **keyword-only after `task_id`** (`*` at `:3508`). Returns
`bool`:
```python
complete_task(
    conn, task_id, *,
    result=None, summary=None, metadata=None,
    created_cards=None, expected_run_id=None,
) -> bool
```
- Param names confirmed `summary` / `metadata` (NOT a positional `summary`).
  The `_Board.complete(tid, summary=..., metadata=...)` kwargs match exactly —
  no correction needed. **[source]**
- Writes `done` gated on the task's OWN id AND `status IN ('running','ready',
  'blocked')` (`:3576-3605`); returns `False` if `rowcount != 1` (e.g. already
  done / unknown). A no-parent card sits in `ready`, which is accepted. **[source]**
- After committing the completion it calls `recompute_ready(conn)` (`:3681`,
  separate txn so children see `done`) — THIS is what promotes the join
  `todo`→`ready` when the last parent completes. **[source, observed via test]**

`recompute_ready` — promotes only, never demotes:
```python
recompute_ready(conn, failure_limit: int = None) -> int   # returns # promoted
```
- Scans tasks in `('todo','blocked')` and promotes to `ready` ONLY when ALL
  parents ∈ `{done, archived}` (`:2858-2908`). It updates with a guarded
  `WHERE … AND status = 'todo'` / `'blocked'`, so it NEVER demotes a non-todo
  card. Demotion is a DIFFERENT function (`link_tasks`, below). **[source]**

`link_tasks` — adds a parent→child edge AND performs the ready→todo demotion:
```python
link_tasks(conn, parent_id: str, child_id: str) -> None
```
- After inserting the edge, if the new parent's `status != "done"` it runs
  `UPDATE tasks SET status='todo' WHERE id=child_id AND status='ready'`
  (`:2371-2379`) — so linking an INCOMPLETE parent demotes a `ready` child to
  `todo`. (Note positional `parent_id, child_id`; the `_Board.link` helper
  passes them as kwargs `parent_id=`/`child_id=` which is fine.) Also rejects
  self-links and cycles with `ValueError`. **[source, demotion observed via test]**

`get_task` — returns a `Task` OBJECT or `None`:
```python
get_task(conn, task_id: str) -> Optional[Task]
```
- **CRITICAL correction vs the plan's Task 6 snippet:** `Task` is a dataclass
  (`kanban_db.py:676`) with a `.status: str` ATTRIBUTE. Use ATTRIBUTE access
  `get_task(conn, tid).status` — the plan's `["status"]` (dict subscript) is
  WRONG and would raise `TypeError`. `_Board.status` uses attribute access.
  Returns `None` if the row is absent. **[source + test]**

`connect` — `connect(db_path=None, *, board=None) -> sqlite3.Connection`
(`:1358`). `connect(board="test")` resolves the board DB under `HERMES_HOME`
and auto-runs `init_db` on first open, so the `tmp_board` fixture needs no
separate init step. **[source + test]**

`archive_task` — `archive_task(conn, task_id: str) -> bool` (`:4486`). Wired on
`_Board.archive` for completeness; NOT exercised by this spike. **[source]**

### Fixture / isolation notes
- `tmp_board` sets `HERMES_HOME=<tmp_path>` and `HERMES_KANBAN_BOARD="test"`
  via `monkeypatch.setenv` (auto-restored; no `os.environ` mutation). Each test
  gets a fresh `tmp_path` → an isolated board file, so tests don't interfere.
- Sentinel assignees with a leading underscore (`_workflow_root` for children,
  `_workflow_gate` for joins) keep cards non-spawnable — fine for this
  no-dispatch kb-layer board test. They pass through `_canonical_assignee` →
  `normalize_profile_name` (`:1986-1992`) without rejection.

### Future fan-out hook surface (recorded for the post_tool_call hook) **[source]**
Not exercised by this spike's tests — the tests use the kb layer directly.

- `post_tool_call` hook invocation (`model_tools.py:993-1006`, top-level file):
  ```python
  invoke_hook("post_tool_call",
      tool_name=function_name, args=function_args, result=result,
      task_id=task_id or "", session_id=session_id or "",
      tool_call_id=tool_call_id or "", duration_ms=duration_ms)
  ```
  The return value is IGNORED and exceptions are SWALLOWED (logged at debug,
  `:1005-1006`). **Implications for the fan-out hook callback:**
  - It MUST accept `**kwargs` (host passes the 7 kwargs above; arg names:
    `tool_name`, `args`, `result`, `task_id`, `session_id`, `tool_call_id`,
    `duration_ms`).
  - The handoff is read from `args` (the tool's INPUT args, e.g.
    `args["metadata"]`), NOT from `result`.
  - It is observational/fail-open: a raise won't surface, a return won't change
    the result. Any board writes must be self-contained.

- `kanban_create` model-tool return shape (`tools/kanban_tools.py:_handle_create`
  `:723`, success path `:820-824`): returns `_ok(task_id=new_tid,
  status=new_task.status)`. `_ok(**fields)` (`:263-264`) is
  `json.dumps({"ok": True, **fields})`, so the return is a JSON STRING:
  `{"ok": true, "task_id": "t_…", "status": "ready"|"todo"|…}`. The design's
  claimed `{task_id, status}` is correct but wrapped in the `{"ok": true}`
  envelope. Errors return `tool_error(...)` (an `{"error": …}` JSON string).

- `PluginContext.dispatch_tool` (`hermes_cli/plugins.py:467-494`): signature
  `dispatch_tool(self, tool_name: str, args: dict, **kwargs) -> str`. Auto-wires
  `parent_agent` from `self._manager._cli_ref` when available, then returns
  `registry.dispatch(tool_name, args, **kwargs)` — a JSON STRING (same format as
  model tool calls). Matches the design's "JSON string" claim.

## Spike 4 — worker cross-task comment (version-gate "visible refuse" basis)

Confirmed against real source (Hermes v0.15.1 @ c47b9d12). Test:
`tests/integration/test_spike_version_gate.py`. Uses the new `as_worker`
fixture in `tests/conftest.py` (a context manager that pins
`HERMES_KANBAN_TASK` to a worker's own card and restores it on exit).

The §2 version gate, on a `schema_version` mismatch, must do a "visible
refuse": post a comment on the workflow ROOT (so the human/next worker sees
why) AND veto the tool via `{"action":"block",...}`. Neither step may raise
(a raise fails open — see Spike 1). This spike confirms the comment step is
permitted from a worker context and that the comment author can't be forged.

**Coverage legend** (same convention as Spikes 1–3):
- **[test]** = directly asserted by `test_spike_version_gate.py`.
- **[source]** = confirmed by reading the pinned Hermes source, NOT exercised
  by a test (re-verify if Hermes moves).

### Cross-task commenting is UNRESTRICTED; author is FORCED **[test]**
A worker (process with `HERMES_KANBAN_TASK` set to its OWN card, `other`) can
`kanban_comment` on a FOREIGN card (the `root`):
- `_handle_comment({"task_id": root, "body": "…"})` returns `ok: true` even
  though `root` is not the worker's task — NO ownership check fires. The exact
  return STRING observed under a tmp board:
  ```json
  {"ok": true, "task_id": "t_28948454", "comment_id": 1}
  ```
- **Author is forced**, not taken from args: calling with an explicit
  `args["author"] = "hermes-system"` still records author `"worker"`
  (= `os.environ.get("HERMES_PROFILE") or "worker"`; `HERMES_PROFILE` is unset
  in the test env). The forged value is IGNORED. Asserted by reading the
  persisted comment back via `kb.list_comments(conn, root)[0].author`
  (a `Comment` dataclass, `kanban_db.py:880`, `.author` ATTRIBUTE).

### CONFIRMED `_handle_comment` signature + return contract (`tools/kanban_tools.py`)
```python
_handle_comment(args: dict, **kw) -> str
```
- Reads `args.get("task_id")` (required; `tool_error("task_id is required …")`
  if missing/falsy, `:690-694`) and `args.get("body")` (required; `tool_error`
  if missing/blank, `:695-696`). Optional `args.get("board")` (`:708`) forwarded
  to `_connect`. **[source]**
- **Author forcing** (`:707`): `author = os.environ.get("HERMES_PROFILE") or
  "worker"` — caller-supplied `args["author"]` is intentionally IGNORED. The
  `:698-706` comment explains why: comments are injected into the NEXT worker's
  system prompt as `**{author}** (ts): {body}`, so accepting an author override
  would let a worker forge a `hermes-system`-looking directive and poison
  future-worker context. **[test + source]**
- **No ownership check** — `_handle_comment` never calls
  `_enforce_worker_task_ownership`. `:705-706` records the deliberate design:
  "Cross-task commenting itself remains unrestricted (see #19713) — comments are
  the deliberate handoff channel between tasks." **[test + source]**
- Connects via `_connect(board=board)` (`:710`) → `kb.connect(board=…)`. With
  `board=None` the resolution chain is `HERMES_KANBAN_DB` → `HERMES_KANBAN_BOARD`
  env → symlink → `default` (`:164-176`). The `tmp_board` fixture pins
  `HERMES_KANBAN_BOARD="test"` under `HERMES_HOME=<tmp_path>`, so the handler's
  own (separate) connection resolves the SAME board file the fixture wrote to —
  the persisted comment reads back fine. **[test confirms: read-back works]**
- Success → `_ok(task_id=tid, comment_id=cid)` = `json.dumps({"ok": True,
  "task_id": tid, "comment_id": cid})` (a JSON STRING). Failure → `tool_error(…)`
  (a JSON string containing `error`/`ok:false`). **[test + source]**
- `add_comment(conn, task_id, author, body) -> int` (`kanban_db.py:2465`) raises
  `ValueError("unknown task …")` if the task row is absent — surfaced by
  `_handle_comment` as `tool_error("kanban_comment: …")`. Not hit here. **[source]**

### CONTRAST — complete/block ARE ownership-enforced (NOT tested, for understanding) **[source]**
`_enforce_worker_task_ownership(tid) -> Optional[str]` (`tools/kanban_tools.py:132-161`):
reads `env_tid = os.environ.get("HERMES_KANBAN_TASK")`; if set (= worker context)
and `tid != env_tid`, returns a `tool_error` refusing to mutate the foreign task
("Use kanban_comment to hand off information …"). `kanban_complete`/`kanban_block`/
`kanban_heartbeat` call this and reject foreign task ids (see #19534). Orchestrator
profiles (kanban enabled but NO `HERMES_KANBAN_TASK`) are exempt. **Comments are
the deliberate exception** — which is exactly why the gate's visible-refuse can
comment on the root from a worker.

### Why the gate MUST be worker-side + exception-proof — `resolve_profile_env(assignee)` **[source]**
The dispatcher resolves the worker's `HERMES_HOME` from the ASSIGNEE's profile:
`env["HERMES_HOME"] = resolve_profile_env(profile_arg)` (`hermes_cli/kanban_db.py:6468`,
where `profile_arg` is the assignee profile; falls back to `HERMES_PROFILE` deferral
on `FileNotFoundError`, `:6469-6474`). So the hook + veto execute under the WORKER
profile's home — and the plugin VERSION installed in that home CAN differ from the
orchestrator's stamped `schema_version`. That is why the §2 version gate must run
worker-side (it's the only place that sees the worker's actual installed version)
AND must be exception-proof (a `pre_tool_call` raise fails open, per Spike 1, so it
must veto by RETURNING the block dict and post the refuse-comment without raising).

### Fixture note — `as_worker` (`tests/conftest.py`) **[test]**
`as_worker(task_id)` is a context manager that sets `HERMES_KANBAN_TASK=task_id`
for the block and restores the prior value (or pops it) on exit. It mutates
`os.environ` directly with self-contained save/restore (not `monkeypatch`) so it
can be entered/exited mid-test around a single tool call. Required `import
contextlib` added to conftest (Task 3 had left it out as unused).

## Spike 5 — abandon: leaves-first archive, host-only, worktree preserved
Confirms the abandon design's archive step against real `hermes_cli.kanban_db`
(no LLM). Test file: `tests/integration/test_spike_abandon.py`.

### `archive_task(conn, task_id) -> bool` (`kanban_db.py:4486-4509`) **[test for return + leaves-first; source for the rest]**
- Returns **`True`** on a real archive; **`False`** when already archived / not
  found — guarded by `WHERE id=? AND status != 'archived'` + a `rowcount != 1`
  check (`:4491-4495`). This is the idempotent guard (a second archive of the
  same task → `False`). **[test]**
- Nulls `claim_lock`, `claim_expires`, **`worker_pid`** in the same UPDATE
  (`:4489-4490`). It does **NOT** SIGTERM/signal a worker — it only drops the
  pid reference. (Killing a live worker is `reclaim_task`'s job; archive just
  forgets the pid.) **[source]**
- Ends any in-flight run via `_end_run(..., outcome="reclaimed",
  status="reclaimed", summary="task archived with run still active")`
  (`:4499-4503`) and appends an `archived` event (`:4504`). **[source]**
- After committing, calls **`recompute_ready(conn)`** (`:4508`) because an
  `archived` parent (like `done`) no longer blocks children — newly-unblocked
  dependents are promoted immediately. This is the source of the transient-ready
  hazard below. **[source]**
- Contains **NO `_cleanup_workspace` call** → archive preserves ALL workspaces
  (scratch/dir/worktree). **[source + test]**

### Leaves-first vs parent-first — the transient-ready finding **[test]**
- `parent = mk_card(title="parent")` (no parents) is **`ready` from birth**;
  `child = mk_card(parents=[parent], assignee="real-profile")` is **`todo`**.
- **Hazard (parent-first):** `archive_task(parent)` → its `recompute_ready`
  promotes the `todo` child to **`ready`** (the child's only parent is now
  `archived`, which satisfies promotion). Confirmed by
  `test_parent_first_archive_transiently_promotes_child`.
- **Safe (leaves-first):** archive the leaf `child` FIRST (→ `archived`), THEN
  the `parent`. The parent's `recompute_ready` runs, but the child is already
  `archived` and is NOT transiently re-promoted. Confirmed by
  `test_leaves_first_archive_avoids_transient_ready`.
- **WHY abandon must archive in reverse-topological (leaves-first) order:** to
  avoid momentarily flipping an interior stage to `ready` (which a racing
  dispatcher tick could otherwise claim) while tearing a workflow down.

### Host-only archive — finding Y **[source]**
- `tools/kanban_tools.py` registers **exactly 9** kanban MODEL tools
  (`:1353-1430`): `kanban_show`, `kanban_list`, `kanban_complete`,
  `kanban_block`, `kanban_heartbeat`, `kanban_comment`, `kanban_create`,
  `kanban_unblock`, `kanban_link`.
- There is **NO `kanban_archive` and NO `kanban_unlink`** model tool (grep:
  none). Archive (and unlink) are reachable ONLY via the host `kb.*` layer
  (`kb.archive_task`) — the model cannot self-archive. Abandon must therefore
  run host-side. **(finding Y confirmed)**

### Reclaim / terminate signatures (for "reclaim/terminate running workers BEFORE archiving") **[source]**
Not exercised (no live workers in a no-LLM board) — recorded for the design step.
- `reclaim_task(conn, task_id, *, reason=None, signal_fn=None) -> bool`
  (`kanban_db.py:3273`): operator-driven immediate reclaim regardless of TTL.
  Returns `False` if not in a reclaimable state (not `running` and
  `claim_lock IS NULL`, `:3297-3299`); on success resets to `ready`, nulls
  claim/`worker_pid`, ends the run `reclaimed`, appends a `reclaimed` event,
  and clears the failure counter (`:3304-3339`). Calls
  `_terminate_reclaimed_worker(...)` to actually signal the worker (`:3301`).
- `_terminate_reclaimed_worker(pid, claim_lock, *, signal_fn=None) -> dict[str, Any]`
  (`kanban_db.py:4939`; also used at `:3229`, `:5229`): the path that SIGTERMs a
  reclaimed worker (signal injectable via `signal_fn`), returning a termination
  metadata dict. **This — not `archive_task` — is what kills a worker.** So the
  abandon order is: `reclaim_task` (terminates the worker) THEN `archive_task`
  (forgets the pid, marks archived), leaves-first.

### Workspace preservation **[source + test]**
- `_cleanup_workspace(conn, task_id)` (`kanban_db.py:3766-3783`) is called ONLY
  from the COMPLETION path (`complete_task`), and even there removes ONLY
  `scratch` workspaces — `worktree` and `dir` are "intentionally preserved"
  (docstring `:3771-3772`, guard `:3783`). **[source]**
- Archive never calls it → **archive preserves ALL workspaces**. Verified by
  `test_archive_preserves_dir_workspace`: a `dir` workspace with a sentinel
  file survives `archive_task` untouched. (`create_task` records
  `workspace_path` for `dir`/`worktree` without provisioning the dir,
  `:2132-2137`/`:2176-2206` — so the sentinel-file test is clean.) **[test]**

### Plan carry-forward corrections (the plan's literal Task 5 code was buggy) **[test]**
- The plan used **`role_assignee=`** — the real `mk_card`/`Board.create` kwarg is
  **`assignee=`** (`tests/conftest.py:61`). Used `assignee="real-profile"`.
- The plan asserted `status(parent) != "ready"` on a freshly-created no-parent
  card — that is **wrong**: a no-parent card is `ready` from birth, so the
  assertion fails. This was a PLAN TEST-CODE bug, NOT a spike-stop; the
  underlying behavior (leaves-first avoids transient-ready) is intact. The
  corrected tests assert on the CHILD's status across the two archive orders,
  which is what actually demonstrates the hazard.

## Reference signatures (confirmed by source read; not behavior-tested) **[source]**

These host-layer (`kb.*`) signatures are confirmed against the pinned source for the
Phase-0 Definition of Done; they are read-only references the Phase-1+ board adapter /
reconcile code will call (no model tool exists for `unlink`/`archive` — finding Y).

### `list_tasks` (`hermes_cli/kanban_db.py:2267-2279`)
```python
list_tasks(conn, *, assignee=None, status=None, tenant=None, session_id=None,
           include_archived=False, limit=None, order_by=None,
           workflow_template_id=None, current_step_key=None) -> list[Task]
```
- Keyword-only after `conn`; `status` validated against `VALID_STATUSES` (raises `ValueError`).
- Orchestrator-only board-wide sweep (finding L: workers can't `kanban_list`; the
  list rows carry **no body**). Use for board-wide sweeps / reconcile dedup, NOT for
  per-run enumeration (which is a link-walk from the root via `get_task`).

### `unlink_tasks` (`hermes_cli/kanban_db.py:2409`)
```python
unlink_tasks(conn, parent_id, child_id) -> bool
```
- Host-only edge removal — **there is NO `kanban_unlink` model tool** (finding Y).
  Returns `True` if an edge was removed. Reconcile dedup re-wire is two ordered host
  steps: `kb.link_tasks(winner→join)` THEN `kb.archive_task(loser)` (link + archive
  cannot share one txn; the archived loser is a satisfied parent so its dangling edge
  is harmless — §5.7).

### `latest_run` (`hermes_cli/kanban_db.py:7398`)
```python
latest_run(conn, task_id) -> Optional[Run]
```
- Returns the most recent `task_runs` row as a `Run`, or `None`.
- `Run` (dataclass, `:825-851`) fields: `id, task_id, profile, step_key, status,
  claim_lock, claim_expires, worker_pid, max_runtime_seconds, last_heartbeat_at,
  started_at, ended_at, outcome, summary, metadata, error`.
- **`Run.metadata`** is the structured handoff dict (parsed from JSON). It persists
  indefinitely (NO time-GC — findings W/D1; only `task_events` + worker logs are
  30-day GC'd). Reconcile reads this UNBOUNDED column directly, NOT the ~4 KB-truncated
  `build_worker_context` view (finding R). This is the durable source-handoff input the
  graph function re-runs from.

## §14 Open question CLOSED (Task 17) — hook fan-out does NOT trip `HallucinatedCardsError` **[test + source]**

The §14 worry: cards the `post_tool_call` fan-out hook creates via
`dispatch_tool("kanban_create")` — fired from inside a completing worker — might trip
the `created_cards` / `HallucinatedCardsError` gate in `complete_task`. **CLOSED: it
cannot. HallucinatedCardsError did NOT trip.**

Source reason (read by this task):
- The gate in `complete_task` (`hermes_cli/kanban_db.py:3550`) is `if created_cards:`
  — it ONLY runs when a completion explicitly passes a truthy `created_cards` list,
  then `_verify_created_cards` (`:3373`) checks each id against `tasks.created_by` and
  `raise HallucinatedCardsError(...)` on a phantom (`:3568`).
- `_handle_complete` (`tools/kanban_tools.py:489-501, 560`) only forwards
  `created_cards` to `complete_task` when the WORKER itself passed it on the
  `kanban_complete` call. The completed-metadata is read later from the board (by
  RunView), never from this arg.
- The fan-out hook runs in `post_tool_call` (`model_tools.py:993-1006`) AFTER
  `kanban_complete` already returned, and only calls `kanban_create`/`kanban_link`/
  `kanban_comment` — NEVER `kanban_complete`/`complete_task(..., created_cards=...)`.
  So the gate is structurally unreachable from the hook.
- `kanban_create` stamps `created_by = os.environ.get("HERMES_PROFILE") or "worker"`
  (`tools/kanban_tools.py:817`), so the hook's cards are attributable, not phantom,
  even if a later completion ever did declare them.

Proof (`tests/integration/test_hook_fanout.py::test_hook_fans_out_on_scan_complete`):
`on_tool_done(...)` is fired INSIDE `as_worker(scan_id)` (sets `HERMES_KANBAN_TASK` —
the realistic worker context). After the hook, RunView resolves `("fix",0,0)`,
`("fix",1,0)` and the R5 join `("approve",0,0)` to real cards. Those cards can only
exist if `dispatch_tool("kanban_create")` SUCCEEDED — a `HallucinatedCardsError` would
have surfaced as a tool_error and the cards would be ABSENT. They are present, so the
gate never fired. (Belt-and-suspenders: `invoke_hook`, `plugins.py:1556-1568`, also
wraps each callback in its own try/except, but the hook is side-effect-only and
never-raises in its own right — `tests/integration/test_hook_fanout.py`.)
