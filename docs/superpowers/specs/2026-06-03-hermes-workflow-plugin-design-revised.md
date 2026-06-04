# hermes-workflow — Design Spec (Revised post-grill)

- **Date:** 2026-06-03 (revised after a source-grounded design grill, Q1–Q13)
- **Status:** ⚠️ SUPERSEDED by `2026-06-03-hermes-workflow-plugin-design-final.md`. This revision was vetted (32-agent source-verification) and adopted as the base for the final spec, with corrections (Q4 framing overstated; Finding-R byte math), five flaw-fixes (R1 nested-expand, R2 reconcile keep-winner, R3 modify ordering, R4 reject DAG-guard, R5 atomic create-with-parents), and a scope trim to a 0.1.0 spine. Kept for history; plan from the final spec.
- **Plugin version target:** `0.1.0` (experimental 0.x line; see Versioning)
- **Verified against:** Hermes Agent local checkout `/Users/carlos/cortex-workspace/hermes-agent` (v0.15.1, commit `c47b9d12`)
- **Supersedes:** `2026-06-03-hermes-workflow-plugin-design.md`. This revision keeps that document's goals and structure but replaces several load-bearing mechanisms that adversarial source verification refuted or reshaped.

---

## 0. What changed from the original, and why

Every change below is forced by a verified fact about Hermes v0.15.1 (see §6) and is governed by one principle adopted during the grill: **prefer the deterministic mechanism over an LLM-driven one whenever it is simply doable; choose non-determinism only for a named gotcha.**

