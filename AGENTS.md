# hermes-workflow — Development Guide

Engineering guide for AI coding assistants and developers working on
`hermes-workflow`: a declarative, versioned, multi-stage workflow primitive over
the Hermes Kanban board, shipped as a standalone (entry-point) Hermes plugin.

Read [`CONTEXT.md`](CONTEXT.md) **first** — it pins the naming taxonomy. The four
layers are distinct and conflating them causes real packaging/import bugs:
**distribution + plugin name** `hermes-workflow`, **import package**
`hermes_workflow` (src-layout), **runtime surface** the unprefixed `workflow`
(CLI `hermes workflow`, slash `/workflow`, toolset `workflow`, tools
`workflow_start`…`workflow_abandon`).

## Working principles

- **Think before coding.** State assumptions; surface tradeoffs; if multiple
  interpretations exist, present them rather than pick silently. When something
  is unclear, stop and name it.
- **Simplicity first.** Minimum code that solves the problem — nothing
  speculative. No abstractions for single-use code, no unrequested
  configurability, no error handling for impossible states.
- **Surgical changes.** Touch only what the task requires; match existing style;
  don't refactor what isn't broken. Clean up only the orphans your own change
  creates — mention pre-existing dead code, don't delete it.
- **Goal-driven execution.** Turn each task into a verifiable goal ("fix the bug"
  → "write a failing test that reproduces it, then make it pass") and loop until
  the check is green.

## Development environment

```bash
python3 -m venv .venv && source .venv/bin/activate   # Python >= 3.11
pip install -e '.[dev]'                              # editable install + pytest
```

The integration suite drives a **real Hermes board with no LLM**, so it needs a
Hermes Agent checkout on `sys.path`. Point `HERMES_AGENT_ROOT` at one (the
`conftest.py` default is `/Users/carlos/cortex-workspace/hermes-agent`); when the
checkout is absent the integration fixtures `pytest.skip` rather than fail.

## Project structure

src-layout: importable code lives under `src/hermes_workflow/` so tests run
against the installed package. One-line purpose per module:

```
src/hermes_workflow/
├── __init__.py        # register(ctx): wire tools + both hooks + CLI + slash + skills
├── version.py         # PLUGIN_VERSION / SCHEMA_VERSION / SUPPORTED_SCHEMA_VERSIONS + sentinel assignees
├── tools.py           # the six orchestrator-facing workflow_* funcs + schemas + CLI/slash dispatch
├── hooks.py           # post_tool_call fan-out driver + pre_tool_call completion gate
├── veto.py            # PURE, TOTAL completion-gate logic (expand_out shape+max, commit-clean)
├── materialize.py     # turn engine CardSpecs into real board cards (sentinel + lifecycle preamble, joins R5)
├── board.py           # WorkerBoard (ctx.dispatch_tool surface) + HostBoard (host kb.* surface)
├── runview.py         # link-walk the run from the root into a live picture for the engine
├── preflight.py       # per-profile loadability probe (one spawned subprocess per profile)
├── sweep.py           # reverse-topological (leaves-first) ordering for hazard-free abandon
├── worktree.py        # pure git worktree pre-provisioning (idempotent, base-ref pinned)
├── engine/
│   ├── model.py       # frozen dataclasses: Param, Role, ExpandSpec, ExpandOut, Stage, Template
│   ├── template.py    # parse_template + validate_template (the deterministic gatekeeper)
│   ├── interpolate.py # ${params.*} / ${<expand-var>.*} substitution; raises on unknown refs
│   ├── graph.py       # cards_for_run: which CardSpecs should exist up to the next dynamic boundary
│   ├── provenance.py  # base64 sentinel/snapshot envelope embed/extract + version compat
│   └── reconcile.py   # pick_winner: deterministic duplicate-collapse tiebreak
├── lanes/presets.py   # lane contract: which bundled skill a lane requests ({profile, codex})
└── skills/            # bundled workflow-author / workflow-orchestrator skills (auto-registered)
```

## Architecture

