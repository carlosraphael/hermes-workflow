# hermes-workflow

A declarative, versioned, multi-stage **workflow primitive over the Hermes Kanban
board**. A `*.workflow.yaml` template — params, abstract roles bound to lanes,
stages with `needs`, a single-level `expand` fan-out plus an `expand_out` shape
gate, a human `gate`, and workspaces — is instantiated into a Kanban card-graph
that Hermes' existing dispatcher and worker lanes execute. It turns
"hand-wire an orchestrator from scratch every run" into a repeatable, durable,
inspectable run on the board you already use.

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
root is a write-once compiled-snapshot blackboard. Nothing reaches under the
`kanban_*` API.

## Requirements

- **Hermes Agent v0.15.x**
- **Python ≥ 3.11**
- For any role with `lane: codex`: the `codex` binary on `PATH`, and Hermes'
  **bundled `kanban-codex-lane` skill** present in that role's bound profile.
  This plugin **reuses** that skill — it does **not** re-ship it.

## Install

```sh
pip install hermes-workflow
# or, for development:
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

Other run commands:

- `hermes workflow status <root_id>` — enumerate the run by link-walk from the root.
- `hermes workflow reconcile <root_id>` — re-drive a partial fan-out (create
  missing children, re-link to the join, dedup progress-aware).
- `hermes workflow approve <gate_card>` — promote a human gate.
- `hermes workflow abandon <root_id>` — hazard-free teardown (reclaim workers,
  archive reverse-topologically).
- `hermes workflow validate --template <path>` — deterministic template check.

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

See [`docs/operations.md`](docs/operations.md) for the upgrade / version-gate
procedure and operational caveats.
