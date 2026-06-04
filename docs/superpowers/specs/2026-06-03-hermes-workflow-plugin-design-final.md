# hermes-workflow — Design Spec (FINAL, grill-applied & source-cross-checked)

- **Date:** 2026-06-04 (grill decisions applied; cross-checked against source)
- **Status:** Final — planning-ready. Incorporates the 2026-06-04 grill decision record, each item independently cross-checked against the Hermes source.
- **Plugin version target:** `0.1.0` (experimental 0.x line; see §2)
- **Verified against:** Hermes Agent local checkout `/Users/carlos/cortex-workspace/hermes-agent` (v0.15.1, commit `c47b9d12`)
- **Supersedes:** `…-design.md` (original) and `…-design-revised.md` (revised). Consolidates and corrects both, then folds in the grill change-set.

---

## 0. Provenance — how this document was produced

Four source-grounded passes, each against the local checkout (never docs alone):
1. **Original** design, verified A–H.
2. **Revised** design (user grill #1), vetted by a 32-agent workflow: the original was found unbuildable (4 refuted mechanisms); the revised base was adopted with 2 corrections + 5 flaw-fixes (R1–R5) + a scope trim.
3. **Grill decision record** (user grill #2, `2026-06-04-…-grill-decisions.md`): a relentless branch-by-branch interrogation that cut two CRITICALs and shrank the spine.
4. **Cross-check** of that decision record by a 29-agent workflow: every load-bearing claim re-verified; verdict **APPLY all decisions** (0 rejections) with 4 wording modifications, several cite fixes, one partially-refuted sub-claim (B2 "silent"), and 3 grill-missed gaps folded in (a HIGH backstop, a MED worktree-orphan note, a LOW-MED example fix).

**The governing principle** (adopted in the grill): *prefer the deterministic mechanism over an LLM-driven one whenever it is simply doable; choose non-determinism only for a named, source-confirmed gotcha.*

**Two CRITICALs eliminated by this revision:**
- **Shell injection (A1):** a `verify.command` interpolating LLM-emitted `expand` values into `subprocess.Popen([bash,"-c",cmd])` (`tools/environments/local.py`) is arbitrary code execution per fan-out. → `verify.command` + `retry` are **cut to 0.2.x**; the deterministic veto remains, carrying only injection-free checks (`expand_out` shape, commit-clean).
- **Silent mis-drive (B7):** the hook/veto run under the **worker** profile's plugin version, which can differ from the orchestrator's stamped `schema_version`; the hook is fail-open and swallows exceptions, so a version-mismatched gate that *raises* is dropped silently. → a **worker-side, exception-proof version gate** that **visibly refuses** (comment on root + veto block), never raises.

---

## 1. Summary

`hermes-workflow` is a native Hermes Agent plugin that adds a first-class, reusable **workflow primitive** on top of the Kanban board. A *workflow template* is a versioned YAML file describing a multi-stage, multi-role process — stages, dependencies, dynamic fan-out, a human gate, and deterministic completion-gating. Instantiating a template materializes a linked Kanban card-graph that Hermes' existing dispatcher and worker lanes execute.

The plugin ships **tool/CLI/slash surfaces** (`workflow_start` / `status` / `validate` / `reconcile` / `approve` / `abandon`), **hooks** (a `post_tool_call` fan-out reactor and a `pre_tool_call` completion-gate veto), **bundled-skill usage** (author + orchestrator playbooks; the codex lane reuses Hermes' bundled `kanban-codex-lane`), and a **deterministic engine** that holds all logic. It turns "hand-wire an orchestrator from scratch every time" into a repeatable, durable, inspectable run on the board the operator already uses.

## 2. Versioning philosophy

The first release is **`0.1.0`** — experimental 0.x, **no backward-compatibility guarantees** between 0.x versions. **`1.0.0`** is the future stabilization milestone.

**Version gate (makes "never a silent mis-drive" true — B7).** `workflow_start` stamps both the **plugin version** and a `schema_version` in the root provenance and each card sentinel. The plugin declares its supported-`schema_version` set at load. Because the hook and veto execute in the **worker** process under the *worker profile's* `HERMES_HOME` (so a different installed plugin version is possible, e.g. a mid-run `pip --upgrade`):
- the `post_tool_call` hook's self-gate **and** the `pre_tool_call` veto both read the root provenance (`kanban_show`) and check version compatibility;
- on mismatch → **visible refuse, never a raise**: the hook posts a `kanban_comment` on the **root** (cross-task commenting is unrestricted, author forced) and declines to fan out; the veto **blocks** the completion with the mismatch message;
- the version-compare branch must be **total / exception-proof** — both the `pre_tool_call` dispatch (`model_tools.py:939-940` leaves `block_message=None` on error) and the `post_tool_call` path (`:1005`) swallow exceptions, so on its *own* failure the gate must return the block dict, never fall through to `None`/raise (else it fails **open** exactly when versions mismatch).

Operational control remains **drain in-flight runs before upgrading**; the worker-side gate is the safety net.

Terminology: "**0.1.0 scope**" = the first release's spine (§13), not the eventual `1.0.0`. Hermes' own "**v2**" (reserved `workflow_template_id`/`current_step_key` columns) is the *Hermes* roadmap, unrelated.

## 3. Problem & gap

Hermes provides strong multi-agent primitives — a durable Kanban board (state machine + message queue + audit log), worker lanes (assignee → profile, dispatcher-spawned), `kanban_*` tools, and orchestrator/worker behavior taught through *prose skills* re-derived by the LLM each run. What it lacks is a **reusable, declarative workflow object**.

**Prior art / native validation (a variation, not a mirror).** Hermes' own orchestration validates the shape this plugin generalizes: `kanban_swarm` models a join as a **child of the fan-out instances** (`kanban_swarm.py:146-155`, verifier = `create_task(parents=worker_ids)`) and uses a completed root as a **blackboard read/written via structured `[swarm:blackboard]` comments** (`BLACKBOARD_PREFIX`, `latest_blackboard()`); `decompose_triage_task` links the root as a **child of every child** so it auto-promotes back to `ready` (`kanban_db.py:4431-4440`, docstring `:4272-4277`). This design is a **variation** of those idioms — a done-root with a non-spawnable sentinel assignee that is *never* re-promoted, and board-derived state rather than a comment-merged blackboard — not a literal mirror. The community's `tonbistudio/hermes-multi-agent-workflow` writes the board's SQLite schema directly (reaching *under* the API); that's the un-native seam this plugin removes.

## 4. Goals / non-goals

**Goals**
- A declarative, versioned workflow template (YAML) instantiated into a Kanban card-graph.
- Lazy, single-level materialization: a static dynamic-free prefix at start; one declared dynamic fan-out (`expand`) the rest.
- Customizable across domains via abstract roles bound to real profiles, plus a human gate and deterministic (injection-free) completion-gating.
- Strictly native and **deterministic-first**: only public `kanban_*` tools / `ctx.dispatch_tool` / `ctx.register_*` / host-layer `kb.*` (for archive/unlink, which have no model tool); never raw SQLite; never depend on unwired surfaces.
- Community-quality: pip-distributable, integration-tested, documented.

**Non-goals (0.1.0)**
- Multi-host; replacing the dispatcher/claim/breaker machinery (reused); auto-decomposition.
- **Command-based verification** (`verify.command` + `retry`) — cut to 0.2.x for injection-hardening (A1).
- **Nested fan-out** (an `expand` stage that is itself an `expand` source) — forbidden in 0.1.0 (R1).
- **Granular `reject`/`modify`** — deferred to 0.2.x (R3/R4); 0.1.0 offers `approve` + whole-run `abandon`.
- A general "wrap any external CLI" framework — 0.1.0 ships **one** lane adapter, `codex`, reusing the **bundled** `kanban-codex-lane` skill (A3). A `claude-code` lane is deferred.
- Automatic merge/integration of parallel work — the deliverable of a fan-out is N isolated, verified, committed branches; merging is a human post-step or an explicit author-added `integrate` stage.
- Per-role safety/acceptance policy text (deferred).

## 5. Locked design decisions (final)

1. **Core model:** declarative YAML template → Kanban card-graph.
2. **Materialization — lazy, single-level; race-freedom is R5 (atomic create).** `workflow_start` creates the *dynamic-free prefix*. At fan-out, the engine creates each fan-out's children **and its join in a single `kanban_create` carrying the complete parent set** — `create_task` validates parent existence (`_find_missing_parents`, `kanban_db.py:2235-2245`) and computes the new card's status atomically from its parents' **current** statuses (`:2155-2168`), so the join lands the correct status whether 0/some/all children are already done. ("Before any instance completes" is a true side-effect, **not** the mechanism — the mechanism is the single atomic create with the full parent set.) 0.1.0 **forbids an `expand` stage from being an `expand` source** (R1; validation error).
3. **Runtime driver — split authority:**
   - **`post_tool_call` hook = fan-out driver only.** Runs in the completing worker's process; self-gates on our sentinel **and the version check** (§2); uses `ctx.dispatch_tool` to **create + link** the next tail. Never completes/blocks/unblocks a foreign card. Side-effect only; **never raises** (fail-open).
   - **`pre_tool_call` veto = the completion gate.** The only blocking channel: returns `{"action":"block","message":…}` to prevent `kanban_complete`. Deterministic, in-process, exception-proof (§2). Enforces injection-free preconditions (§5.5).
   - **Orchestrator-context CLI/tool (`workflow_*`, no `HERMES_KANBAN_TASK`) = everything else:** seed the root, `approve`/`abandon` the gate, reconcile. Refuse if invoked inside a worker. Archive/unlink run via the **host `kb.*` layer** (no model tool exists — §6/B3).
4. **Linkage & state — the board is the source of truth (deterministic, by choice).** Per-card **body sentinels** (`workflow_root`, `stage_id`, `fan_index`, `attempt`, `template_id+version`, `plugin_version`, `schema_version`) + `task_links` edges + statuses *are* the live state. The **root card body is a write-once, immutable compiled-template snapshot** (template + validated params + role→profile bindings + versions), seeded in orchestrator context, never mutated. The root is a **completed blackboard card** with a **leading-underscore sentinel assignee** (§5.x) so it's never dispatched; it is the permanent link-ancestor for enumeration. *(This is a deliberate choice over the feasible comment-merged manifest, not a forced one.)* The human-decision audit trail uses `kanban_comment` on the gate/root.
5. **Completion-gating (0.1.0 = injection-free only).** The deterministic `pre_tool_call` veto self-selects per stage and enforces, before `kanban_complete`:
   - **`expand_out` shape + `max`** (an `expand`-source stage's emitted `metadata` matches the declared item schema and `len(items) ≤ max`) — a pure data check; its branch must be **total/non-raising** (it is now the sole pre-fan-out data gate, A1/gap #4);
   - **commit-clean** (a worktree stage's tree is committed: a fixed `git -C <engine-derived-path> status`, no untrusted interpolation).
   Failures feed back as the tool result for an in-run fix-and-recomplete in the **normal** agent loop (no `goal_mode`). **`verify.command` + `retry` are cut to 0.2.x** (A1) and **rejected at `workflow_start`** with a "0.2.x" fail-fast. There is no `verifier` profile/lane/card. The veto keeps a small fixed self-timeout as hygiene (commit-clean's git call is fast/bounded).
6. **Gate (0.1.0 = `approve` + `abandon`).** A `gate: human` stage is a non-spawnable card (leading-underscore sentinel assignee → `skipped_nonspawnable`; §5.x). Resolution is orchestrator-context CLI:
   - **`approve`** = complete the gate (orchestrator may complete any card; native fan-in promotes downstream).
   - **`abandon`** = end the whole run, hazard-free: (1) **reclaim/terminate every running run-card first** (`archive_task` does *not* kill workers — `kanban_db.py:4486`; use `reclaim_task`/`_terminate_reclaimed_worker`), (2) `kanban_comment` an audit on the root **that enumerates orphaned worktree branches via the still-live sentinel link-walk** (so the operator can salvage; archive preserves all non-scratch worktrees with no GC — gap #2), (3) archive in **reverse-topological order (children strictly before parents)** so `recompute_ready` never transiently promotes an interior real-assignee stage to `ready`, (4) relaunch fresh only after the sweep confirms no run-card remains in `running`/`ready`/`todo`/`blocked`.
   - Granular `reject`/`modify` → 0.2.x engine commands (R3/R4-hardened). The R3/R4 hazards are *not* relocated onto a manual runbook (the grill removed that).
7. **Reconcile — primary = re-run-graph + create-missing; secondary = dedup.** The fail-open hook's real crash mode is **partial fan-out** (some children never created). Reconcile (manual orchestrator CLI, authoritative) **re-runs the engine graph function from the durable inputs** — source handoff on `task_runs.metadata` (never time-GC'd, §6/D1) + the root snapshot — and **creates the missing cards, re-linking each created child to its join** (`kanban_link(child→join)`; `link_tasks` demotes a `ready` join back to `todo`, claim re-checks — so a late edge is safe). `attempt` is **stable across reconcile** (first materialization = 0, never bumped) so create-missing is idempotent by sentinel identity. **Dedup (secondary)** resolves genuine concurrent duplicates: winner = any `done` duplicate (multi-`done` tiebreak: `task_runs.id` → `created_at` → `min(card_id)`); **re-wire = `kb.link_tasks(winner→join)` then `kb.archive_task(loser)`** (two ordered steps — there is no `kanban_unlink` and `link`/`archive` cannot share one transaction; the archived loser is a *satisfied* parent so its dangling edge is harmless). A discarded `done` duplicate **orphans its branch/worktree** (audit it). Exactly-once is **"converges to once under repeated reconcile,"** not a hard guarantee (the read-then-create shares the native key's out-of-txn race). The per-child sentinel `idempotency_key` is a cheap sequential dedup only.
8. **Non-spawnable sentinel — leading underscore (collision-proof).** Every non-worked card (root, gate) uses a **leading-underscore assignee** (e.g. `_workflow_gate`, `_workflow_root`). `validate_profile_name`'s regex `^[a-z0-9][a-z0-9_-]{0,63}$` (`profiles.py:35`) forbids a leading underscore, so Hermes can *never* create a colliding profile; `profile_exists` returns `False` (never raises) → the card is reliably `skipped_nonspawnable`. **Never leave such a card unassigned** (a board `default_assignee` would auto-assign and spawn it — `kanban_db.py:5921-5963`). **`skipped_nonspawnable` is NOT silent** (B2 correction): a non-empty-assignee card stranded in `ready` past ~30 min raises an escalating `stranded_in_ready` diagnostic surfaced as a dashboard badge each `get_board()` and printed each dispatcher tick (`plugin_api.py:437,462-468`). So the gate must **not** be parked indefinitely in `ready` assuming silence — hold a `claim_lock` on it or raise its `stranded_threshold`, OR treat the badge as the (acceptable) native "awaiting approval" signal. Either way, **`workflow_status` is the primary gate signal.**
9. **Board scoping:** active board by default; `--board` for opt-in isolation. One run is wholly within one board.
10. **Audience:** polished, pip-distributable community plugin.

## 6. Feasibility findings (verified against source)

| # | Mechanism | Verdict | Consequence |
|---|---|---|---|
| A | `post_tool_call` fires after `kanban_complete` | **GO** | In-process, incl. failed completes; read handoff from `args`, not `result`; callback **must** accept `**kwargs`. Return ignored; exceptions swallowed (`:1005`) ⇒ fan-out gate is a side-effect, never a raise. |
| B | Hook `ctx.dispatch_tool("kanban_create"/"kanban_link")` | **GO** | No `check_fn` gate on dispatch; create/link worker-allowed, sync, no recursion. `kanban_link` ungated. |
| C | Workers read `plugins.enabled` from the **assignee** profile's home | **GO (#1 silent-failure)** | `HERMES_HOME = resolve_profile_env(assignee)` (`:6468`). Plugin must be enabled **and loadable** in every bound profile; version can differ (→ §2 gate). |
| D | `kanban_create` id/parents/idempotency; complete envelope | **ADJUST** | Returns `{task_id,status}`; `parents`+`idempotency_key`; **no `metadata` column on `tasks`** (handoff on `task_runs.metadata`); idempotency racy/out-of-txn (`:1648`,`:2106-2119`). |
| E | LLM-free **verifier lane** via `ctx.*` | **REFUTED** | No spawn_fn/lane registrar. → `pre_tool_call` veto. |
| F | Stage metadata to hook + child `worker_context` | **GO** | Hook reads `args.metadata`; child sees each **direct done parent's** last completed-run summary+metadata; **skips non-done parents**. |
| G | Reserved cols writable publicly | **REFUTED** | No production writer. Use root provenance. |
| H | Gates via fan-in | **ADJUST** | `recompute_ready`: child→`ready` when `all(parents ∈ {done,archived})` (`:2858-2908`). Worker can't `unblock` (orchestrator-only); `block` ownership-scoped. `unblock_task` gates on `!= done` (does NOT treat `archived` as satisfying — avoid relying on archive to release a *blocked* child). |
| I | Worker can complete/block a **foreign** card | **REFUTED** | `_enforce_worker_task_ownership` rejects foreign complete/block (`:132-161`). → hook only create/link. |
| J | Native **rollup** (parent auto-completes from children) | **REFUTED** | `done` written only by `complete_task`, gated on the task's own id (`:3576-3605`). → join is a **child**, created already-wired (R5). |
| K | Worker reads a foreign card | **GO** | `kanban_show` worker-allowed, ungated, returns body+parents+children. |
| L | Worker enumerates board (`kanban_list`) | **REFUTED for workers** | Orchestrator-only; no body (`:309-332`). → hook link-walks; CLI uses `kanban_list` for board-wide sweeps. |
| M | `recompute_ready` vs late edges | **GO** | Own txn after status commit; re-reads current parents; never demotes a non-`todo` card; `claim_task` re-checks. → late `link(child→join)` in reconcile is safe. |
| N | Non-worked **barrier/blackboard** card | **GO (with telemetry)** | label/`_`-prefixed assignee → `skipped_nonspawnable` (`:5978-5986`). **But** a non-empty assignee stranded in `ready` raises `stranded_in_ready` badges (`plugin_api.py:437,462-468`) — not silent (B2). |
| O | `pre_tool_call` blocks `kanban_complete` + feeds back | **GO** | Returns `{"action":"block","message":…}`; not dispatched; card stays `running`; message surfaced; loop continues. Synchronous, fail-open, **no per-hook timeout** → self-time. |
| P | Non-completing run → escalation | **GO** | **Clean exit (rc=0) without `kanban_complete` = `protocol_violation`, trips on the FIRST occurrence** (`failure_limit=1`, `:5427`), emits `gave_up` (recoverable); other failures default limit 2 (`:4692`). goal_mode budget exhaustion → `block_task` → sticky `blocked`. Distinguish by **event kind**, not status. Caveat: per-task `max_retries>1` delays the trip; a reap-registry miss degrades to the default-2 crash path. |
| Q | Worktrees auto-provisioned; preserved | **ADJUST** | Hermes does **not** create worktrees (`resolve_workspace` returns the path, `:4565/4615-4625`); completion preserves `worktree`/`dir` (only `scratch` deleted, `:3766-3783`); no auto-commit/merge. Separate `-w`/`worktree:true` auto-worktree exists (`cli.py:1142`) but kanban workers aren't spawned with `-w` — **worker profiles must not set `worktree:true`** or it collides. → **engine pre-provisions**; veto enforces commit. |
| R | `build_worker_context` fan-in scaling | **GO** | All done direct parents, **no count cap**, ~4 KB/field (~8 KB/parent; the 8 KB body cap is this task's own body) (`:6789-6825`). → plugin owns width-limiting (B5 `expand_out.max`); reconcile reads the **unbounded `task_runs.metadata` column** directly, not the 4 KB-truncated context. |
| S | Reopen a `done` card | **ADJUST** | Only via dashboard HTTP (`_set_status_direct`, `:971`); tool/CLI terminal. → `modify` (0.2.x) = fresh cards. `link` re-close (`ready→todo`) verified (`:2371-2379`). |
| T | Per-profile enablement; `enabled ≠ loaded` | **GO** | `plugins list` is **config-only** (`:806`); load truth in `LoadedPlugin.enabled/.error` (`plugins.py:278-279`), only visible **in-process** under that profile's home (`list_plugins():1574-1593`). → spawned loadability probe (§9). |
| U | Native Claude Code **lane** | **REFUTED** | Only `kanban-codex-lane` bundled. → `claude-code` lane is a real port, **deferred to 0.2.x**. |
| V | `verify.command` shell-exec | **CONFIRMED (the A1 CRITICAL)** | Shell strings run via `Popen([bash,"-c",cmd])` (`tools/environments/local.py`), no escaping; interpolating untrusted `expand` values = RCE. → cut to 0.2.x. `expand_out`/commit-clean carry no untrusted interpolation. |
| W | `task_runs` GC | **CONFIRMED (D1)** | **No `gc_runs`**; `task_runs` persist until hard-delete (`:4532/4555`). Only `task_events` (done/archived tasks) + worker logs are 30-day GC'd (`:7191-7229`). |
| X | `card.skills` force-load | **GO for bundled** | The `card.skills → --skills` plumbing is shared by all dispatch (review path proves the plumbing via `sdlc-review`, `:6088-6139`); **`kanban-codex-lane` is bundled and resolves by bare name** (`skills_tool.py:957-961`). Forced `card.skills` are **not** resolvability-gated (only `kanban-worker` is, `:6546`) — the worker's home must contain **exactly one** resolvable copy: a missing OR duplicate copy makes worker startup fatal (`cli.py:15549`). **Do not re-ship the skill.** Plugin-namespaced skills remain unproven → **Spike 3 (0.2.x), only for the claude-code lane.** |
| Y | `kanban_unlink` / `kanban_archive` model tools | **REFUTED** | Neither exists (9 kanban tools; `tools/kanban_tools.py:1352-1424`). Edge-removal/archive only via `kb.unlink_tasks`/`kb.archive_task` / CLI (`:2409`, `:4486`). → plugin does dedup link+archive via the **host layer**, not the worker/orchestrator tool surface. |
| Z | Review-required block habit | **CONFIRMED (B6)** | The "block instead of complete" habit is in the **always-on** `KANBAN_GUIDANCE` system preamble (`prompt_builder.py:206-219`), gated only on `HERMES_KANBAN_TASK` — a stage can't dodge it by skipping the skill. A stage that blocks creates a **sticky** block (`_has_sticky_block`; `unblock` orchestrator-only) that **silently stalls the join**. → body preamble **+ a real backstop** (§11). `status='review'` is never set by a worker tool (only dashboard/sdlc) ⇒ review-column collision is **low-risk**. |

**Design rules that follow directly**
- Hook callback: `def on_tool_done(tool_name, args, result, task_id, **kwargs)` — `**kwargs` mandatory; **side-effect only, never raises**.
- Self-gate hard: act only when `tool_name == "kanban_complete"` ∧ `result` has no `error` ∧ our sentinel ∧ **version compatible** (§2).
- Hook powers = create + link only. `approve`/`abandon`/reconcile/dedup-archive are orchestrator-context, and **archive/unlink go through `kb.*`** (no model tool).
- Read provenance via `kanban_show(root).body`; enumerate via link-walk from the root.
- Set **explicit** `board` + `workspace_kind`/`workspace_path` on every hook-issued create (an omitted workspace **inherits the source worker's** — `kanban_tools.py:788`).
- Per-profile **loadability** pre-flighted at `workflow_start` (§9), fail-fast with remediation.

## 7. The workflow template (DSL)

A YAML file (`<name>.workflow.yaml`), discovered from the project dir or `~/.hermes/workflows/`, **snapshotted into the root provenance at start**. Worked example (every 0.1.0 feature):

```yaml
# fix-flaky-tests.workflow.yaml
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
    expand_out: { key: flaky, max: 50, item: { test_id: string, file: string } }  # shape + width, veto-enforced

  - id: fix
    role: fixer
    needs: [scan]
    expand: { over: scan.flaky, as: t }   # single-level fan-out: 1 card per flaky test
    title: "Fix flaky test ${t.test_id}"
    body:  "Fix ${t.test_id} in ${t.file}. Keep the change minimal. Commit before completing."
    workspace: "worktree:${params.repo}"  # engine pre-provisions; card becomes dir:<provisioned-path>
    # commit-clean veto is automatic for worktree stages (no untrusted interpolation)

  - id: approve
    needs: [fix]                          # join: a CHILD of every fix card; waits for ALL
    gate:  human                          # non-spawnable; resolve via `hermes workflow approve|abandon`

  - id: report
    role: reporter
    needs: [approve, fix]                 # approve = ordering; fix = data (handoffs from all fix cards)
    title: "Summarize the fixes"
    body:  "Summarize all fixes from the parent handoffs and list the branches."
```

**Field reference (0.1.0)**

| Field | Meaning |
|---|---|
| `params` | Typed inputs; validated before any card is created. |
| `roles.<name>.lane` | `profile` or `codex` (reuses bundled `kanban-codex-lane`; the engine sets `card.skills=["kanban-codex-lane"]` and pre-provisions the worktree). Bound to a concrete profile at start. |
| `stages[].role` | Abstract role; must appear in `roles`. Omitted for a pure `gate`. |
| `stages[].needs` | On a post-fan-out stage, wires a direct parent edge from **every** instance (ordering + native handoff). List a gate **and** a data-stage for pre-gate data (`needs: [approve, fix]`). |
| `stages[].expand` | `{ over: <stage>.<key>, as: <var> }`. **An `expand` stage may not itself be an `expand` source (R1).** |
| `stages[].expand_out` | On an `expand` source: `{ key, item, max }` — the veto enforces shape + `max` (default ~50) before completion (the sole pre-fan-out data gate; bounds fan-in context, hook cost, worktree sprawl). |
| `stages[].gate: human` | Non-spawnable card; resolved by `hermes workflow approve|abandon`. |
| `stages[].workspace` | `scratch` / `dir:<path>` / `worktree:<path>`. A `worktree:` is **engine-pre-provisioned** and the card is handed a `dir:<provisioned-path>`; worktree stages also get the commit-clean veto. Worktree/data stages must not use `scratch`. **Only `${params.*}` allowed in `workspace:` paths** (expand-vars forbidden — the per-child path is engine-derived; params are `normpath`'d + containment-checked, strengthening Hermes' `is_absolute()`-only defense). |

**Deferred to 0.2.x:** `verify: { command, retry }` — command-based verification (injection-hardening required, A1); rejected at `workflow_start` in 0.1.0.

**"Templating is bounded" = safety + scope.** Only `${params.*}` and `${<expand-var>.*}` interpolate, and `${<expand-var>.*}` may appear **only in `title`/`body`** (never in a command or path). All other cross-stage data flows through native `worker_context`.

## 8. Workflow ↔ Kanban relationship

A layer that authors/advances a card-graph; Kanban executes. A run = a completed root blackboard card + its connected subgraph, identified by sentinel.

| Workflow concept | Kanban reality |
|---|---|
| Template | board-agnostic YAML; snapshotted into the root |
| Run | completed root blackboard card + subgraph |
| Stage | a card (or N when fanned out) |
| `needs` | `task_links` parent→child (to every instance when fanned out) |
| Role | assignee (bound profile) + lane (skill + binary) |
| Join / barrier | a **child** of all fan-out instances (never an auto-completing parent) |
| Gate | a non-spawnable `_`-sentinel card, resolved by CLI |
| Completion gate | a `pre_tool_call` veto (no card) |
| Handoff | native `worker_context` (each direct done parent's summary + metadata) |
| Provenance | write-once snapshot in the root body; live state from the board |
| Execution | the unchanged kanban dispatcher |

**Cardinality:** many runs per board; one run wholly within one board. Concurrent runs share the board's dispatch budget.

## 9. Runtime model & data flow

1. **`workflow_start(template, params, bindings, board?)`** *(orchestrator context — refuses inside a worker)*: load + snapshot YAML; reject `verify.command`/`retry` (0.2.x); validate `params`; resolve roles → profiles (fail fast on missing); **pre-flight per-profile loadability** — for each *distinct* bound profile, **spawn a probe** that runs `discover_plugins()` under that profile's `HERMES_HOME` (passed explicitly; set `HERMES_ENABLE_PROJECT_PLUGINS=1` if shipped as a project plugin) and reports `hermes-workflow`'s `LoadedPlugin.enabled/.error` (codex profiles also confirm the bundled lane skill resolves + the `codex` binary). Remediation derived from the probe: not-enabled → `plugins enable`; enabled-but-`.error` → surface the load error. **Zero cards created on any failure.** Then create the **root blackboard card** (compiled snapshot; `_`-sentinel assignee; completed) and the **dynamic-free prefix** via `kanban_create(parents=…)`.
2. **Static prefix** runs on native parent-gating.
3. **`post_tool_call` hook** (in the completing worker): self-gate (sentinel + version §2); read `args.metadata`; opportunistic local link-walk dedup; via `ctx.dispatch_tool` **create + link** the next tail — fan-out children **and** their join in one atomic create carrying all instances (R5), plus the gate/report tail — with **explicit board + workspace** on every create. Side-effect only; never raises; on version mismatch posts a root comment and declines.
4. **`pre_tool_call` veto** (in the stage worker): exception-proof; enforces `expand_out` shape+`max` and commit-clean; failures feed back for an in-loop fix-and-recomplete.
5. **Gate** is a non-spawnable card. **`approve`** completes it (orchestrator CLI). **`abandon`** reclaim-then-archives the whole run reverse-topologically with an orphaned-branch audit (§5.6). The decision lives on the card.
6. **Crash / partial fan-out** → Hermes' breaker + the **manual `workflow_reconcile`**: re-run-graph + create-missing (re-linked to the join) + progress-aware dedup (§5.7), reading durable inputs (`task_runs.metadata` + root snapshot). Reconcile also **diagnoses**: "stage `done`, downstream absent ⇒ probable plugin-not-enabled in that profile" (a *probable* hint; the repair is cause-agnostic). It additionally surfaces **stages stuck `blocked` via a worker-initiated review-required** block (§11 backstop) and stages repeatedly tripping `protocol_violation` (§11).
7. **Body lifecycle preamble (B6).** The engine **prepends a workflow-stage lifecycle preamble to every stage card's body**: "complete via `kanban_complete` (even a no-op stage must complete with empty/sentinel metadata); emit declared metadata; commit before completing; **do not `kanban_block` for review** — the workflow's gate handles that." Using the **body** (not a new plugin skill) keeps 0.1.0 Spike-3-free. This counters the always-on `KANBAN_GUIDANCE` habit but is **not sufficient alone** — see the §11 backstop.

## 10. Component architecture

Fat engine / thin shell.

```
hermes-workflow/
├── plugin.yaml                 # name, version: 0.1.0, provides_tools, provides_hooks: [post_tool_call, pre_tool_call]
├── __init__.py                 # register(ctx): tools + CLI + slash + hooks + bundled skills
├── engine/                     # PURE, deterministic, no board/LLM — the unit-tested core
│   ├── template.py             #   parse/validate YAML, params, roles, cycle detection, expand_out schema, nested-expand prohibition, verify-rejection
│   ├── graph.py                #   "completed stages + metadata → cards that should exist up to the next boundary" (drives both fan-out and reconcile)
│   ├── provenance.py           #   root compiled-snapshot read + body sentinels (write-once) + version compatibility check
│   ├── reconcile.py            #   re-run-graph + create-missing(+re-link join) + progress-aware dedup; identity = root+stage+fan_index+attempt
│   └── interpolate.py          #   ${params.*} (title/body/workspace) / ${expand-var.*} (title/body only)
├── tools.py                    # thin shell: workflow_start / status / validate / reconcile / approve / abandon (orchestrator-context-only mutators)
├── hooks.py                    # post_tool_call (fan-out create+link, side-effect, version-gated) + pre_tool_call (completion-gate veto, exception-proof)
├── lanes/
│   └── presets.py              #   codex preset (card.skills=["kanban-codex-lane"] against the BUNDLED skill + binary + permission policy); documents the lane contract
└── skills/
    ├── workflow-author/SKILL.md
    └── workflow-orchestrator/SKILL.md   # kickoff, status, approve, abandon, reconcile
# NOTE: the codex lane skill is NOT re-shipped — it reuses Hermes' bundled kanban-codex-lane (exactly one resolvable copy; re-shipping makes worker startup fatal, finding X).
```

**Surfaces:** `workflow_*` tool, `hermes workflow …` CLI, `/workflow` slash. All *mutating* surfaces are orchestrator-context-only (refuse if `HERMES_KANBAN_TASK` set); `workflow_status` enumerates a run by **link-walk from the root** (`kanban_show` → body+children+sentinels; O(N) shows, fine on-demand — `kanban_list` returns no body and no run-filter, so it's for board-wide sweeps/reconcile, not run enumeration). Registered via `ctx.register_tool/register_cli_command/register_command/register_hook/register_skill`. Archive/unlink use `kb.*` (no model tool — finding Y). The codex "lane" is a normal LLM worker that **drives `codex` as a subprocess and then completes** — codex never touches the board.

## 11. Error handling & edge cases

- **Fail-open hook → reconcile (§5.7):** primary = re-run-graph + create-missing (re-linked to join); secondary = progress-aware dedup; "converges to once." The hook never raises; it is a pure side-effect.
- **Version gate (§2):** exception-proof, visible-refuse (root comment + veto block), never a raise — both hook and pre_tool_call swallow exceptions, so the gate must fail *closed* by returning the block dict.
- **Completion veto:** must return `{"action":"block","message":…}` (not a bare string), accept `**kwargs`, self-timeout under the 15-min claim TTL, and its `expand_out` shape-check branch must be **total/non-raising** (it's the sole pre-fan-out data gate, gap #4).
- **Every dispatched stage worker MUST `kanban_complete`** — even a no-op stage (empty/sentinel metadata). A clean rc=0 exit while `running` is a `protocol_violation` that trips the breaker on the **first** occurrence (`gave_up`, recoverable; can re-spawn into a no-op loop until `consecutive_failures` pins it). The body preamble states this; reconcile flags repeated `protocol_violation` as operator-actionable.
- **Review-required backstop (HIGH, gap #1):** the always-on `KANBAN_GUIDANCE` teaches coding workers to `kanban_block("review-required: …")`. A stage that does so creates a **sticky** block (auto-recovery refused; `unblock` orchestrator-only) that **silently stalls the join** (the tool call *succeeded* — no `gave_up`). The body preamble counters it but isn't sufficient. Backstop: **`workflow_status` and `reconcile` actively detect a sentinel stage card in `blocked` whose most-recent block event is worker-initiated `review-required`, surface it distinctly, and emit the remediation (`hermes kanban unblock <id>`).** (Intercepting `kanban_block` in the veto to convert this silent stall into a loud error is a candidate 0.2.x hardening.)
- **Fail-fast at `workflow_start`:** unknown profile; not enabled/loaded (per-profile probe); missing lane skill / `codex` binary; `verify`/worktree stage on `scratch`; nested `expand` (R1); a `verify.command`/`retry` block (0.2.x); invalid params.
- **Sentinel parking (§5.x):** leading-underscore assignee (collision-proof) + always assigned (no `default_assignee` hijack). `skipped_nonspawnable` is **not silent** — a gate left in `ready` raises `stranded_in_ready` badges; hold a `claim_lock`/raise the threshold, or accept the badge as the native "awaiting approval" signal; `workflow_status` is primary.
- **Gate `abandon` (§5.6):** reclaim/terminate workers first; reverse-topological archive; audit-enumerate orphaned worktree branches before archiving (preserved, no GC — gap #2).
- **Empty fan-out** (`expand` over `[]`): create no children; wire the join to the **source** via `kanban_create(parents=[source])` (never create-then-link); the gate opens trivially.
- **Worktree isolation** is engine-pre-provisioned (deterministic), idempotent (reuse-if-exists; survives hook-refire/reconcile), base-ref pinned in provenance, provision-then-create per child (a failed provision ⇒ missing card → reconcile, never a card pointing at a missing worktree), tolerant of `git index.lock` (brief retry). **Worker profiles must not set `worktree:true`** (collides with the engine worktree — finding Q). Cleanup is operator work.
- **Durability (D1):** durable state lives in the **`tasks` row** (body/status), persisting until hard-delete; **`task_runs.metadata` also persists indefinitely** (no time-GC); only `task_events` (done/archived tasks) and worker logs are 30-day GC'd (`kanban_db.py:7191-7229`; no `gc_runs`). Reconcile reads the unbounded `task_runs.metadata` column directly.
- **Dispatch budget (D4):** a wide fan-out bound to one profile serializes at that profile's concurrency cap (fine, bounded by `expand_out.max`) but can starve co-resident runs sharing it; mitigations: the `max` cap, `--board` isolation, a dedicated fan-out profile. (Review-status dispatch bypasses the per-profile cap, but workflow stages never use `review` status.)
- **Body is Markdown** (dashboard escapes HTML + whitelists link schemes — no XSS; cosmetic escaping deferred).

## 12. Testing strategy (integration-first)

**Integration tests are the default; unit tests only where logic carries real weight; no LLM in either.**

- **Unit — pure `engine/`:** template parse/validate (expand_out schema, nested-expand prohibition, `verify`-rejection, cycle detection), the graph function (drives fan-out **and** reconcile), interpolation (incl. workspace `${params.*}`-only + containment), provenance read + sentinel + **version-compatibility check (total, never raises)**, reconcile (re-run-graph create-missing **+ re-link to join**, stable `attempt`, progress-aware multi-`done` winner), empty-fan-out edges.
- **Integration — wired to real Hermes, zero LLM:** real board + plugin load + `kanban_*`; "worker" steps via `kanban_complete` with canned metadata. Assert: `workflow_start` materializes the prefix + seeds the done-root + **per-profile probe fails fast on a disabled/unloadable profile**; the hook fans out with the join wired to all instances (R5) and is **version-gated** (mismatch → root comment, no fan-out); the veto blocks on a bad `expand_out` shape/over-`max`/uncommitted tree and passes otherwise, and **its shape-check never raises**; a gate-less data consumer does **not** promote until its parent is `done`; the `approve` gate completes → promotes; **`abandon` reclaims-then-archives reverse-topologically and leaves no spawnable card**; **reconcile create-missing re-links to the join and the progress-aware winner prefers the `done` duplicate**; the **review-required backstop** detects a sentinel stage stuck `blocked` and emits remediation.
- **Lane smoke test (one live run):** the codex lane drives `codex -p …` in a pre-provisioned worktree → completes with lane metadata. Out of CI.

## 13. 0.1.0 scope (spine) vs deferred

**0.1.0 spine:** template DSL (`params`, `roles`/lanes `{profile, codex}`, `needs`, single-level `expand`, `expand_out` shape+`max`, `gate`); `workflow_start`/`status`/`validate`/`reconcile`/`approve`/`abandon` as tool + CLI + `/workflow`; `post_tool_call` fan-out (version-gated, side-effect) + `pre_tool_call` completion-gate veto (commit-clean + `expand_out`, exception-proof, self-timeout); lazy single-level creation with race-free join wiring (R5) and **nested-expand forbidden** (R1); root-blackboard provenance + body sentinels + **worker-side version gate**; leading-underscore non-spawnable sentinel; reconcile = re-run-graph + create-missing(+re-link) + progress-aware dedup; engine-pre-provisioned worktrees + commit-clean; per-profile **loadability** pre-flight; body lifecycle preamble + **review-required backstop**; **one** bundled `codex` lane (no re-ship); `workflow-author` + `workflow-orchestrator` skills; 1–2 example templates (incl. `build-hermes-plugin` with an author-level `integrate` stage); pip packaging; integration-first tests.

**Deferred → 0.2.x:** `verify.command` + `retry` (injection-hardened: value-charset validation + `shlex`/argv) and the verify-timeout/`goal_mode` wiring; granular `reject`/`modify` engine commands (R3/R4-hardened); the `claude-code` lane (+ **Spike 3**: plugin-namespaced skill force-load); a bundled `workflow-stage` skill (replacing the body preamble); intercepting `kanban_block` to harden the review backstop; an automatic/tick-scheduled reconciler; the fan-in aggregator; nested fan-out; `fanout: N`; per-role safety policy text; automatic merge; dashboard chrome; conditional branching/loops; additional lanes; multi-host; reserved-column mirroring.

## 14. Open questions & de-risking spikes

- **Spike 1 (veto path):** a `pre_tool_call` runs commit-clean + an `expand_out` shape check, self-times, and returns `{"action":"block",…}`; confirm it prevents `kanban_complete`, leaves the card `running`, surfaces the message for an in-loop retry, and that its branch never raises (fails closed).
- **Spike 2 (per-profile landmine):** plugin enabled only in root; dispatch to another profile; confirm the hook does **not** fire; enable there; confirm it does; confirm the `workflow_start` loadability probe catches the missing/`.error` case.
- **Spike 4 (race + reconcile):** materialize an N-way fan-out + join in one atomic create; assert the join is wired to all N and promotes once when the last completes; kill the hook mid-fire; assert `workflow_reconcile` recreates the missing children **and re-links them to the join**; assert empty-fan-out source-rewire.
- **Spike 5 (version gate):** stamp plugin/`schema_version`; simulate a worker profile on an unsupported version; confirm the hook posts a root comment + declines and the veto blocks — neither raises.
- **Spike 6 (abandon):** confirm reclaim-then-archive terminates running workers, archives reverse-topologically with no transient `ready` promotion, and the audit enumerates orphaned branches.
- **Closed:** review-column collision (low-risk — workflow stages never enter `review` status, never get `sdlc-review`). **Moved to 0.2.x:** Spike 3 (plugin-namespaced skill force-load + `on_session_start` worker-self-provisioning) — gates the claude-code lane only.
- **Open:** confirm hook-created cards don't trip `created_cards`/`HallucinatedCardsError` (the hook calls `kanban_create` directly — verify in Spike 1).

## 15. Worked UX example — build a new Hermes plugin

Two human touchpoints: launch, and answer one gate.

**Template** (`build-hermes-plugin.workflow.yaml`): `spec` (architect; `expand_out` = list of tools, shape+`max`) → `implement` (builder via the codex lane, fanned out one card per tool, each on a pre-provisioned worktree, **each gated by commit-clean**) → **`integrate`** (collect the per-tool branches into one plugin — an explicit author-added stage; deliverable is one plugin) → `test` (tester; the worker runs the suite itself and commits — **commit-clean** confirms it; the human gate reviews) → `review` (human gate) → `enable` (reporter).

**Launch:**
```
/workflow start build-hermes-plugin \
  --param plugin_name=rss_reader --param purpose="fetch and parse RSS feeds" \
  --bind architect=designer, builder=coder, tester=qa, reporter=writer
```
The engine validates, binds roles → profiles, **probes each profile's plugin loadability** (and the builder profile's bundled codex lane skill + `codex` binary), seeds the done-root blackboard, and creates the `spec` card.

**Autonomous execution:** `spec` returns `metadata.tools=[…]` (shape+`max` checked by the veto); the hook (version-gated) fans `implement` into one card per tool — each pre-provisioned a worktree, each gated by commit-clean — and wires the `integrate` join to **all** implement cards in one atomic create; native fan-in holds `integrate` until every implement card is `done`; `integrate` collects the branches; `test` runs and commits (commit-clean confirms); `review` parks as a non-spawnable gate.

**Answer the gate:** `hermes workflow approve t_review` → downstream resumes; `enable` finishes; the done-root holds the audit trail. `workflow_status t_root` shows the stage rollup (board + snapshot, incl. not-yet-materialized stages as "pending", and any stage stuck `blocked`); `workflow_reconcile t_root` re-drives a partial fan-out; `hermes workflow abandon t_root` ends and audits the run (preserving committed branches) for a fresh relaunch.

**The 0.1.0 deterministic gates are `expand_out` (shape+width) and commit-clean** — both injection-free. Command-based verification (an import-check or `pytest` gate) is **0.2.x** (it requires running untrusted-influenced shell strings, hardened first). The workflow's *workers* are real LLM agents (incl. the codex lane doing real coding); only the completion gate is deterministic. The "no-LLM" rule applies to the plugin's *test suite*, not the workflows it runs.

## 16. References

- Hermes local checkout: `/Users/carlos/cortex-workspace/hermes-agent` (v0.15.1, `c47b9d12`).
- Key source: `model_tools.py` (hook dispatch, `pre_tool_call` block `:928-943`, swallow `:1005`/`:939-940`), `tools/registry.py` (`dispatch`), `tools/kanban_tools.py` (`_handle_create/_complete/_block/_show/_link`, `_enforce_worker_task_ownership:132-161`, workspace inherit `:788`, 9-tool surface `:1352-1424`, cross-task comment `:705-707`), `hermes_cli/kanban_db.py` (`create_task` atomic+parent-existence `:2155-2168/2235-2245`, `recompute_ready:2858-2908`, `complete_task:3576-3605`, `link_tasks:2356-2383`, `unlink_tasks:2409`, `archive_task:4486-4509`, `resolve_workspace:4565/4615-4625`, `_cleanup_workspace:3766-3783`, `build_worker_context:6789-6825`, `decompose_triage_task:4272-4277/4431-4440`, `_default_spawn`+`HERMES_HOME:6452/6468`, `skipped_nonspawnable:5978-5986`, `default_assignee:5921-5963`, `protocol_violation:5347-5427`, `DEFAULT_FAILURE_LIMIT:4692`, blocked-vs-gave_up `:2786-2822`, GC `:7191-7229`, hard-delete `:4532/4555`, review-dispatch `card.skills` `:6088-6139`), `hermes_cli/kanban_swarm.py` (blackboard via comments, join-as-child `:146-155/243-264`), `hermes_cli/plugins.py` (`LoadedPlugin.enabled/.error:278-279`, `list_plugins:1574-1593`, `register_hook` warns-not-rejects `:935-949`, `VALID_HOOKS`+`on_session_start:140`, project-plugin env `:1085`), `hermes_cli/plugins_cmd.py` (config-only `list:806`), `hermes_cli/profiles.py` (regex `:35`, `profile_exists:307-312`), `agent/prompt_builder.py` (always-on review-block habit `:206-219`), `skills/skills_tool.py` (bare-name resolution `:957-961`), `cli.py` (forced-skill fatal `:15549`, separate `-w` worktree `:1142`), `plugins/kanban/dashboard/plugin_api.py` (`_set_status_direct:971`, `stranded_in_ready` badge `:437/462-468`), `tools/environments/local.py` (`Popen([bash,-c,cmd])`), bundled `skills/autonomous-ai-agents/kanban-codex-lane/`, `skills/devops/kanban-worker/SKILL.md:50`.
- Abandoned upstream lane feature: issue #19931, PR #19924 (closed) — no public custom-lane registrar.
- Prior art: Hermes' `kanban_swarm`/`decompose_triage_task`; `tonbistudio/hermes-multi-agent-workflow` (the un-native seam removed).
- Vetting provenance: original A–H verification → 32-agent revised-vs-original vetting → 29-agent grill-decision cross-check (verdict: apply all, 0 rejections, with the wording fixes and 3 grill-missed gaps folded in here).
```
