---
name: workflow-author
description: Write a *.workflow.yaml template for hermes-workflow — params, roles/lanes, stages, needs, expand/expand_out, gate, and workspace — within the 0.1.0 constraints, validated with workflow_validate.
version: 0.1.0
metadata:
  hermes:
    tags: [workflow, authoring, templates]
    requires_tools: [workflow_validate]
---

# Authoring a `*.workflow.yaml`

A workflow template is a declarative DAG of stages over Hermes Kanban. You write
it once; `workflow_start` validates it deterministically, binds abstract roles to
concrete profiles, and seeds the run. This is the reference for the template
shape and the 0.1.0 rules the validator enforces.

## 1. Top-level shape

```yaml
name: fix-flaky-tests          # template name
version: 0.1.0                 # TEMPLATE version (independent of the plugin version)
description: Find flaky tests, fix each in isolation, gate, then report.
params: { ... }                # typed inputs
roles: { ... }                 # abstract roles -> lanes
stages: [ ... ]                # the DAG
```

`version` is the template's own version and has nothing to do with the plugin's
`PLUGIN_VERSION`. Pick whatever scheme you like for it.

## 2. `params` — typed inputs

```yaml
params:
  repo:    { type: string, required: true }
  pattern: { type: string, required: false, default: "test_*.py" }
```

Each param is `{ type: string, required: true|false, default: ... }`. Params are
validated deterministically at `workflow_start` **before any card is created** —
a missing required param fails the whole start with zero side effects.

## 3. `roles` — abstract roles bound to lanes

```yaml
roles:
  scout:   { lane: profile }
  fixer:   { lane: codex }
  reporter:{ lane: profile }
```

A role names a lane:

- **`profile`** — a plain LLM worker on the bound profile.
- **`codex`** — an LLM worker that drives the `codex` binary as an isolated
  implementation lane. It reuses Hermes' **BUNDLED `kanban-codex-lane` skill**:
  the engine sets `card.skills = ["kanban-codex-lane"]` and pre-provisions the
  worktree for that stage. This plugin does not re-ship the skill.
- **`claude-code`** — a 0.2.x lane; **not available in 0.1.0**.

Roles are abstract. You bind each to a concrete profile at start as a JSON
dict — `--bindings '{"scout":"designer","fixer":"coder"}'` on the CLI (the
`bindings` arg to `workflow_start`). See the `workflow-orchestrator` skill for
launching a validated template.

## 4. `stages[]`

Each stage is a node in the DAG:

```yaml
stages:
  - id: scan          # unique stage id
    role: scout       # abstract role; omit ONLY for a pure gate stage
    title: "Scan ${params.repo}"
    body: "List flaky tests under ${params.pattern}."
    needs: []         # parent stage ids
    expand: { ... }       # fan-out (see §5)
    expand_out: { ... }   # fan-out source contract (see §6)
    gate: human           # human gate (see §7)
    workspace: scratch    # workspace (see §8)
```

A **gate stage must not declare a role**; every **non-gate stage must declare a
role**.

## 5. `needs` — parent edges

`needs` lists parent stage ids. Wiring rules:

- On a **post-fan-out stage**, listing a fanned-out stage wires a direct edge
  from **every** instance of that stage (ordering + native handoff of each
  instance's output).
- To get **both** pre-gate data **and** ordering, list **both** the gate and the
  data stage, e.g. `needs: [approve, fix]` — `approve` orders the stage after the
  human gate, `fix` hands it the per-instance fix data.

## 6. `expand` — single-level fan-out

```yaml
expand: { over: scan.flaky, as: item }
```

`{ over: <stage>.<key>, as: <var> }` produces one card per item emitted by the
source stage. The `<key>` (`flaky`) must match the source stage's
`expand_out.key`. Inside the fanned-out stage, `${item.*}` refers to the current
item — **usable only in `title`/`body`** (never in a path or command).

## 7. `expand_out` — the fan-out source contract

On the fan-out **source** stage:

```yaml
expand_out:
  key: flaky
  item: { path: string, name: string }
  max: 50
```

`{ key, item: {<field>: <type>}, max }`. Before the source stage may complete,
the **completion veto** enforces the item **shape** (every emitted item has the
declared fields/types) and the `max` width (default `50`). This is the sole
pre-fan-out data gate — it bounds fan-in context and worktree sprawl.

## 8. `gate: human`

```yaml
- id: approve
  title: "Approve fixes"
  gate: human
  needs: [fix]
```

A `gate: human` stage is a **non-spawnable** card a human resolves via
`hermes workflow approve <gate_card>` (or `abandon`). It declares no role.

## 9. `workspace`

`workspace` is one of:

- **`scratch`** — ephemeral scratch space.
- **`dir:<path>`** — a fixed directory.
- **`worktree:<path>`** — engine-pre-provisioned git worktree. The card is handed
  a `dir:<provisioned-path>`; worktree stages also get the automatic
  **commit-clean veto** (the stage may not complete with a dirty tree).

Fan-out / data stages must **not** use `scratch`.

## 10. 0.1.0 constraints (the validator REJECTS these)

- **No `verify: { command, retry }`** — deferred to 0.2.x.
- **No nested expand** — an `expand` stage may not itself be an `expand` source.
- In `workspace:` paths, **only `${params.*}` tokens** are allowed. Expand-vars
  are forbidden in paths (the per-child path is engine-derived).
- Fan-out / data stages must **not** use `scratch`.
- `${<expand-var>.*}` may appear **only** in `title`/`body`, never in a path or a
  command.
- No duplicate stage ids.
- No dependency cycles.
- `needs` / `expand.over` must reference **known** stages.
- A **gate** stage must not declare a role; a **non-gate** stage must declare a
  role.

## 11. Worked example — scan → fix → approve → report

```yaml
name: fix-flaky-tests
version: 0.1.0
description: Find flaky tests, fix each in isolation, gate, then report.
params:
  repo: { type: string, required: true }
roles:
  scout:    { lane: profile }
  fixer:    { lane: codex }
  reporter: { lane: profile }
stages:
  - id: scan
    role: scout
    title: "Scan ${params.repo} for flaky tests"
    body: "Identify flaky tests and emit them as the `flaky` list."
    workspace: dir:${params.repo}
    expand_out:
      key: flaky
      item: { path: string, name: string }
      max: 50

  - id: fix
    role: fixer
    title: "Fix ${item.name}"
    body: "Repair the flaky test at ${item.path} in an isolated worktree."
    needs: [scan]
    expand: { over: scan.flaky, as: item }
    workspace: worktree:${params.repo}

  - id: approve
    title: "Approve the fixes"
    gate: human
    needs: [fix]

  - id: report
    role: reporter
    title: "Summarize the run"
    body: "Write a summary of every fix that landed."
    needs: [approve, fix]
    workspace: dir:${params.repo}
```

## 12. Validate before launching

Before launching, always validate:

- **Tool:** `workflow_validate`
- **CLI:** `hermes workflow validate --template <path>`
- **Slash:** `/workflow validate --template <path>`

It returns `{ok: true}` or `{ok: false, error: <message>}`. Fix the reported
error and re-validate until it returns `{ok: true}`.
