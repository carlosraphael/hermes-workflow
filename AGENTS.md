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

> **Binding rules live in [`## Key invariants`](#key-invariants) and
> [`## Definition of Done`](#definition-of-done) — treat them as merge-blocking.
> Read this whole file before changing engine, hook, veto, or provenance code.**

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
│   └── reconcile.py   # plan_collapse: pure duplicate-collapse planner (pick_winner + relink/reclaim/archive)
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

**These are merge-blocking guarantees.** A PR that weakens any invariant below is
rejected. If you must change one, change its pinning test in the **same** PR and
say so in the description.

- **No raw SQLite anywhere.** All DB access goes through `ctx.dispatch_tool`
  (`WorkerBoard`) or host `kb.*` (`HostBoard` / `RunView` db-path). The single
  host connection is opened via `kanban_db.connect_closing` in
  `tools.py::_host_board` (closes the FD on exit — Hermes #33159).
  _Pinned by `tests/unit/test_no_raw_sqlite.py`._
- **Engine purity.** Engine code (`engine/*.py`) imports stdlib + PyYAML +
  intra-package only — never the board, Hermes, or any other third-party package.
  This is the load-bearing supply-chain guarantee: the engine's dependency floor
  stays at PyYAML. _Pinned by `tests/unit/test_engine_purity.py`._
- **No core modification.** This plugin reaches Hermes ONLY through the generic
  plugin surface — `ctx.register_tool` / `register_hook` / `register_cli_command`
  / `register_command` / `register_skill` in `register(ctx)` (`__init__.py`). It
  never patches `run_agent.py`, `cli.py`, `gateway/run.py`, or
  `hermes_cli/main.py`. A capability the surface doesn't expose is upstreamed as a
  new hook / ctx method, not hardcoded into core (Hermes "plugins MUST NOT modify
  core files", Teknium / PR #5295). _Structural (standalone repo); not separately
  test-pinned._
- **Injection-free deterministic gate.** Every `subprocess.run` uses a fixed argv
  list with no shell and no untrusted interpolation (`veto.py` commit-clean is
  `["git","-C",dir,"status","--porcelain"]`; `worktree.py` branch is
  engine-derived; `preflight.py` is `[sys.executable,"-m",…]`).
  _Not yet test-pinned — add a test if you touch the gate's argv construction._
- **Veto fails CLOSED.** `evaluate_completion_gate` and the `on_tool_pre` `except`
  both return a block dict on any error; `is_version_compatible` is total and
  returns `False` for anything it cannot positively confirm.
  _Pinned by `tests/unit/test_veto.py`._
- **Fan-out fails OPEN.** The `post_tool_call` fan-out driver (`hooks.py::on_tool_done`)
  is a side-effect that materializes the next layer; its whole body is one
  try/except that logs and swallows and **never raises** — a raising side-effect
  hook would wedge the worker that just completed legitimate work.
  _Pinned by `tests/integration/test_hook_fanout.py`._
- **Total version gate.** `parse_root_body` raises by design on a malformed root
  (callers wrap it and fail loud); `is_version_compatible` never raises. A
  schema-version mismatch is a *visible refuse*, never a silent mis-drive.
  _Pinned by `tests/integration/test_spike_version_gate.py`._
- **Base64-encoded provenance envelope** (`engine/provenance.py`): the sentinel
  and snapshot payloads are base64'd so author content containing `-->` (the
  close marker) cannot truncate serialization. `extract_sentinel` stays
  fail-soft; `parse_root_body` stays raising.
  _Pinned by `tests/unit/test_provenance.py`._
- **Sentinel root assignee is non-spawnable.** `_workflow_root` (and the
  `_workflow_gate` gate assignee) lead with `_`, so the dispatcher treats them as
  `skipped_nonspawnable` — the root blackboard and human gates never auto-spawn a
  worker. _Pinned by `tests/integration/test_spawnability.py`._

Cross-check against `version.py` and `engine/provenance.py`.

## Adding a tool or hook

Tools follow `COMMANDS → make_tool_handler → register(ctx)`. The `COMMANDS`
descriptor tuple (`tools.py`) is the **single source of truth**: one frozen
`Command(name, fn, schema, bind, positional, cli_args)` per tool drives tool
registration, the `hermes workflow <cmd>` subparser, and `/workflow` dispatch.
Adding a tool is one descriptor — never a separate edit to the argparse setup or
the dispatch routing (both loop `COMMANDS`).

1. Write `workflow_<verb>(ctx, *, …)` in `tools.py` returning a plain dict
   (`{"error": …}` on failure — the **flat-error contract**). Mutating tools call
   `_require_orchestrator(...)` to self-refuse inside a dispatcher-spawned worker
   (`HERMES_KANBAN_TASK` set).
2. Add a schema dict and one `Command(...)` entry to `COMMANDS`. Its `positional`
   + `cli_args` describe the CLI subparser; its `bind` maps the parsed argparse
   namespace to the tool's keyword args (the one place `--template` is read off
   disk and `--params`/`--bindings` JSON is decoded). The CLI/slash subcommand is
   the tool name minus the `workflow_` prefix (`workflow_start` → `start`).
3. `register(ctx)` (`__init__.py`) loops `COMMANDS`, registering each under
   toolset `workflow` with `make_tool_handler(ctx, cmd.fn)` — which unpacks args
   into `fn(ctx, **args)`, JSON-serializes the dict, and converts any exception
   into a `{"error": …}` envelope so the handler never raises.

Both hooks are registered in `register(ctx)` and **bound to `ctx` via a closure**
— Hermes' hook invoke calls `cb(**kwargs)` and does **not** pass `ctx`. New
hooks **MUST** wrap their body in a try/except matching the channel's failure
mode (`post_tool_call` fail-open; `pre_tool_call` fail-closed); **reviewers
reject a hook that can raise out of the wrong channel.**

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

### Don't write change-detector tests

A test that fails whenever data *expected to change* is updated (a version
literal, an enumeration count, a catalog snapshot) adds no behavioural coverage —
it just breaks CI on routine edits. Assert **relationships and invariants**, not
snapshots.

```
DON'T:
  assert PLUGIN_VERSION == "0.1.4"
  assert len(KNOWN_LANES) == 2

DO:
  assert SCHEMA_VERSION in SUPPORTED_SCHEMA_VERSIONS
  assert "codex" in KNOWN_LANES and "claude-code" not in KNOWN_LANES
```

Reviewers reject new change-detector tests; convert them into invariants first.
(`test_no_raw_sqlite`, `test_engine_purity`, and `test_supply_chain_pins` are the
model: they assert a property, not a snapshot.)

### Why plain `pytest` (no hermetic wrapper)

The plugin runs `python3 -m pytest` directly — there is no `scripts/run_tests.sh`.
Tests use no LLM and no credentials, so the core's hermetic credential-stripping
wrapper buys nothing here; the one process-global (`pre_tool_call` hooks) is
isolated by the `register_pre_hook` fixture teardown, and `HERMES_HOME` is
redirected to `tmp_path` by the `tmp_board` fixture. Per-test process isolation is
intentionally **not** adopted. Coverage and the integration tier are not gated in
CI (the latter needs a real Hermes checkout via `HERMES_AGENT_ROOT`).

## Definition of Done

**Before you claim any task complete or open a PR you MUST run through every
applicable item below and back each with evidence — actual command output, not
assertion. If an item does not apply, state why. Skipping this checklist is
itself a governance violation.** This is the authoritative pre-submit gate;
`CONTRIBUTING.md` "Before opening" and the PR template mirror it.

**1. Tests — run them, don't assume.**
- [ ] Ran `python3 -m pytest -m 'not integration'` — green (paste the result line).
- [ ] If the change touches the board / materialize / runview / reconcile /
  veto-on-board path: ran `python3 -m pytest` with `HERMES_AGENT_ROOT` set — or
  stated why it couldn't run.
- [ ] New/changed behaviour has a test; existing coverage not weakened.
- [ ] No change-detector tests added (assert relationships, not snapshots /
  counts / version literals).

**2. Invariants — merge-blocking.**
- [ ] Every invariant in `## Key invariants` still holds (no raw SQLite; engine
  purity; no core modification; injection-free fail-closed gate; fail-open
  fan-out; total version gate; base64 provenance; non-spawnable sentinels).
- [ ] If I changed an invariant, I changed its pinning test in the **same** change
  and said so.

**3. Governance & conventions.**
- [ ] Commit(s) are Conventional `type(scope):`; **one logical change**; branch
  `type/short-slug`.
- [ ] Any new PyPI dep has a `<next_major` (pre-1.0: `<0.(minor+2)`) ceiling; any
  new Action is SHA-pinned with a `# vX.Y.Z` comment
  (`tests/unit/test_supply_chain_pins.py` enforces both).
- [ ] Engine still imports stdlib + PyYAML + intra-package only; Hermes reached
  only via `ctx.register_*` — no core file patched.

**4. Docs kept current (whenever applicable).**
- [ ] Updated every doc the change touches — `README.md`, `AGENTS.md`,
  `CONTRIBUTING.md`, `docs/operations.md`, `CHANGELOG.md` — or confirmed none apply.
- [ ] No surviving claim/example contradicts the change (stale "Future work"
  lists, version refs, the `CONTEXT.md` naming taxonomy).

**5. Scope discipline.**
- [ ] Every changed line traces to the task; no unrelated refactor/reformat;
  cleaned only the orphans my own change created.

**6. Cross-platform.**
- [ ] No Unix-isms introduced — subprocess via argv lists (no `shell=True`),
  `pathlib`, no `os.kill(pid, 0)` liveness, no hardcoded `/tmp`.

## Cross-platform

**Posture: POSIX only — Linux, macOS, and WSL2 on Windows. Native Windows is out
of scope for the 0.x line.** The engine is pure stdlib + PyYAML; the only OS
surface is git subprocess calls and a per-profile subprocess spawn, both assuming
a POSIX shell/path environment. The code stays cross-platform-clean by
construction — preserve these when editing:

- **No PID/signal liveness probes.** Idempotency is filesystem- and board-state
  derived (`worktree.py` checks `(<path>/.git).exists()`), never `os.kill(pid, 0)`.
- **Subprocess via argv lists, never a shell.** `subprocess.run(["git", "-C", …])`;
  convert paths with `str(path)` only at the subprocess boundary.
- **`pathlib` for all paths**; worktrees live under
  `<repo>/../.hermes-workflow-worktrees/` (not a temp dir); no hardcoded `/tmp`.
- **`git` is a hard prerequisite** (assumed on `PATH`); **`codex` is optional and
  `shutil.which`-gated** in pre-flight — the asymmetry is intentional.
- **Self-invocation via `[sys.executable, "-m", …]`**, never a shebang.
- **No `psutil`** — the plugin owns no process lifecycle, so cross-platform
  process remedies are intentionally N/A and the dependency floor stays at PyYAML.

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
