---
name: workflow-orchestrator
description: Drive a Kanban workflow run end to end and recover stalls.
version: 0.1.0
author: "Carlos Raphael"
license: MIT
metadata:
  hermes:
    category: workflow
    tags: [workflow, orchestration, kanban]
---

# Workflow Orchestrator Skill

This is the operator's loop for a `hermes-workflow` run: start it from a
validated template, monitor it, resolve the human gate, and recover when a stage
stalls. It does **not** author or edit the template itself — for that, use the
`workflow-author` skill.

## When to Use

- You have a validated template and want to launch a run (`workflow_start`).
- A run is in flight and you need its per-stage state (`workflow_status`).
- A `gate: human` stage is parked and waiting for your approval.
- A run crashed mid-fan-out and looks stuck partway through (`workflow_reconcile`).
- A stage is silently stalled on a worker-initiated `review-required` block.
- You want to tear a run down (`workflow_abandon`).

## Prerequisites

- Run every **mutating** tool from an **orchestrator** context, never from
  inside a dispatcher-spawned worker. `workflow_start`, `workflow_reconcile`,
  `workflow_approve`, and `workflow_abandon` refuse when `HERMES_KANBAN_TASK` is
  set and return a flat `{"error": ...}` instead of acting. `workflow_status`
  and `workflow_validate` are read-only and always safe.
- Enable `hermes-workflow` in **every bound profile**, not just the
  orchestrator's. This is an entry-point plugin, so add `hermes-workflow` to the
  `plugins.enabled` list in each bound profile's `config.yaml`
  (`hermes -p <profile> config edit`); the change takes effect next session.
- Drain in-flight runs before any `pip install --upgrade hermes-workflow` — the
  0.x line has no cross-version compatibility, and a mid-run upgrade trips the
  schema-version gate and stalls the run.

## How to Run

Each tool has three surfaces: the tool name, the CLI `hermes workflow <verb>`,
and the slash `/workflow <verb>`. All return JSON.

```bash
hermes workflow start --template <path> \
  --bindings '{"architect":"designer","builder":"coder","tester":"designer","reporter":"writer"}' \
  [--params '{"repo":"/r"}'] [--board <name>]
hermes workflow status <root_id> [--board <name>]
hermes workflow approve <gate_card> [--board <name>]
hermes workflow reconcile <root_id> [--board <name>]
hermes workflow abandon <root_id> [--board <name>]
```

## Quick Reference

| Tool | Surface | Purpose |
|---|---|---|
| `workflow_start` | mutating | Validate, pre-flight every profile, seed the run. |
| `workflow_status` | read-only | Per-stage rollup + blocked / awaiting / review-required. |
| `workflow_approve` | mutating | Complete a human gate so downstream resumes. |
| `workflow_reconcile` | mutating | Re-drive the graph: create-missing, re-link, dedup, diagnose. |
| `workflow_abandon` | mutating | Reclaim running workers, then archive the run leaves-first. |

## Procedure

### 1. Kickoff — `workflow_start`

Supply `template_text`, `params`, role→profile `bindings`, and optional `board`.
On success returns `{"root_id": <id>, "board": <name>}`.

Pre-flight is fail-closed and **all-or-nothing**: if any bound profile can't load
the plugin (or a `codex` lane is missing its binary or `kanban-codex-lane`
skill) it creates **zero** cards and returns:

```json
{
  "error": "per-profile pre-flight failed (zero cards created)",
  "profiles": { "<profile>": "<error>" },
  "remediation": { "<profile>": "<hint>" }
}
```

Fix each profile per its `remediation`, then retry.

### 2. Monitor — `workflow_status`

Takes `root_id` and optional `board`. Returns per-stage `stages` (each a
`{"state", "instances"}` rollup, or `{"state": "pending"}` before
materialization), plus `blocked_stages`, `awaiting_approval`, and
`review_required`. `awaiting_approval` is the native "gate parked, waiting for
you" signal — that's your cue to approve.

### 3. Resolve the gate — `workflow_approve`

Complete the human gate card so its downstream stages promote natively:

```bash
hermes workflow approve <gate_card>     # -> {"approved": <gate_card>}
```

### 4. Stalled / partial run — `workflow_reconcile`

After a crash or a mid-fan-out hook failure, re-run the engine graph from durable
inputs — create-missing (re-linked to the join), progress-aware dedup (a running
duplicate is reclaimed before it is archived), and diagnosis. The collapse is
best-effort: a per-op board error lands in `failures` rather than aborting the
pass:

```json
{
  "root_id": <id>,
  "created":   [...],
  "relinked":  [...],
  "deduped":   [...],
  "failures":  [...],
  "diagnosis": {"review_required": [...]}
}
```

### 5. Teardown — `workflow_abandon`

Reclaims/terminates running workers FIRST, then archives every run card and the
root reverse-topologically (leaves-first). Committed worktree branches are
**preserved** for a fresh relaunch:

```bash
hermes workflow abandon <root_id>
# -> {"abandoned": <root_id>, "orphaned_branches": [...], "failures": [...]}
```

Worktrees are not deleted — prune them manually from the `orphaned_branches`
list (`git worktree remove <path>`).

## Pitfalls

- **Review-required backstop (IMPORTANT).** A coding worker following the
  always-on guidance may call `kanban_block("review-required: …")` on a stage
  card. That is a **sticky** block that silently stalls the join — the
  `kanban_block` call itself *succeeded*, so no failure badge fires. Both
  `workflow_status` and `workflow_reconcile` actively detect a sentinel stage
  card stuck `blocked` on a worker-initiated review-required block and surface it
  under `review_required` with the exact remediation. Release the stage with
  `hermes kanban unblock <card>`. This is always a stall to clear — never an
  approval step (the human gate is the only approval mechanism).
- **Mutating tools from a worker context.** They return `{"error": ...}` and do
  nothing. Run them from an orchestrator.
- **Profile-level `worktree:true`.** The engine pre-provisions one worktree per
  fan-out child deterministically; a profile-level `worktree:true` collides and
  double-provisions. Never set it on a profile a workflow role binds to.

## Verification

- `workflow_start` returned `{"root_id", "board"}` — not a `per-profile
  pre-flight failed` error.
- `workflow_status` shows the expected stages advancing; `awaiting_approval`,
  `blocked_stages`, and `review_required` are empty (or each entry is being
  actioned).
- After `workflow_approve`, the gated downstream stage leaves `pending`/`todo`
  on the next `workflow_status`.
- After `workflow_reconcile`, the run is no longer stuck partway through fan-out
  and `diagnosis.review_required` is empty.
- After `workflow_abandon`, `failures` is empty and the run no longer appears on
  the board.