Materialization is **lazy and single-level** — the engine only ever asks for the
cards up to the next dynamic (fan-out) boundary.

- **`workflow_start`** (`tools.py`) validates the template + bindings, runs the
  per-profile pre-flight, then seeds the run: it writes a write-once
  compiled-snapshot **blackboard root** (a completed card carrying the base64
  snapshot, assignee `_workflow_root`) and materializes the **dynamic-free
  prefix** (entry stages with no fan-out dependency yet). Pre-flight is
  fail-closed and zero-cards-on-failure.
- **`post_tool_call` fan-out driver** (`hooks.py::on_tool_done`) runs in the
  completing worker's process. It self-gates on `kanban_complete` + a successful
  result + a sentinel, version-gates, then drives `materialize` to create the
  next layer — fan-out children **and** their join — wiring the join atomically
  to every instance parent (`materialize.py`, R5). It is fail-open: the whole
  body is one try/except that logs and swallows, never raises.
- **`pre_tool_call` deterministic veto** (`hooks.py::on_tool_pre` →
  `veto.evaluate_completion_gate`) is the only blocking channel: it checks
  `expand_out` shape + `max` and commit-clean for worktree stages before a stage
  may complete. **No LLM in the gate.** It vetoes by *returning* a block dict and
  **fails CLOSED** — any internal error returns a block, never `None`/raise
  (a raising `pre_tool_call` fails OPEN at the host).
- **`RunView`** (`runview.py`) enumerates the run by link-walking DOWN from the
  root (`children`), recovering each sentinel card's `Identity`, status, and
  latest-done metadata — the bridge from board state to the pure engine.

## Key invariants

- **No raw SQLite anywhere.** All DB access goes through `ctx.dispatch_tool`
  (`WorkerBoard`) or host `kb.*` (`HostBoard` / `RunView` db-path). The single
  host connection is opened via `kanban_db.connect_closing` in
  `tools.py::_host_board` (closes the FD on exit — Hermes #33159). A
  `test_no_raw_sqlite` meta-test walks the package to keep this true.
- **Injection-free deterministic gate.** Every `subprocess.run` uses a fixed argv
  list with no shell and no untrusted interpolation (`veto.py` commit-clean is
  `["git","-C",dir,"status","--porcelain"]`; `worktree.py` branch is
  engine-derived; `preflight.py` is `[sys.executable,"-m",…]`).
- **Veto fails CLOSED.** `evaluate_completion_gate` and the `on_tool_pre` `except`
  both return a block dict on any error; `is_version_compatible` is total and
  returns `False` for anything it cannot positively confirm.
- **Total version gate.** `parse_root_body` raises by design on a malformed root
  (callers wrap it and fail loud); `is_version_compatible` never raises. A
  schema-version mismatch is a *visible refuse*, never a silent mis-drive.
- **Base64-encoded provenance envelope** (`engine/provenance.py`): the sentinel
  and snapshot payloads are base64'd so author content containing `-->` (the
  close marker) cannot truncate serialization. `extract_sentinel` stays
  fail-soft; `parse_root_body` stays raising.
- **Sentinel root assignee is non-spawnable.** `_workflow_root` (and the
  `_workflow_gate` gate assignee) lead with `_`, so the dispatcher treats them as
  `skipped_nonspawnable` — the root blackboard and human gates never auto-spawn a
  worker.

Cross-check against
[`docs/superpowers/reviews/2026-06-04-hermes-workflow-v0.1.0-audit.md`](docs/superpowers/reviews/2026-06-04-hermes-workflow-v0.1.0-audit.md),
`version.py`, and `engine/provenance.py`.

## Adding a tool or hook

Tools follow `TOOL_SPECS → make_tool_handler → register(ctx)`:

1. Write `workflow_<verb>(ctx, *, …)` in `tools.py` returning a plain dict
   (`{"error": …}` on failure — the **flat-error contract**). Mutating tools call
   `_require_orchestrator(...)` to self-refuse inside a dispatcher-spawned worker
   (`HERMES_KANBAN_TASK` set).
