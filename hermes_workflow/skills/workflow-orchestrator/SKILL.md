---
name: workflow-orchestrator
description: Drive a hermes-workflow run — start, monitor, approve/abandon, reconcile, and recover a stalled stage.
version: 0.1.0
metadata:
  hermes:
    tags: [workflow, orchestration, kanban]
    requires_tools: [workflow_start, workflow_status]
---

# Driving a hermes-workflow run

This is the operator's loop: start a run from a validated template, monitor it,
resolve the human gate, and recover when a stage stalls. To author or change the
template itself, see the `workflow-author` skill.

## Context rule (read first)

Every **mutating** surface — `workflow_start`, `workflow_reconcile`,
`workflow_approve`, `workflow_abandon` — **refuses inside a dispatcher-spawned
worker**: if `HERMES_KANBAN_TASK` is set it returns an `error` instead of acting.
Run these from an **orchestrator** context, never from inside a worker card.
`workflow_status` and `workflow_validate` are read-only and always safe.

## 1. Kickoff — `workflow_start`

Start a run from a validated template, supplying params and role→profile bindings.

- **Tool args:** `template_text`, `params` (dict), `bindings` (role→profile dict),
  optional `board`.
- **CLI:**
  ```bash
  hermes workflow start --template <path> \
    --bindings '{"scout":"designer","fixer":"coder","reporter":"designer"}' \
    [--params '{"repo":"/r"}'] [--board <name>]
  ```
- **Slash:** `/workflow start ...`

On success returns:

```json
{"root_id": <id>, "board": <name>}
```

On a per-profile pre-flight failure it returns (and creates **zero** cards):

```json
{
  "error": "per-profile pre-flight failed (zero cards created)",
  "profiles": { "<profile>": "<error>" },
  "remediation": { "<profile>": "<hint>" }
}
```

Pre-flight is all-or-nothing — **no cards are created on any failure**. Fix the
profile per the `remediation` (enable the plugin, install `codex`, etc.) and
retry.

## 2. Monitor — `workflow_status`

- **Tool args:** `root_id`, optional `board`.
- **CLI:** `hermes workflow status <root_id>`

Returns:

```json
{
  "root_id": <id>,
  "stages": {
    "<stage_id>": {"state": "<rollup>", "instances": <n>},
    "<other>":    {"state": "pending"}
  },
  "blocked_stages": [...],
  "awaiting_approval": [{"stage": ..., "card": ...}],
  "review_required": [{"stage": ..., "card": ..., "remediation": ...}]
}
```

Not-yet-materialized stages show `{"state": "pending"}`. `awaiting_approval` is
the native "gate parked, waiting for you" signal — that's your cue to approve.

## 3. Resolve the gate — `workflow_approve` / `workflow_abandon`

Complete a human gate so downstream resumes:

```bash
hermes workflow approve <gate_card>     # -> {"approved": <gate_card>}
```

To end a run instead of approving, abandon it. This reclaims-then-archives the
whole run **reverse-topologically**; committed worktree branches are **preserved**
for a fresh relaunch:

```bash
hermes workflow abandon <root_id>
# -> {"abandoned": <root_id>, "orphaned_branches": [...], "failures": [...]}
```

## 4. Stalled / partial run — `workflow_reconcile`

After a crash or a mid-fan-out hook failure, re-run the engine graph from durable
inputs — create-missing (re-linked to the join), progress-aware dedup, and
diagnosis:

```bash
hermes workflow reconcile <root_id>
# -> {
#   "root_id": <id>,
#   "created":   [...],
#   "relinked":  [...],
#   "deduped":   <n>,
#   "diagnosis": {"review_required": [...]}
# }
```

Use it whenever a run looks stuck partway through fan-out.

## 5. Review-required backstop (IMPORTANT)

A coding worker, following the always-on `KANBAN_GUIDANCE` habit, may call
`kanban_block("review-required: …")` on a stage card. That is a **sticky** block
that silently stalls the join — the `kanban_block` tool call itself *succeeded*,
so **no failure badge fires** and nothing looks wrong at a glance.

Both `workflow_status` and `workflow_reconcile` actively detect a sentinel stage
card stuck `blocked` with a worker-initiated review-required block and surface it
in `review_required` with the exact remediation. When you see it, release the
stage:

```bash
hermes kanban unblock <card>
```
