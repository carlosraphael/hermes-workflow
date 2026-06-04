# hermes-workflow

A declarative, versioned, multi-stage workflow primitive over the Hermes Kanban board.

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python: >=3.11](https://img.shields.io/badge/python-%3E%3D3.11-blue.svg)](pyproject.toml)
[![CI](https://github.com/carlosraphael/hermes-workflow/actions/workflows/ci.yml/badge.svg)](https://github.com/carlosraphael/hermes-workflow/actions)

A `*.workflow.yaml` template — params, abstract roles bound to lanes, stages with
`needs`, a single-level `expand` fan-out plus an `expand_out` shape gate, a human
`gate`, and workspaces — is instantiated into a Kanban card-graph that Hermes'
existing dispatcher and worker lanes execute. It turns "hand-wire an orchestrator
from scratch every run" into a repeatable, durable, inspectable run on the board
you already use.

## What it is

A template compiles to a linked card-graph. Materialization is **lazy and
single-level**:

- `workflow_start` validates the template + bindings, runs a per-profile
  pre-flight, and creates the **dynamic-free prefix** (the static stages up to
  the first fan-out) plus a write-once compiled-snapshot **blackboard root**.
- The `post_tool_call` **fan-out hook** fires as stages complete: when a source
  stage finishes, it creates that fan-out's children **and** its join in one
  atomic create, wiring the join as a child of every instance.

Completion-gating is **deterministic and injection-free**, enforced by a
`pre_tool_call` veto: it checks the `expand_out` shape + `max`, and commit-clean
for worktree stages, before a stage may complete. There is no LLM in the gate.

All state lives on the board — body sentinels, links, and statuses — and the run
root is a write-once compiled-snapshot blackboard. Nothing touches raw SQLite —
every mutation goes through Hermes' board APIs (`kanban_*` from workers, `kb.*`
from the host).

## Requirements

- **Hermes Agent v0.15.x**
- **Python ≥ 3.11**
- For any role with `lane: codex`: the `codex` binary on `PATH`, and Hermes'
  **bundled `kanban-codex-lane` skill** present in that role's bound profile.
  This plugin **reuses** that skill — it does **not** re-ship it.

## Quick Install

The intended primary path is PyPI:

```sh
pip install hermes-workflow
```

From source:

```sh
git clone https://github.com/carlosraphael/hermes-workflow
cd hermes-workflow
pip install -e .
```

Then **enable it in EVERY bound profile** — not just the orchestrator's. This is
a pip / entry-point plugin, so `hermes plugins enable` does **not** apply to it
(that command only sees user-dir and bundled plugins). Instead add
`hermes-workflow` to the `plugins.enabled` list in each bound profile's
`config.yaml` — open it with `hermes -p <profile> config edit` (or edit
`<that profile's HERMES_HOME>/config.yaml` directly) and add:

```yaml
plugins:
  enabled:
    - hermes-workflow
```

The change takes effect on the **next session**. (Do **not** use
`hermes config set plugins.enabled …` — it writes a scalar string, which breaks
the loader's list check.)

**Per-profile enablement is the #1 failure mode.** Workers read the plugin's
load status from the *assignee profile's* home, so the plugin must be enabled
**and loadable** in every profile a role binds to. `workflow_start` runs a
per-profile loadability pre-flight and **fails fast — creating zero cards** —
with a per-profile remediation map if any bound profile cannot load it (or a
codex role is missing its `codex` binary / `kanban-codex-lane` skill).

## Quickstart

Using `examples/fix-flaky-tests.workflow.yaml`. There are two surfaces; both take
the same arguments.

In-session slash command:

```
/workflow start --template examples/fix-flaky-tests.workflow.yaml \
  --params '{"repo":"/abs/path/to/repo"}' \
  --bindings '{"scout":"designer","fixer":"coder","reporter":"writer"}'
```

CLI:

```sh
hermes workflow start --template examples/fix-flaky-tests.workflow.yaml \
  --params '{"repo":"/abs/path/to/repo"}' \
  --bindings '{"scout":"designer","fixer":"coder","reporter":"writer"}'
```

### Run lifecycle

1. The `scan` worker (role `scout`) inspects the repo and returns
   `metadata.flaky = [{test_id, file}, …]`.
2. The fan-out hook creates one `fix` card per flaky test — each on its own
   pre-provisioned worktree, gated by commit-clean — and wires the `approve`
   human gate as a child of all of them.
3. Once every `fix` card is `done`, the gate promotes to `ready`.
4. The operator runs `hermes workflow approve <gate_card>`. Find the gate card
   with `hermes workflow status <root_id>` (it is listed under
   `awaiting_approval`).
5. `report` (role `reporter`) then runs, summarizing the fixes from the
   handoffs and listing the branches.

## Commands

Both surfaces — the CLI (`hermes workflow <cmd>`) and the slash command
(`/workflow <cmd>`) — dispatch the same tools (`workflow_start` … `workflow_abandon`).

| Command | Form | What it does |
|---|---|---|
| `start` | `--template <path> --params <json> --bindings <json> [--board]` | Validate, pre-flight every bound profile, then seed the run (root blackboard + dynamic-free prefix). Fails closed with zero cards if any profile can't load. |
| `status` | `<root_id> [--board]` | Read-only run summary: per-stage rollup plus `blocked_stages`, `awaiting_approval` (the gate signal), and `review_required`. |
| `validate` | `--template <path>` | Deterministic, read-only template check. Rejects verify/retry and nested-expand. |
| `reconcile` | `<root_id> [--board]` | Re-drive a partial fan-out: create missing children, re-link to the join, progress-aware dedup, and surface review-required stalls. |
| `approve` | `<gate_card> [--board]` | Complete a human gate card so its downstream stages promote natively. |
| `abandon` | `<root_id> [--board]` | Hazard-free teardown: reclaim running workers, then archive the run reverse-topologically (leaves-first). Worktrees are preserved. |

The four mutating commands (`start`, `reconcile`, `approve`, `abandon`) refuse to
run inside a dispatcher-spawned worker — they are orchestrator-context only.

## Bundled skills

Two skills are auto-registered on plugin load:

- **`workflow-author`** — how to write a `*.workflow.yaml` template within the
  0.1.0 constraints; validate it with `workflow_validate`.
- **`workflow-orchestrator`** — start / status / approve / abandon / reconcile,
  plus the review-required backstop for recovering a stalled stage.

## 0.1.0 scope

Lanes are `{profile, codex}` only — `claude-code` is deferred to 0.2.x.
`verify.command` / `retry` and granular `reject` / `modify` are deferred to
0.2.x. Nested fan-out (an `expand` stage that is itself an `expand` source) is
**forbidden** in 0.1.0.

## Documentation

| Document | What it covers |
|---|---|
| [`AGENTS.md`](AGENTS.md) | Development guide for AI coding assistants and contributors. |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Development setup, PR process, and code style. |
| [`docs/operations.md`](docs/operations.md) | Upgrade / version-gate procedure and operational caveats. |
| [`CONTEXT.md`](CONTEXT.md) | The naming taxonomy (distribution / import / plugin / runtime layers). |
| [`docs/adr/`](docs/adr/) | Architecture decision records. |

## Contributing

Contributions are welcome — see [`CONTRIBUTING.md`](CONTRIBUTING.md) for the
development setup, PR process, and code style.

## License

MIT — Copyright (c) 2026 Carlos Raphael. See [`LICENSE`](LICENSE).
