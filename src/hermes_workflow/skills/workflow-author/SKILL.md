---
name: workflow-author
description: Write a validated multi-stage workflow template.
version: 0.1.0
author: "Carlos Raphael"
license: MIT
metadata:
  hermes:
    category: workflow
    tags: [workflow, authoring, templates]
---

# Workflow Author Skill

Authors a `*.workflow.yaml` template — a declarative DAG of stages over the
Hermes Kanban board, with typed params, abstract roles, single-level fan-out,
human gates, and per-stage workspaces. It covers the template shape and the
0.1.0 rules the validator enforces; it does **not** launch runs, bind roles to
profiles, or recover stalled stages — see the `workflow-orchestrator` skill for
that.

## When to Use

- Writing a new `*.workflow.yaml` from scratch.
- Editing an existing template's params, roles, stages, fan-out, or gates.
- Diagnosing why `workflow_validate` rejected a template.

## Prerequisites

- The `hermes-workflow` plugin is enabled for the profile you author under (add
  it to that profile's `config.yaml` `plugins.enabled` list).
- The `workflow_validate` tool is available — it is the deterministic gatekeeper
  you run after every edit (see `## Verification`).

## How to Run

1. Write the template to a `*.workflow.yaml` file.
2. Validate it with `workflow_validate` (or `hermes workflow validate
   --template <path>`).
3. Fix the first reported error and re-validate until it returns `{ok: true}`.
4. Hand the validated path to the `workflow-orchestrator` skill to start a run.

## Quick Reference

| Key | Where | Meaning |
|---|---|---|
| `name`, `version`, `description` | top level | `version` is the template's own; unrelated to the plugin version |
| `params` | top level | `{ type, required, default }` — typed inputs |
| `roles` | top level | abstract role → `{ lane: profile \| codex }` |
| `stages[]` | top level | DAG nodes; each has a unique `id` |
| `role` | stage | required on every non-gate stage; forbidden on a gate stage |
| `needs` | stage | parent stage ids (ordering + handoff) |
| `expand` | stage | `{ over: <stage>.<key>, as: <var> }` — fan-out |
| `expand_out` | stage | `{ key, item: {<f>: <type>}, max }` — fan-out source contract |
| `gate: human` | stage | non-spawnable card a human resolves |
| `workspace` | stage | `scratch` \| `dir:<path>` \| `worktree:<path>` |

## Procedure

**1. Top-level shape.** `name`, `version` (the template's own — independent of
`PLUGIN_VERSION`), `description`, then `params`, `roles`, `stages`.

**2. `params` — typed inputs.** Each is `{ type, required, default }`. Params are
validated at `workflow_start` **before any card is created**; a missing required
param fails the whole start with zero side effects.

**3. `roles` — abstract roles bound to lanes.** A role names a lane:
- **`profile`** — a plain LLM worker on the bound profile.
- **`codex`** — an LLM worker driving the `codex` binary as an isolated lane. The
  engine sets the bundled `kanban-codex-lane` skill on the card; this plugin does
  not re-ship the skill. (Worktree isolation is a separate, stage-level choice —
  declared via the stage's `workspace`, not implied by the lane.)

Roles are abstract; you bind each to a concrete profile at start (the
orchestrator's job, not the author's).

**4. `stages[]` — DAG nodes.** Each stage has a unique `id`. A **gate stage must
not declare a role**; every **non-gate stage must declare a role**.

**5. `needs` — parent edges.** Lists parent stage ids. On a post-fan-out stage,
listing a fanned-out stage wires an edge from **every** instance of it. To get
both pre-gate ordering **and** per-instance data, list **both** the gate and the
data stage, e.g. `needs: [approve, fix]`.

**6. `expand` — single-level fan-out.** `{ over: <stage>.<key>, as: <var> }`
produces one card per item the source stage emits. The `<key>` must match the
source's `expand_out.key`. Inside the fanned-out stage, `${<var>.*}` is the
current item — usable **only in `title`/`body`**, never in a path or command.

**7. `expand_out` — the fan-out source contract.** On the source stage:
`{ key, item: {<field>: <type>}, max }`. Before the source may complete, the
completion veto enforces the item **shape** and the `max` width (default `50`) —
the sole pre-fan-out data gate, bounding fan-in context and worktree sprawl.

**8. `gate: human`.** A non-spawnable card a human resolves via `hermes workflow
approve <gate_card>` (or `abandon`). It declares no role.

**9. `workspace`.** One of `scratch` (ephemeral), `dir:<path>` (fixed directory),
or `worktree:<path>` (engine-pre-provisioned git worktree; the card is handed a
`dir:<provisioned-path>` and gets the automatic commit-clean veto). Fan-out
stages must **not** use `scratch`.

**Worked example — scan → fix → approve → report** (mirrors
`examples/fix-flaky-tests.workflow.yaml`):

```yaml
name: fix-flaky-tests
version: 0.1.0                            # template version — independent of plugin version
description: Find flaky tests, fix each in isolation (committed), gate, report.

params:                                   # validated deterministically at start
  repo: { type: string, required: true }

roles:                                    # abstract roles → bound to profiles at start
  scout:    { lane: profile }
  fixer:    { lane: codex }               # reuses Hermes' bundled kanban-codex-lane skill
  reporter: { lane: profile }

stages:
  - id: scan
    role: scout
    title: "Scan ${params.repo} for flaky tests"
    body: |
      Identify flaky tests. Return metadata.flaky as a list of
      {test_id, file}. Do not fix anything.
    workspace: "dir:${params.repo}"
    expand_out: { key: flaky, max: 50, item: { test_id: string, file: string } }

  - id: fix
    role: fixer
    needs: [scan]
    expand: { over: scan.flaky, as: t }   # single-level fan-out: 1 card per flaky test
    title: "Fix flaky test ${t.test_id}"
    body:  "Fix ${t.test_id} in ${t.file}. Keep the change minimal. Commit before completing."
    workspace: "worktree:${params.repo}"  # engine pre-provisions; card becomes dir:<provisioned-path>

  - id: approve
    needs: [fix]                          # join: a CHILD of every fix card; waits for ALL
    gate:  human                          # non-spawnable; resolve via `hermes workflow approve|abandon`

  - id: report
    role: reporter
    needs: [approve, fix]                 # approve = ordering; fix = data (handoffs from all fix cards)
    title: "Summarize the fixes"
    body:  "Summarize all fixes from the parent handoffs and list the branches."
```

## Pitfalls

The validator REJECTS these in 0.1.0:

- **`verify: { command, retry }`** — deferred to 0.2.x.
- **Nested expand** — an `expand` stage may not itself be an `expand` source.
- **Non-`${params.*}` tokens in `workspace:` paths** — expand-vars are forbidden
  in paths (the per-child path is engine-derived).
- **`${<expand-var>.*}` outside `title`/`body`** — never in a path or command.
- **`scratch` on a fan-out stage.**
- **Duplicate stage ids** or **dependency cycles.**
- **`needs` / `expand.over` referencing an unknown stage**, or `expand.over`'s
  key not matching the source `expand_out.key`.
- **A `gate` value other than `human`**; a gate stage that declares a role; a
  non-gate stage that omits one.

Note: the `claude-code` lane is a 0.2.x feature and is **not available in
0.1.0** — only `profile` and `codex`.

## Verification

Always validate before handing the template off:

- **Tool:** `workflow_validate` (read-only; safe in any context).
- **CLI:** `hermes workflow validate --template <path>`
- **Slash:** `/workflow validate --template <path>`

It returns `{ok: true}` or `{ok: false, error: <message>}` reporting the first
failure. Fix the reported error and re-validate until it returns `{ok: true}`.
