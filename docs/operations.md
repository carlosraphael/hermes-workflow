# hermes-workflow — Operations

Operator guide for running, upgrading, and recovering `hermes-workflow` runs.
Accurate to the design spec §2 (versioning) and §11 (error handling & edge cases).

## Upgrading: drain before upgrade

The 0.x line has **no backward-compatibility guarantees** between versions.

**Operational rule: drain all in-flight runs before upgrading the plugin in any
profile.** Let active runs reach a terminal state (or `abandon` them) before you
`pip install --upgrade hermes-workflow` anywhere.

### Why draining is required — the worker-side version gate

`workflow_start` stamps both the **plugin version** and a `schema_version` into
the run root provenance and into every card sentinel. The `post_tool_call`
fan-out hook and the `pre_tool_call` completion veto both run **worker-side,
under the worker profile's `HERMES_HOME`**. That means a mid-run
`pip install --upgrade` in a worker profile can change the installed version a
worker loads — diverging it from the `schema_version` stamped at start.

On a `schema_version` mismatch the gate performs a **visible refuse — never a
raise**:

- the fan-out hook posts a `kanban_comment` on the run root and **declines to
  fan out**;
- the completion veto **blocks** the completion with the mismatch message.

The gate is the safety net: it guarantees there is never a silent mis-drive. But
a mismatch will **STALL the run** — the fan-out never happens and completions are
blocked. That is exactly why you **drain first**: the gate protects correctness,
draining protects progress.

## Operational caveats

### 1. Per-profile enablement is the #1 failure mode

Enable `hermes-workflow` in **every bound profile**, not just the orchestrator's.
This is a pip / entry-point plugin, so `hermes plugins enable` does **not** apply
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

Workers load the plugin from the **assignee profile's home**, so each role's
bound profile must have it enabled and loadable. `workflow_start` runs a
per-profile loadability pre-flight and **fails fast (creates zero cards)** with a
per-profile remediation map identifying which profiles cannot load it — or which
codex role is missing its `codex` binary or `kanban-codex-lane` skill.

### 2. Gate `stranded_in_ready` is expected and benign

A `gate: human` card parked in `ready` will raise Hermes' native
`stranded_in_ready` badge/diagnostic after roughly 30 minutes. **This is the
native "awaiting approval" signal, not an error.**

`workflow_status` is the **primary gate signal** — it lists the gate card under
`awaiting_approval`. Resolve the gate with:

```sh
hermes workflow approve <gate_card>
```

### 3. Worktrees are PRESERVED on abandon — prune manually

`hermes workflow abandon <root_id>` is hazard-free teardown:

1. reclaims / terminates any running workers;
2. audit-enumerates orphaned worktree branches in a comment on the run root
   **before** archiving;
3. archives the run reverse-topologically.

It does **not** delete worktrees. Archive preserves all non-scratch
workspaces, and there is no garbage collection. The operator prunes manually:

```sh
git worktree remove <path>   # per orphaned worktree
git worktree prune           # clean up stale administrative refs
```

Consult the orphaned-branch list in the root comment to know what to remove.

### 4. Worker profiles must NOT set `worktree:true`

The engine pre-provisions one worktree per fan-out child **deterministically**.
A profile-level `worktree:true` collides with that (Hermes finding Q) and
**double-provisions** the workspace. Leave worktree provisioning to the engine —
do not set `worktree:true` on any profile a workflow role binds to.

## Stage protocol: every worker must `kanban_complete`

Every dispatched stage worker **MUST** call `kanban_complete` — even a no-op
stage, which completes with empty/sentinel metadata. A clean `rc=0` exit while
the card is still `running` is a `protocol_violation` that trips the breaker on
the first occurrence. The body preamble states this requirement, and `reconcile`
flags repeated `protocol_violation` as operator-actionable.

## Review-required backstop

Hermes' always-on coding-worker guidance teaches workers to call
`kanban_block("review-required: …")`. When a workflow stage does this it creates
a **sticky** block (auto-recovery is refused; `unblock` is orchestrator-only)
that **silently stalls the join** — the `kanban_block` tool call *succeeded*, so
there is no `gave_up` signal to surface it.

The backstop: `workflow_status` and `reconcile` actively detect a sentinel stage
card stuck in `blocked` whose most-recent block event is a worker-initiated
`review-required`, surface it distinctly, and emit the remediation:

```sh
hermes kanban unblock <id>
```

Note: the workflow's **own human gate** (`gate: human`, resolved via
`hermes workflow approve`) is the approval mechanism — **not** a worker block.
A `review-required` block is always a stall to clear, never an approval step.