| # | Original design said | Revised design | Forcing fact |
|---|---|---|---|
| Q1 | Static graph created at start; engine only touches dynamic moments | **Lazy creation**: only the dynamic-free prefix is created at start; the whole post-`expand` tail is engine-materialized, with joins created *already wired to all fan-out instances* | `recompute_ready` runs *inside* `kanban_complete`, **before** the `post_tool_call` hook — so a join wired after a parent completes races and can be claimed early |
| Q2 | Verification = a real `verifier` **profile worker** ("LLM-free in substance") | Verification = a deterministic **`pre_tool_call` veto** in the stage's own worker; **no verifier lane/card** | Every spawned worker is an LLM `hermes chat`; there is no non-LLM lane registrar. The veto is the only genuinely LLM-free gate |
| Q3 | `retry: N` re-creates the stage card | `retry: N` = a **goal_mode turn budget**; veto enforces pass/fail; budget exhaustion → goal_mode sticky-block → human gate | `goal_mode` natively self-blocks on budget exhaustion (clean human-review handoff) |
| Q4 | JSON **manifest** on the root card, updated by the hook | Root body = **write-once compiled-template snapshot**; the **board is the source of truth**; no mutable hook-updated manifest | A worker can't mutate a foreign card's body (ownership wall); a shared mutable body races (lost updates) |
| Q5 | `expand` reads `metadata`; malformed → flag in manifest | `expand` source stage has a **declared output shape**, veto-enforced | The completing stage is already `done` by the time the hook runs — can't be re-blocked; enforce *before* completion |
| Q6 | Gate via `kanban_block`, resume by `unblock` | Gate = **non-spawnable `ready` card**; `approve` = complete it, `reject` = **archive the whole downstream subtree** | The in-worker hook can't `block`/`unblock` a foreign gate card; `archived` is a *satisfied* parent (so archiving only the gate would promote its children) |
| Q7 | `modify` deferred | **`modify` in 0.1.0** = redo-with-feedback via *fresh cards*, **re-wired into every consumer of the superseded card**, which is **archived** (still auditable) | `done` is terminal on tool/CLI surfaces; `kanban_link` re-close/re-open cycle works; `build_worker_context` skips non-`done` parents (so the archived original drops out of downstream handoffs) |
| Q8 | "the plugin self-checks at startup" | **Orchestrator-side pre-flight** at `workflow_start` (a disabled plugin can't self-check) | Per-profile opt-in is *required*; `pip install` only discovers; root enablement doesn't propagate |
| Q9 | `worktree:` workspaces, verifier card shares them | **Engine pre-provisions worktrees**; commit contract veto-enforced; **integration not in engine core** | Hermes does *not* auto-create worktrees (LLM does); completion preserves them; no native merge |
| Q11 | "data flows through native parent-handoff" | A fan-in consumer must be a **direct child of all fan-out instances**; `report needs [approve, fix]` | `worker_context` surfaces *direct* parents only (but all of them, uncapped) |
| Q12/Q13 | lanes `{profile, codex, verifier}`; one Codex adapter | lanes `{profile, codex, claude-code}`; **two built lanes** | No verifier lane exists; Hermes ships no claude-code lane (low-delta to add) |

---

## 1. Summary

`hermes-workflow` is a native Hermes Agent plugin that adds a first-class, reusable **workflow primitive** on top of the Kanban board. A *workflow template* is a versioned YAML file describing a multi-stage, multi-role process — stages, dependencies, dynamic fan-out, human gates, and verification. Instantiating a template materializes a linked Kanban card-graph that Hermes' existing dispatcher and worker lanes execute.

The plugin ships **tools/CLI/slash surfaces** (`workflow_start` / `status` / `validate` / `reconcile` / `approve` / `reject` / `modify`), **hooks** (a `post_tool_call` *fan-out* reactor and a `pre_tool_call` *completion-gate* veto), **bundled skills** (author + orchestrator playbooks, plus two lane skills), and a **deterministic engine** that does all the logic.

The primitive turns "hand-wire an orchestrator from scratch every time" into a repeatable, durable, inspectable run on the board the operator already uses.

## 2. Versioning philosophy

The first release is **`0.1.0`**. The whole `0.x` line is explicitly experimental: **no backward-compatibility guarantees** between `0.x` versions — template schema, manifest/provenance format, tool signatures, and hook behavior may all change freely. **`1.0.0`** is the future stabilization milestone.

In-flight runs across an upgrade: every run stamps a `schema_version` (in the root provenance and each card sentinel). The engine **refuses to drive a run whose `schema_version` it does not support** (a loud error, never a silent mis-drive). Operational guidance: **drain in-flight runs before upgrading the plugin.**

Terminology, to avoid collisions:
- "**0.1.0 scope**" = the feature set of the first release (§13). It is *not* the eventual `1.0.0`.
- Hermes' own "**v2**" (the reserved `workflow_template_id` / `current_step_key` columns) refers to the *Hermes* roadmap and is unrelated to this plugin.

## 3. Problem & gap

Hermes provides strong multi-agent primitives — a durable Kanban board (state machine + message queue + audit log), worker lanes (assignee → profile, dispatcher-spawned), `kanban_*` tools, and orchestrator/worker behavior taught through *prose skills* re-derived by the LLM each run. What it lacks is a **reusable, declarative workflow object**: a repeatable process definition customizable per domain and instantiated on demand.

**Prior art / validation.** Hermes' *own* internal multi-agent orchestration — `kanban_swarm` and `kanban_decompose` — is built on exactly the primitive this plugin generalizes: a declarative graph materialized as native parent/child fan-in, with a completed **root card as a shared blackboard**, explicit completion, and no auto-rollup. This design deliberately mirrors those native idioms (see §6). The community's `tonbistudio/hermes-multi-agent-workflow` is the closest external solution, but it writes the board's SQLite schema directly — reaching *under* Hermes' API rather than *through* it. That direct-schema coupling is the "un-native" seam this plugin removes.

## 4. Goals / non-goals

**Goals**
- A declarative, versioned workflow template (YAML) that instantiates into a Kanban card-graph.
- Hybrid materialization: static dynamic-free prefix at start, declared dynamic fan-out (`expand`) the rest.
- Customizable across domains via abstract roles bound to real profiles, plus per-stage gates and deterministic verification.
- Strictly native: only public `kanban_*` tools / `ctx.dispatch_tool` / `ctx.register_*`; never raw SQLite; never depend on unwired Hermes surfaces.
- Community-quality: pip-distributable, integration-tested, documented, with example templates.

**Non-goals (0.1.0)**
- Multi-host coordination (Hermes is single-host).
- Replacing the dispatcher / claim / reclaim / circuit-breaker machinery (reused as-is).
- Auto-decomposition / auto-assignment (that is Hermes' LLM decomposer).
- Per-role safety/acceptance policy text (deferred).
- **A general "wrap any external CLI" framework.** 0.1.0 ships **two built lane adapters** — `codex` and `claude-code` — as instances of a bounded lane contract (skill + binary + permission policy), which doubles as the worked extension example. Additional CLIs are a documented, config-shaped extension, not a framework.
- **Automatic integration/merge of parallel work.** The deliverable of a fan-out is N isolated, verified, committed branches; merging is a human post-step or an explicit author-added integration stage.

## 5. Locked design decisions (revised)

1. **Core model:** declarative YAML template → instantiated as a Kanban card-graph.
2. **Materialization (Q1):** **lazy creation.** `workflow_start` creates only the *dynamic-free prefix* (the cards before the first `expand`). Everything downstream is materialized by the engine at fan-out time, and **every join is created already wired to all its fan-out instances, before any of them can complete** (race-free).
3. **Runtime driver (Q1/Q2/Q4):** an event-hook + fat-engine architecture, with a clean split of authority:
   - **`post_tool_call` hook = the fan-out driver only.** It runs *in the completing worker's process*, self-gates on our sentinel, and uses `ctx.dispatch_tool` to **create + link new cards** (the only mutations a worker is allowed on foreign structure). It never completes, blocks, or unblocks a foreign card.
   - **`pre_tool_call` hook = the completion-gate veto.** Deterministic, in-process, gates `kanban_complete` on per-stage preconditions (§5.5).
   - **Orchestrator-context CLI/tool (`workflow_*`, no `HERMES_KANBAN_TASK`) = everything else:** seed the root, open/resolve gates, complete structural barriers, reconcile. These ops *require* orchestrator context and refuse if invoked from inside a worker.
4. **Linkage & state (Q4):** **the board is the source of truth.** Per-card **body sentinels** (minimal pointers: `workflow_root`, `stage_id`, `fan_index`, `attempt`, `template_id+version`, `schema_version`) + `task_links` edges + statuses *are* the live state. The **root card body is a write-once, immutable compiled-template snapshot** (template + validated params + role→profile bindings + schema version), seeded by `workflow_start` in orchestrator context and never mutated. There is **no mutable, hook-updated manifest**. The root is a **completed "blackboard" card** (native swarm idiom), with a reserved **label assignee** so the dispatcher never spawns it; it is the permanent link-ancestor used to enumerate the run.
5. **Verification (Q2/Q3/Q5/Q9):** a deterministic **`pre_tool_call` veto** in the stage's own worker. It self-selects per stage and can enforce, before `kanban_complete`:
   - **verify command** (`verify.command` → exit 0),
   - **expand output shape** (an `expand`-source stage's emitted `metadata` matches the declared item schema),
   - **commit-clean** (a worktree stage's tree is committed on its branch).
   On failure it returns `{"action":"block","message": …}`, which becomes the tool result; the worker sees it and retries in-run. `retry: N` is realized as a **goal_mode turn budget**; budget exhaustion → goal_mode's native sticky-block → the human-gate resolution path. There is **no `verifier` profile/lane/card**.
6. **Gates (Q6):** a `gate: human` stage is a **non-spawnable `ready` card** (label assignee → silently parked). Resolution happens in orchestrator context via the `hermes workflow` CLI: **`approve`** = complete the gate (native fan-in promotes downstream); **`reject`** = archive the gate **and its entire downstream subtree** (because `archived` is a satisfied parent, archiving only the gate would wrongly promote its children); **`modify`** = §5.7. The decision lives on the gate card (status + comment).
7. **Modify (Q7) — bounded human-driven loop, in 0.1.0:** redo-with-feedback via **fresh replacement cards** (`done` is terminal on tool/CLI surfaces, so no reopen). Each replacement gets a **bumped `idempotency_key`**, a distinct `attempt` marker in its sentinel, the human feedback **injected into its body**, and a pre-provisioned worktree. The engine then **re-wires the replacement into *every* former consumer of the superseded card** — found by link-walking the superseded card's children (e.g. the `approve` gate **and** the `report` consumer), not just the gate — so each downstream stage depends on, and reads the handoff of, the redo rather than the discarded original. Linking the incomplete replacement to the parked `ready` gate re-closes it (`ready → todo`); when the redo passes, the gate re-opens for another review. The superseded original is **archived** — it stays fully auditable (`archive` ≠ delete; its card and run history persist), and, crucially, **`build_worker_context` skips non-`done` parents**, so the archived original drops out of every consumer's handoffs while the replacement appears (deterministic, no LLM dedup); an archived card is a *satisfied* parent, so nothing deadlocks. Reconcile is unaffected (the replacement's distinct `attempt` is a different identity). Default granularity per-**stage**, optional per-**card**.
8. **Reconcile (Q10):** at-least-once + reconcile. The `idempotency_key = hash(root + stage_id + fan_index + attempt)` makes the *sequential* case idempotent (re-create dedups to the existing card). Duplicates can only arise under genuine concurrency; reconcile resolves them deterministically: **keep `min(card_id)` per sentinel identity, archive the losers and their subtrees** — a pure function of immutable id, so concurrent reconciles converge with no locks. Hook does **local** reconcile (link-walk neighborhood); the `workflow_reconcile` CLI does the **global** sweep and is the backstop for crash/timeout and totally-failed fan-outs. Best-effort convergence (a rare race may waste a little work before the loser is archived).
9. **Board scoping:** materialize on the **active board** by default; `--board` opts into a dedicated/isolated board. A single run is always wholly within one board.
10. **Audience:** polished, pip-distributable community plugin.

## 6. Feasibility findings (verified against source)

All load-bearing assumptions were verified against the local Hermes checkout (v0.15.1, `c47b9d12`) across several adversarial passes. The original A–H findings held; the revision adds the findings that reshaped the design.

| # | Mechanism | Verdict | Consequence |
|---|---|---|---|
| A | `post_tool_call` fires after `kanban_complete` | **GO** | Fires unconditionally in-process (incl. failed completes); read the handoff from `args`, not `result`. Callback **must** accept `**kwargs` incl. `duration_ms` or it silently `TypeError`s. |
| B | Hook calls `ctx.dispatch_tool("kanban_create"/"kanban_link")` | **GO** | `registry.dispatch` has no `check_fn` gate; create/link are worker-allowed, sync, no hook recursion. `kanban_link` has **no ownership guard at all**. |
| C | Workers read `plugins.enabled` from the **assignee profile's** home | **GO (the #1 silent-failure mode)** | Dispatcher sets `HERMES_HOME = resolve_profile_env(assignee)`. Plugin must be enabled in **every** bound profile. |
| D | `kanban_create` id/parents/idempotency; `kanban_complete` envelope | **ADJUST** | Returns `{task_id,status}`; accepts `parents`+`idempotency_key`; **no `metadata` column on `tasks`** (handoff lives on `task_runs.metadata`); idempotency is **racy** (non-unique index, dups persist). |
| E | LLM-free **verifier lane** via `ctx.*` | **REFUTED** | No spawn_fn/lane registrar; `_default_spawn` always runs `hermes -p <profile> chat`. → use the `pre_tool_call` veto. |
| F | Stage metadata reaches hook + child `worker_context` | **GO** | Hook reads `args.metadata`; child sees each **direct done parent's** last completed run summary+metadata (4 KB/field cap; 8 KB body). |
| G | Reserved cols writable publicly | **REFUTED** | No production writer; read-filterable on CLI only. Use the root provenance. |
| H | Human gates via block/unblock; native fan-in | **ADJUST** | Native AND-join fan-in (`all(parents ∈ {done,archived})`). Worker **cannot** `unblock` (orchestrator-guarded); `block` is worker-allowed but **ownership-scoped to its own card**. Sticky gate needs `kanban_block()`, not `initial_status:blocked`. |
| **I** | Ownership: a worker can `complete`/`block` a **foreign** card | **REFUTED** | `_enforce_worker_task_ownership` rejects any `task_id ≠ HERMES_KANBAN_TASK`. → the hook can only create/link; gate/barrier ops are orchestrator-context (CLI). Orchestrator/CLI **can** mutate any card. |
| **J** | Native **rollup** (parent auto-completes when children done) | **REFUTED** | The only link aggregation, `recompute_ready`, reads **parents** to promote a **child** to `ready` (never `done`). `done` is always explicit. → joins are *children* of fan-out, created already-wired. |
| **K** | Worker can **read** a foreign card | **GO** | `kanban_show` is worker-allowed, ungated, returns full `body` + `parents`/`children`. → hook reads provenance + enumerates by link-walk. |
| **L** | Worker can **enumerate** the board (`kanban_list`) | **REFUTED for workers** | `kanban_list` is **orchestrator-only**. → hook uses link-walk; the CLI uses `kanban_list`. |
| **M** | `recompute_ready` vs late-added parents | **GO (race window)** | `recompute_ready` never demotes; `claim_task`'s parent re-check only protects edges present at claim time. → wire joins to all parents **before** any parent completes. |
| **N** | Structural non-worked **barrier** card | **GO** | A label/non-existent assignee → `skipped_nonspawnable` (silent, no breaker, no "stuck" warning). A `done`/`archived` card is a satisfied parent and stays readable (GC trims only events/logs). |
| **O** | `pre_tool_call` can block `kanban_complete` and feed back a retry | **GO** | Callback returns `{"action":"block","message":…}`; tool not dispatched, card stays `running`, message surfaced as the tool result, loop continues. Synchronous before dispatch (a `subprocess.run` gates it). TTL note: a hook subprocess that doesn't tick the heartbeat is safe up to ~1 h. |
| **P** | Non-completing run → escalation | **GO** | goal_mode budget exhaustion → **sticky `blocked`** (clean human handoff); classic clean-exit-without-complete → protocol-violation auto-block; breaker default limit 2. |
| **Q** | Worktrees auto-provisioned; completion preserves them | **ADJUST** | Hermes does **not** create worktrees (the LLM worker runs `git worktree add`); completion **preserves** `worktree`/`dir` (only `scratch` is deleted); no auto-commit; no native merge. → **engine pre-provisions** (hand worker a `dir:`); veto enforces commit. |
| **R** | `build_worker_context` fan-in scaling | **GO** | Surfaces **all** done direct parents (no count cap, no total cap; ~N×8 KB), 4 KB/field each. → fan-in consumer is a direct child of all instances; keep summaries tight. |
| **S** | Reopen a `done` card | **ADJUST** | Only via the **dashboard HTTP API** (no source-status guard); tool/CLI treat `done` as terminal. → `modify` = fresh cards. `kanban_link` re-close/re-open cycle verified. |
| **T** | Per-profile enablement / `plugins enable`-`list` | **GO** | pip only *discovers*; opt-in per profile required; `hermes -p <p> plugins enable` writes that profile's config atomically; `plugins list --json` is config-only, **enabled ≠ loaded** (use in-process `list_plugins()` for true load status). |
| **U** | Native Claude Code **lane** | **REFUTED (low-delta to build)** | Hermes bundles only `kanban-codex-lane`; the generic `claude-code` skill has no kanban contract; ACP adapter is server-side. → plugin ships its own `kanban-claude-code-lane` skill (≈85% port). |

**Design rules that follow directly**
- **Hook callback signature:** `def on_tool_done(tool_name, args, result, task_id, **kwargs)` — `**kwargs` mandatory.
- **Self-gate hard:** act only when `tool_name == "kanban_complete"` ∧ `result` has no `error` ∧ the completing card carries our sentinel.
- **Hook powers = create + link only.** Gate-open/resolve, barrier-complete, unblock, and global reconcile are **orchestrator-context CLI** operations.
- **Read provenance** via `kanban_show(root).body`; **enumerate** a run via link-walk from the root (`kanban_show` `children`).
- **Always pass `board` explicitly**, and set `workspace_kind`/`workspace_path` explicitly on every hook-issued create.
- **Per-profile enablement** is pre-flighted at `workflow_start` (orchestrator side), fail-fast with remediation.

## 7. The workflow template (DSL)

A template is a YAML file (`<name>.workflow.yaml`) discovered from the project directory or `~/.hermes/workflows/` and **snapshotted into the run's root provenance at start** (so editing the file never affects an in-flight run). Worked example exercising every 0.1.0 feature:

```yaml
# fix-flaky-tests.workflow.yaml
name: fix-flaky-tests
version: 0.1.0                            # template version — independent of plugin version
description: Find flaky tests, fix each in isolation, verify, gate, report.

params:                                   # declared inputs, validated deterministically at start
  repo:     { type: string, required: true }
  test_cmd: { type: string, default: "pytest -q" }

roles:                                    # abstract roles → bound to profiles at start
  scout:    { lane: profile }
  fixer:    { lane: claude-code }         # external-tool lane (codex | claude-code)
  reporter: { lane: profile }

stages:
  - id: scan
    role: scout
    title: "Scan ${params.repo} for flaky tests"
    body: |
      Identify flaky tests. Return metadata.flaky as a list of
      {test_id, file}. Do not fix anything.
    workspace: "dir:${params.repo}"
    expand_out: { key: flaky, item: { test_id: string, file: string } }   # declared output shape (veto-enforced)

  - id: fix
    role: fixer
    needs: [scan]
    expand: { over: scan.flaky, as: t }   # dynamic: 1 card per flaky test
    title: "Fix flaky test ${t.test_id}"
    body:  "Fix ${t.test_id} in ${t.file}. Keep the change minimal."
    workspace: "worktree:${params.repo}"  # engine pre-provisions an isolated worktree
    verify: { command: "${params.test_cmd} ${t.file}", retry: 2 }   # veto-enforced; commit-clean also enforced

  - id: approve
    needs: [fix]                          # join: gate waits for ALL fix cards
    gate:  human                          # non-spawnable card; resolve via `hermes workflow approve|reject|modify`

  - id: report
    role: reporter
    needs: [approve, fix]                 # approve = ordering; fix = data (direct handoffs from all fix cards)
    title: "Summarize the fixes"
    body:  "Summarize all fixes from the parent handoffs and list the branches."
```

**Field reference (0.1.0)**

| Field | Meaning |
|---|---|
| `params` | Typed inputs; validated deterministically before any card is created. |
| `roles.<name>.lane` | Execution mode: `profile` (normal Hermes spawn) or an **external-CLI lane** (`codex` \| `claude-code`). A lane = (bundled lane skill, CLI binary, permission policy); the engine sets the card's `skills` to the lane skill and pre-provisions its worktree. Bound to a concrete profile at start. |
| `stages[].role` | Abstract role; must appear in `roles`. Omitted for a pure `gate` stage. |
| `stages[].needs` | Dependencies. On a **post-fan-out** stage, `needs: [X]` wires a direct parent edge from **every** instance of `X` — both for ordering and as the native handoff channel. List a gate **and** a data-stage when a stage needs pre-gate data (e.g. `needs: [approve, fix]`). |
| `stages[].expand` | `{ over: <stage>.<key>, as: <var> }`. When the source stage completes, the hook reads that metadata list and creates one card per item, interpolating `${<var>.*}`. |
| `stages[].expand_out` | On an `expand` *source* stage: the declared **output shape** the veto enforces before the stage may complete (so fan-out never runs on malformed/missing data). |
| `stages[].verify` | `{ command, retry }`. A **veto-enforced completion precondition** run in the stage's own worker: exit 0 to complete; `retry: N` is the goal_mode turn budget; exhaustion → sticky-block for human review. Requires a persistent workspace (`dir:`/`worktree:`). |
| `stages[].gate: human` | A non-spawnable card; resolved by `hermes workflow approve|reject|modify` (orchestrator context). |
| `stages[].workspace` | `scratch` / `dir:<path>` / `worktree:<path>`. The engine **pre-provisions** a `worktree:` as an isolated git worktree and hands the worker a ready `dir:`. Worktree stages additionally get the **commit-clean** veto. `verify` stages must not use `scratch`. |

**Veto-enforced completion preconditions** (one mechanism, self-selected per stage): `verify.command` (exit 0), `expand_out` shape, commit-clean (worktree stages). All three are separate, explicit attributes; all enforced by the same `pre_tool_call` veto in the stage worker.

**Templating is deliberately bounded** to `${params.*}` and `${<expand-var>.*}`. All other cross-stage data flows through Hermes' native parent-handoff (`worker_context`), never string interpolation.

## 8. Workflow ↔ Kanban relationship

The workflow primitive is a **layer that authors and advances a structured card-graph**; Kanban remains the **executor**. A workflow instance is one **root card** (a completed blackboard) + the connected subgraph it spawned, distinguished by the body sentinel.

| Workflow concept | Kanban reality |
|---|---|
| Template (`*.workflow.yaml`) | *(board-agnostic YAML; snapshotted into the root at start)* |
| Workflow instance / run | a completed root blackboard card + its connected subgraph |
| Stage | a card (or N cards when fanned out) |
| `needs` dependency | a `task_links` parent→child edge (to every instance when the parent stage fanned out) |
| Role | assignee (bound profile) + lane (skill + binary) |
| Gate | a non-spawnable `ready` card, resolved by CLI |
| Verification | a `pre_tool_call` veto in the stage worker (no card) |
| Stage→stage handoff | native `worker_context` (each direct done parent's summary + metadata) |
| Run-state / provenance | write-once compiled-template snapshot in the root body; live state derived from the board |
| Execution | the unchanged kanban dispatcher claiming `ready` cards |

**Cardinality:** a board holds **many** coexisting workflow instances plus ad-hoc cards. One instance is **wholly within one board** (Hermes forbids cross-board linking). Concurrent instances share the board's dispatch budget.

## 9. Runtime model & data flow

1. **`workflow_start(template, params, bindings, board?)`** *(orchestrator context — refuses if run inside a worker)*: load + snapshot YAML; validate `params` deterministically; resolve roles → profiles (fail fast on a missing profile); **pre-flight per-profile enablement** (each bound profile has `hermes-workflow` enabled and loadable; codex/claude-code profiles also have the lane skill + CLI binary) — fail fast with copy-pasteable remediation, creating **zero** cards on failure. Then create the **root blackboard card** (body = compiled snapshot; label assignee; completed to `done`), and materialize the **dynamic-free prefix** as its children.
2. **Static prefix** runs on native parent-gating.
3. **The `post_tool_call` hook** (in the completing worker) is the **fan-out driver**: self-gates, reads `args.metadata`, link-walks the local neighborhood for idempotent reconcile, and via `ctx.dispatch_tool` **creates + links** the next tail up to the next dynamic boundary — fan-out children, their downstream join(s) wired to **all** instances before any can complete, and the gate/report tail. It never completes/blocks/unblocks foreign cards.
4. **The `pre_tool_call` veto** (in the stage worker) gates `kanban_complete` on the stage's preconditions (verify command, `expand_out` shape, commit-clean). Failures feed back as the tool result for in-run retry; `retry: N` = goal_mode budget; exhaustion → goal_mode sticky-block.
5. **Gates** are non-spawnable `ready` cards. Resolution is **orchestrator-context CLI**: `approve` completes the gate; `reject` archives the gate + its downstream subtree; `modify` spawns fresh feedback-injected replacement cards, **re-wires them into every consumer of the superseded card (the gate *and* its data consumers like `report`), and archives the superseded original** (still auditable; skipped by `worker_context` so consumers read the redo), re-closing then re-opening the gate. Decisions persist on the cards.
6. **Crash / timeout** lean on Hermes' native circuit-breaker + `workflow_reconcile` (the same idempotent keep-min-id path). A totally-failed fan-out (no sibling ever completes to re-fire the hook) is caught by `workflow_reconcile` or its **diagnosis** ("stage `done`, expected downstream absent" ⇒ probable plugin-not-enabled in that profile).

## 10. Component architecture

Fat engine / thin shell. The engine holds all logic and carries the test weight; `tools.py` / `hooks.py` are imperative glue over `ctx.dispatch_tool`.

```
hermes-workflow/
├── plugin.yaml                 # name, version: 0.1.0, provides_tools, provides_hooks: [post_tool_call, pre_tool_call]
├── __init__.py                 # register(ctx): tools + CLI + slash + hooks + bundled skills (incl. lane skills)
├── engine/                     # PURE, deterministic, no board/LLM — the unit-tested core
│   ├── template.py             #   parse + validate YAML, params, roles, cycle detection, output-shape schemas
│   ├── graph.py                #   "completed stages + metadata → cards that should exist up to next dynamic boundary"
│   ├── provenance.py           #   root compiled-snapshot read + body sentinels (write-once; NOT a mutable manifest)
│   ├── reconcile.py            #   keep-min-id dedup + archive-loser-subtree; identity = root+stage+fan_index+attempt
│   └── interpolate.py          #   ${params.*} / ${expand-var.*} only
├── tools.py                    # thin shell: workflow_start / status / validate / reconcile / approve / reject / modify
├── hooks.py                    # post_tool_call (fan-out create+link) + pre_tool_call (completion-gate veto)
├── lanes/                      # lane contract: (skill, binary, permission policy); engine wires card.skills + worktree
│   └── presets.py              #   codex + claude-code presets
└── skills/
    ├── workflow-author/SKILL.md
    ├── workflow-orchestrator/SKILL.md
    ├── kanban-codex-lane/SKILL.md        # reused/re-shipped for self-containment
    └── kanban-claude-code-lane/SKILL.md  # NEW — plugin ships it (Hermes has none); tight --allowedTools; Hermes-commits
```

**Surfaces:** a `workflow_*` **tool** (orchestrator agent), a `hermes workflow …` **CLI** (humans/cron/scripts), and a `/workflow` **slash command** (in-session). All *mutating* surfaces are **orchestrator-context-only** (refuse if `HERMES_KANBAN_TASK` is set); read-only `workflow_status` works anywhere. Registered via `ctx.register_tool`, `ctx.register_cli_command`, `ctx.register_command`, `ctx.register_hook`, `ctx.register_skill`.

> **Build-time unknown to confirm:** whether a card's `skills` field force-loads a *plugin-registered namespaced* skill, or whether lane skills must be installed as regular skills. Resolve when wiring lanes.

## 11. Error handling & edge cases

- **Fail-open hook → at-least-once + reconcile (§5.8):** per-child keys make the sequential case idempotent; reconcile (keep-min-id + archive-loser-subtree) converges duplicates deterministically without locks; hook = local, `workflow_reconcile` = global + backstop.
- **Hard self-gating:** the hook also fires on *failed* completes, so success must be checked.
- **Veto callback** must return `{"action":"block","message":…}` to block (not a bare string), and must accept `**kwargs`.
- **Handoff reads** from `args.metadata` with `kanban_show` fallback; the `expand_out` veto prevents fan-out on malformed/None.
- **Fail-fast at `workflow_start`:** unknown bound profile; plugin not enabled/loaded in a bound profile; missing lane skill or CLI binary; a `verify`/worktree stage on `scratch`; invalid params.
- **Gate discipline:** non-spawnable `ready` gate; resolve only from orchestrator/CLI; `reject` archives the **whole** downstream subtree (not just the gate); persist the decision on the card.
- **Empty fan-out** (`expand` over `[]`): create no children; wire the join to the **source** stage so it proceeds; gates still open trivially.
- **Worktree isolation** is engine-pre-provisioned (deterministic), not LLM-dependent; commit-clean is veto-enforced; worktrees persist after completion (operator merges/prunes).
- **Per-profile enablement** is the #1 silent-failure mode — pre-flighted, and *diagnosed* by reconcile if it slips through.
- **Schema-version refusal** for in-flight runs across a plugin upgrade.

## 12. Testing strategy (integration-first)

Per project preference: **integration tests are the default; unit tests only where logic carries real weight; no LLM in either.**

- **Unit — only the pure `engine/`:** template parse/validate (incl. output-shape schemas), the graph function ("completed stages + metadata → next cards up to the next dynamic boundary"), interpolation, provenance read + sentinel derivation, reconcile (keep-min-id, archive-loser-subtree, identity), empty-fan-out & cycle edges.
- **Integration — the bulk, wired to real Hermes, zero LLM:** real board + real plugin load + real `kanban_*`; "worker" steps driven by calling `kanban_complete` with canned metadata. Assert: `workflow_start` materializes the prefix + seeds the done-root blackboard; the `post_tool_call` hook fans out and wires joins to all instances; the `pre_tool_call` veto blocks `kanban_complete` on a failing command/shape/uncommitted-tree and lets it through on success; a gate parks → `approve` promotes / `reject` archives the subtree / `modify` re-closes-then-re-opens; `reconcile` keep-min-id self-heals duplicates; the per-profile pre-flight fails fast.
- **Lane smoke tests (one live run each):** codex and claude-code lanes — `<cli> -p …` in a throwaway pre-provisioned worktree → reconcile → `kanban_complete` with lane metadata. Kept out of CI for determinism/cost.

## 13. 0.1.0 scope vs deferred

**0.1.0 scope:** the template DSL (`params`, `roles`/lanes `{profile, codex, claude-code}`, `needs`, `expand`, `expand_out`, `verify`, `gate`); `workflow_start` / `status` / `validate` / `reconcile` / `approve` / `reject` / `modify` as tool + CLI + `/workflow` slash; `post_tool_call` fan-out + `pre_tool_call` completion-gate veto; **lazy creation**; root-blackboard provenance + body sentinels; **two built lane adapters** (codex + claude-code) via the lane contract; `workflow-author` + `workflow-orchestrator` skills + two lane skills; engine-pre-provisioned worktrees + commit contract; **bounded human-driven `modify` loop**; 1–2 example templates (incl. `build-hermes-plugin` with an integration stage); pip packaging + per-profile enablement installer/pre-flight; integration-first tests.

**Deferred (designed-for, not built):** `fanout: N` (static parallel duplication — a trivial degenerate `expand`, YAGNI until a real use); per-role safety/acceptance policy text; automatic merge/integration of parallel branches; intermediate fan-in aggregator card for very large N; dashboard workflow badge/chrome; conditional branching / loops beyond `modify`/`retry`; additional external-lane adapters beyond codex/claude-code; true non-Hermes dispatcher-spawned lanes; multi-host; mirroring the reserved columns (until Hermes ships a public writer).

## 14. Open questions & de-risking spikes (revised)

- **Spike 1 (veto path):** register a `pre_tool_call` that runs a deterministic command and returns `{"action":"block",…}`; confirm it prevents `kanban_complete`, leaves the card `running`, surfaces the message for retry, and that a goal_mode budget exhaustion sticky-blocks for review. *(Replaces the obsolete verifier-profile spike.)*
- **Spike 2 (the per-profile landmine):** enable the plugin only in root, dispatch to a *different* profile, confirm the hook does **not** fire; enable it in that profile, confirm it does. Confirm the `workflow_start` pre-flight catches the missing case.
- **Spike 3 (worktree pre-provision + lane wiring):** the engine runs `git worktree add` at fan-out and hands the card a `dir:`; confirm the worker spawns inside it; confirm a card's `skills` field force-loads the (plugin-registered?) lane skill.
- **Open:** confirm hook-created cards don't trip `created_cards` / `HallucinatedCardsError` (the hook calls `kanban_create` directly — likely fine; verify in Spike 1). Confirm the `skills`-field resolution for plugin-namespaced lane skills.

## 15. Worked UX example — build a new Hermes plugin

Two human touchpoints: launch, and answer one gate.

**Template** (`build-hermes-plugin.workflow.yaml`): `spec` (architect) → `implement` (builder via claude-code or codex, fanned out one card per tool the spec returns, each verified by an import-check veto, each on its own pre-provisioned worktree) → **`integrate`** (collect the per-tool branches into one plugin — an explicit author-added stage, since the deliverable is one plugin) → `test` (tester, `pytest` veto) → `review` (human gate) → `enable` (reporter).

**Launch:**
```
/workflow start build-hermes-plugin \
  --param plugin_name=rss_reader --param purpose="fetch and parse RSS feeds" \
  --bind architect=designer, builder=coder, tester=qa, reporter=writer
```
The engine validates, binds roles → profiles, pre-flights enablement (incl. the builder profile's lane skill + CLI), seeds the done-root blackboard, and creates the `spec` card on the active board.

**Autonomous execution:** `spec` runs and returns `metadata.tools=[…]` (shape-checked by the veto); the hook fans `implement` into one card per tool — each pre-provisioned a worktree, each gated by an import-check + commit-clean veto — and wires the `integrate` join to **all** implement cards; native fan-in holds `integrate` until every implement card is `done`; `integrate` collects the branches; `test` runs with a `pytest` veto; `review` parks as a non-spawnable gate.

**Answer the gate:** `hermes workflow approve t_root` — downstream resumes; `enable` finishes; the done-root holds the audit trail. `workflow_status t_root` gives a stage rollup (rendered from the board + the snapshot, including not-yet-materialized stages as "pending"); `workflow_reconcile t_root` re-drives if anything stalls. `hermes workflow modify t_review --stage implement --feedback "…"` sends specific tools back for a fresh attempt, re-closing the gate until the redo passes.

**Distinction worth stating:** the workflow's *workers* are real LLM agents (spec, implement, integrate, test, report) — including external-CLI lanes (codex/claude-code) doing real coding. Only the **completion-gate veto** (verify command, output shape, commit-clean) is deterministic and LLM-free. The "no-LLM" rule applies to the plugin's *test suite*, not the workflows it runs.

## 16. References

- Hermes local checkout: `/Users/carlos/cortex-workspace/hermes-agent` (v0.15.1, `c47b9d12`).
- Key source verified: `model_tools.py` (hook dispatch, `pre_tool_call` block), `tools/registry.py` (`dispatch`), `tools/kanban_tools.py` (`_handle_create/_complete/_block/_show/_link`, `_enforce_worker_task_ownership`), `hermes_cli/kanban_db.py` (`recompute_ready`, `claim_task`, `complete_task`, `block_task`, `archive_task`, `resolve_workspace`, `_cleanup_workspace`, `build_worker_context`, `decompose`, dispatch), `hermes_cli/kanban_swarm.py` (root-as-blackboard idiom), `hermes_cli/plugins.py` + `plugins_cmd.py` (enablement, `register_*`, `dispatch_tool`), `hermes_cli/profiles.py` (per-profile homes), `plugins/kanban/dashboard/plugin_api.py` (`_set_status_direct` reopen), `skills/autonomous-ai-agents/kanban-codex-lane` + `claude-code`.
- Abandoned upstream lane feature: issue #19931, PR #19924 (both closed) — no public custom-lane registrar.
- Prior art: Hermes' own `kanban_swarm` / `kanban_decompose` (native validation of the declarative-graph + native-fan-in + blackboard approach); `tonbistudio/hermes-multi-agent-workflow` (the un-native seam this plugin removes).