2. Add a schema dict and an entry to the `TOOL_SPECS` list.
3. `register(ctx)` (`__init__.py`) loops `TOOL_SPECS`, registering each under
   toolset `workflow` with `make_tool_handler(ctx, fn)` — which unpacks args into
   `fn(ctx, **args)`, JSON-serializes the dict, and converts any exception into a
   `{"error": …}` envelope so the handler never raises.

Both hooks are registered in `register(ctx)` and **bound to `ctx` via a closure**
— Hermes' hook invoke calls `cb(**kwargs)` and does **not** pass `ctx`. New
hooks must wrap their body in a try/except matching the channel's failure mode
(`post_tool_call` fail-open; `pre_tool_call` fail-closed).

## Skills

Two bundled skills under `skills/`, auto-registered on plugin load (`register`
walks `skills/*/SKILL.md` and calls `ctx.register_skill`):

- **`workflow-author`** — writing a `*.workflow.yaml` within the 0.1.0
  constraints; validating it with `workflow_validate`.
- **`workflow-orchestrator`** — start / status / approve / abandon / reconcile,
  plus the review-required backstop for a stalled stage.

The dir guard keeps `register` crash-free if `skills/` is absent.

## Testing

```bash
python3 -m pytest                          # full suite
python3 -m pytest tests/unit               # pure, hermes_workflow-only
python3 -m pytest -m integration           # real board, no LLM (needs HERMES_AGENT_ROOT)
```

Two tiers, **no LLM in any test**:

- **`tests/unit/`** (plus a couple of pure tests directly under `tests/` —
  `test_preflight_eval.py`, `test_sweep.py`) — pure: import `hermes_workflow`
  only (engine, veto, provenance, worktree, reconcile). No board, no Hermes.
- **`tests/integration/`** — marked `pytestmark = pytest.mark.integration`. Each
  drives a real Hermes board via `fake_ctx` (routes `dispatch_tool` to the real
  kanban registry) over the `tmp_board` SQLite harness in
  `tests/integration/board.py`. Needs `HERMES_AGENT_ROOT` (the `hermes_root`
  fixture puts the checkout on `sys.path`, else skips).

`conftest.py` provides the board harness and the `register_pre_hook` fixture,
whose teardown removes EXACTLY the callbacks it appended from the process-global
`pre_tool_call` hook singleton (a leak corrupts every later test in the session).

## Known pitfalls

- **Per-profile enablement is the #1 failure mode.** Workers load the plugin from
  the *assignee profile's* home, so `hermes-workflow` must be in `plugins.enabled`
  in **every** bound profile's `config.yaml`, not just the orchestrator's.
- **Entry-point plugins are NOT enabled via `hermes plugins enable`** (that
  command only sees user-dir + bundled plugins). Add `hermes-workflow` to the
  `plugins.enabled` *list* in each profile's `config.yaml` (`hermes -p <profile>
  config edit`). Do **not** `hermes config set plugins.enabled …` — it writes a
  scalar string and breaks the loader's list check. The change takes effect next
  session.
- **Nested fan-out is forbidden in 0.1.0** — an `expand` stage may not itself be
  an `expand` source, and `verify` / `retry` are likewise rejected by
  `template.py::validate_template`. The `claude-code` lane is **not** rejected —
  it is simply absent from `KNOWN_LANES` (`lanes/presets.py`) and deferred to
  0.2.x.
- **Lanes are `{profile, codex}` only** (`lanes/presets.py::KNOWN_LANES`). A
  `codex` role additionally requires the `codex` binary on `PATH` and Hermes'
  bundled `kanban-codex-lane` skill in the bound profile — pre-flight checks both.
- **Worker profiles must NOT set `worktree:true`** — the engine pre-provisions one
  worktree per fan-out child deterministically; a profile-level flag
  double-provisions (Hermes finding Q).

Verify against [`README.md`](README.md) and [`docs/operations.md`](docs/operations.md).
