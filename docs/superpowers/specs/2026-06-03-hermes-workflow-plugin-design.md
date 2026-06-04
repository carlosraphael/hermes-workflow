# hermes-workflow — Design Spec

- **Date:** 2026-06-03
- **Status:** ⚠️ SUPERSEDED by `2026-06-03-hermes-workflow-plugin-design-final.md`. Source vetting found four mechanisms here are not buildable against Hermes v0.15.1 (foreign-card completion from the hook, an LLM-free verifier lane, an auto-rollup join, and a hook-edited root-body manifest). Kept for history; do not plan from this.
- **Plugin version target:** `0.1.0` (experimental 0.x line; see Versioning)
- **Verified against:** Hermes Agent local checkout `/Users/carlos/cortex-workspace/hermes-agent` (v0.15.1, commit `c47b9d12`)

---

## 1. Summary

`hermes-workflow` is a native Hermes Agent plugin that adds a first-class, reusable **workflow primitive** on top of the Kanban board. A *workflow template* is a versioned YAML file describing a multi-stage, multi-role process — stages, dependencies, dynamic fan-out, human gates, and verification. Instantiating a template materializes a linked Kanban card-graph that Hermes' existing dispatcher and worker lanes execute. The plugin ships **tools** (define / start / inspect / reconcile), **hooks** (a `post_tool_call` reactor and a `pre_tool_call` verify gate), and **skills** (author + orchestrator playbooks).

The primitive turns "hand-wire an orchestrator from scratch every time" into a repeatable, durable, inspectable run on the board the operator already uses.

## 2. Versioning philosophy

The first release is **`0.1.0`**. The whole `0.x` line is explicitly experimental: **no backward-compatibility guarantees** between `0.x` versions — template schema, manifest format, tool signatures, and hook behavior may all change freely while ideas are tested. **`1.0.0` is the future stabilization milestone** at which the template DSL and manifest schema become stable and a compatibility policy begins.

Note on terminology to avoid collisions:
- "**0.1.0 scope**" in this doc = the feature set of the first release (§12). It is *not* the eventual `1.0.0`.
- Hermes' own "**v2**" (e.g. the reserved `workflow_template_id` / `current_step_key` columns "reserved for v2") refers to the *Hermes* roadmap and is unrelated to this plugin's version.

## 3. Problem & gap

Hermes provides strong multi-agent primitives — a durable Kanban board (state machine + message queue + audit log), worker lanes (assignee → profile, dispatcher-spawned), `kanban_*` tools, and orchestrator/worker behavior taught through *prose skills* re-derived by the LLM each run. What it lacks is a **reusable, declarative workflow object**: a repeatable process definition that can be customized per domain and instantiated on demand.

The community's `tonbistudio/hermes-multi-agent-workflow` is the closest existing solution, but it defines workflows in YAML interpreted by an LLM-driven Markdown skill that shells into Python via brittle `python -c` one-liners and **writes the board's SQLite schema directly** — reaching *under* Hermes' API rather than *through* it. That direct-schema coupling is the "un-native" seam this plugin removes.

## 4. Goals / non-goals

**Goals**
- A declarative, versioned workflow template (YAML) that instantiates into a Kanban card-graph.
- Hybrid materialization: static graph by default, with declared dynamic fan-out.
- Customizable across domains via abstract roles bound to real profiles, plus per-stage gates and verification.
- Strictly native: only public `kanban_*` tools / `ctx.dispatch_tool`; never raw SQLite; never depend on unwired Hermes surfaces.
- Community-quality: pip-distributable, integration-tested, documented, with example templates.

**Non-goals (0.1.0)**
- Multi-host coordination (Hermes is single-host).
- Replacing the dispatcher / claim / reclaim / circuit-breaker machinery (reused as-is).
- Auto-decomposition / auto-assignment (that is Hermes' LLM decomposer).
- Per-role safety/acceptance policy text (deferred).
- A general "wrap any external CLI" framework — one reference Codex lane adapter, with a documented extension point.

## 5. Locked design decisions

1. **Core model:** declarative YAML template → instantiated as a Kanban card-graph.
2. **Expansion:** hybrid — static graph (native parent-gating) + declared dynamic fan-out (`expand`).
3. **Runtime driver:** an event-hook + fat-engine architecture. A `post_tool_call` hook reacts to `kanban_complete`; a pure deterministic engine computes what cards should exist next; mutations go through `ctx.dispatch_tool`.
4. **Linkage & state:** a JSON **manifest on a workflow-root card** plus per-card **body sentinels**. Never the reserved columns, never raw SQLite.
5. **Verification:** a real Hermes **profile** worker (the `verifier` lane) that runs one deterministic command and routes on **exit code** — LLM-free in substance. Optionally backed by a `pre_tool_call` veto of `kanban_complete`.
6. **Gates:** human-approval via `kanban_block("review-required: …")`; resume from **outside** the worker (human CLI / dashboard / orchestrator process).
7. **Board scoping:** materialize on the **active board** by default; `--board` opts into a dedicated/isolated board. A single run is always wholly within one board.
8. **Audience:** polished, pip-distributable community plugin.

## 6. Feasibility findings (verified against source)

All load-bearing assumptions were verified against the local Hermes checkout (v0.15.1, `c47b9d12`) with an adversarial second pass. Verdicts:

| # | Mechanism | Verdict | Consequence for the design |
|---|---|---|---|
| A | `post_tool_call` fires after `kanban_complete`; callback reads the handoff | **GO** | Fires unconditionally in-process; read the handoff from the `args` kwarg, **not** `result`. |
| B | Hook calls `ctx.dispatch_tool("kanban_create"/"kanban_link")`, incl. other profiles | **GO (guards)** | `registry.dispatch` has no toolset/`check_fn` gate; create/link are worker-allowed, sync, no hook recursion. |
| C | Dispatcher-spawned workers load the plugin | **ADJUST** | True, but the worker reads `plugins.enabled` from the **assignee profile's** config (its profile-scoped `HERMES_HOME`), not root. **#1 silent-failure mode.** |
| D | `kanban_create` returns id / parents / idempotency / linkage | **ADJUST** | Returns id, accepts `parents` + `idempotency_key`, but has **no `metadata` field**; idempotency is best-effort (non-unique index, racy). `kanban_complete` result omits metadata. |
| E | Plugin registers an LLM-free **verifier lane** via `ctx.*` | **REFUTED** | No public spawn_fn/lane registrar; upstream feature abandoned (issue #19931 / PR #19924 closed). Use a real profile worker keyed on exit code. |
| F | Stage metadata reaches the hook + downstream `worker_context` | **GO (guards)** | Hook reads `args.metadata`; child sees the parent's last-completed run summary + metadata (4 KB cap — don't parse the prose for typed inputs). |
| G | Reserved cols `workflow_template_id` / `current_step_key` writable publicly | **REFUTED** | No public writer on any surface; doc's "clients can write them" is unwired. Use the root-card manifest. |
| H | Human gates via block + unblock + comment; native fan-in promotion | **ADJUST (medium)** | Mechanism is real and vendor-blessed, but the worker-process hook **cannot** `kanban_unblock` (env guard); a sticky gate needs `kanban_block()` not `initial_status:blocked`. |

**Design rules that follow directly from the findings**
- **Hook callback signature must be** `def on_tool_done(tool_name, args, result, task_id, **kwargs)` — `**kwargs` is mandatory (it absorbs `session_id` / `tool_call_id`; omitting it `TypeError`s silently).
- **Self-gate hard:** act only when `tool_name == "kanban_complete"` ∧ `json.loads(result)` has no `error` key ∧ the completing card carries our sentinel.
- **At-least-once + reconcile:** the hook is observational and fail-open (return ignored, exceptions swallowed). Every mutation is idempotent (`idempotency_key = hash(workflow_root + stage_id + fan_index)`, one per child — never shared). Each fire reconciles (list root's children, dedupe on sentinel, archive strays). A silently-failed dispatch self-heals on the next completion or via `workflow_reconcile`.
- **Read handoffs from `args.metadata`**, with defense-in-depth re-read via `kanban_show` / `latest_run(...).metadata`. The `kanban_complete` result is only the `{ok,...}` envelope.
- **Carry per-card linkage in the card body** (a sentinel block: `workflow_root`, `stage_id`, `template_id`, `schema_version`), kept under ~8 KB for the worker-context cap, plus a namespaced `HERMES_WORKFLOW_LINK:` comment for audit. Never the reserved columns.
- **Always pass `board` explicitly** (from `HERMES_KANBAN_BOARD`) and set `workspace_kind` / `workspace_path` explicitly on every hook-issued create (don't inherit the completing worker's workspace; don't rely on `created_by`).
- **Per-profile enablement:** `workflow_start` ensures `hermes-workflow` is enabled in each bound profile's home and self-checks at startup; a missing enablement fails fast rather than stalling.
- **Codex lane is a Hermes profile worker** that wraps Codex as a subprocess inside its own run, so it still calls `kanban_complete` and the hook fires normally. The "non-Hermes lane doesn't fire the hook" gap does **not** apply to the 0.1.0 lanes.

## 7. The workflow template (DSL)

A template is a YAML file (`<name>.workflow.yaml`) discovered from the project directory or `~/.hermes/workflows/`. Worked example exercising every 0.1.0 feature:

```yaml
# fix-flaky-tests.workflow.yaml
name: fix-flaky-tests
version: 0.1.0                            # template version — independent of plugin version
description: Find flaky tests, fix each in isolation, verify, gate, report.

params:                                   # declared inputs, validated at start
  repo:     { type: string, required: true }
  test_cmd: { type: string, default: "pytest -q" }

roles:                                    # abstract roles → bound to profiles at start
  scout:    { lane: profile }
  fixer:    { lane: codex }               # external-tool lane adapter
  verifier: { lane: verifier }            # deterministic, LLM-free
  reporter: { lane: profile }

stages:
  - id: scan
    role: scout
    title: "Scan ${params.repo} for flaky tests"
    body: |
      Identify flaky tests. Return metadata.flaky as a list of
      {test_id, file}. Do not fix anything.
    workspace: "dir:${params.repo}"

  - id: fix
    role: fixer
    needs: [scan]
    expand: { over: scan.flaky, as: t }   # dynamic: 1 card per flaky test
    title: "Fix flaky test ${t.test_id}"
    body:  "Fix ${t.test_id} in ${t.file}. Keep the change minimal."
    workspace: "worktree:${params.repo}"
    verify: { command: "${params.test_cmd} ${t.file}", retry: 2 }

  - id: approve
    needs: [fix]                          # join: waits for ALL fix cards
    gate:  human                          # pause → approve / reject / modify

  - id: report
    role: reporter
    needs: [approve]
    title: "Summarize the fixes"
    body:  "Summarize all fixes from the parent handoffs."
```

**Field reference (0.1.0)**

| Field | Meaning |
|---|---|
| `params` | Typed inputs; `workflow_start` supplies values; validated before any card is created. |
| `roles.<name>.lane` | Execution mode: `profile` (normal Hermes spawn), `codex` (external-tool adapter), or `verifier` (deterministic, LLM-free). Bound to a concrete profile at start. |
| `stages[].role` | Abstract role; must appear in `roles`. Omitted for a pure `gate` stage. |
| `stages[].needs` | Static dependencies → native `kanban_link` parent edges. Run by Hermes' own fan-in; the engine doesn't touch them at runtime. |
| `stages[].expand` | `{ over: <stage>.<metadata-key>, as: <var> }`. The one dynamic moment: when the source stage completes, the hook reads that metadata list and creates one card per item, interpolating `${<var>.*}`. |
| `stages[].fanout: N` | Static parallel duplication (fixed count) when data-dependence isn't needed. |
| `stages[].verify` | `{ command, retry }`. Compiled into an auto-injected verifier card gated on the stage, sharing its workspace, run by the `verifier` profile lane. Exit 0 → pass; non-zero → block/retry. Requires a persistent workspace (`dir:` / `worktree:`), not `scratch`. |
| `stages[].gate: human` | No role needed; the engine opens a sticky gate (`kanban_block("review-required: …")`). Human `unblock` (approve) lets `needs`-children proceed; a `reject` / `modify` decision (from the unblock comment) archives or re-runs downstream. |
| `stages[].workspace` | `scratch` / `dir:<path>` / `worktree:<path>`. `verify` stages must not use `scratch`. |

**Templating is deliberately bounded** to `${params.*}` and `${<expand-var>.*}`. All other cross-stage data flows through Hermes' native parent-handoff (`worker_context`), never string interpolation.

## 8. Workflow ↔ Kanban relationship

The workflow primitive is a **layer that authors and advances a structured card-graph**; Kanban remains the **executor** (durable state machine, dispatcher, lanes, audit). A workflow instance is one **root card** + the connected subgraph it spawned, distinguished by the body sentinel and the root-card manifest.

| Workflow concept | Kanban reality |
|---|---|
| Template (`*.workflow.yaml`) | *(no kanban equivalent — board-agnostic YAML)* |
| Workflow instance / run | a root card + its connected card subgraph |
| Stage | a card (or N cards when fanned out) |
| `needs` dependency | a `task_links` parent→child edge |
| Role | assignee (bound profile) + lane |
| Gate | a `blocked` card (`review-required:`) |
| Verification | a card on the `verifier` profile |
| Stage→stage handoff | native `worker_context` (parent run summary + metadata) |
| Run-state / manifest | JSON in the root card body + comments |
| Execution | the unchanged kanban dispatcher claiming `ready` cards |

**Cardinality:** *not* one-per-board. A board (heavyweight: own SQLite DB, dispatcher loop, workspaces dir; meant to be one-per-project/repo/domain) holds **many** coexisting workflow instances plus ad-hoc cards. One instance is **wholly within one board** (Hermes forbids cross-board linking). Concurrent instances share the board's dispatch budget (`max_in_progress` / per-profile caps).

**Board scoping default:** active board; `--board` for opt-in isolation.

## 9. Runtime model & data flow

1. **`workflow_start(template, params, bindings, board?)`** — load + validate YAML; validate `params`; resolve abstract roles → real profiles (fail fast on a missing profile — the silent-drop fix); ensure the plugin is enabled in each bound profile's home. Create the **workflow-root card** (body = JSON manifest: template id + version, params, bindings, stage→card-id map, gate state, schema version) and materialize the initial static cards — each with a body sentinel and `parents=[…]` links. The dispatcher + native fan-in take over.
2. **Static deps** run entirely on native parent-gating; the engine never touches them.
3. **The `post_tool_call` hook** (fires in-worker after `kanban_complete`) is the only runtime driver, and only for dynamic moments. It self-gates, reads `args.metadata`, and via `ctx.dispatch_tool`: (a) expands `expand.over` lists into N idempotent child cards; (b) opens gates; (c) updates the manifest. It reconciles each fire (at-least-once + verify).
4. **Verification** = an auto-injected card on the `verifier` profile sharing the stage's persistent workspace; exit-code → complete/block; `retry: N` re-creates the stage card. Optionally enforced by a `pre_tool_call` veto so a stage cannot `kanban_complete` before its verify passes (a backstop; the worker should run verify itself).
5. **Gates** open via `kanban_block("review-required: …")`; resume happens **outside** the worker — human `hermes kanban unblock` / dashboard (re-spawns with the comment thread) / orchestrator process — with the decision persisted to the manifest. Downstream auto-promotes via native fan-in.
6. **Crash / timeout** terminations (which don't fire the hook) lean on Hermes' native circuit-breaker (auto-block after N failures) + a manual `workflow_reconcile` repair tool (the same idempotent reconcile path).

## 10. Component architecture

Fat engine / thin shell. The engine holds all logic and carries the test weight; `tools.py` / `hooks.py` are imperative glue over `ctx.dispatch_tool`.

```
hermes-workflow/
├── plugin.yaml                 # name, version: 0.1.0, provides_tools, provides_hooks: [post_tool_call, pre_tool_call]
├── __init__.py                 # register(ctx): tools + hooks + bundled skills
├── engine/                     # PURE, deterministic, no board/LLM — the unit-tested core
│   ├── template.py             #   parse + validate YAML, params, roles, cycle detection
│   ├── graph.py                #   compute "given completed stages + metadata → cards that should exist"
│   ├── manifest.py             #   root-card JSON manifest read/update + body sentinels
│   └── interpolate.py          #   ${params.*} / ${expand-var.*} only
├── tools.py                    # thin shell: workflow_start / workflow_status / workflow_validate / workflow_reconcile
├── hooks.py                    # post_tool_call (fan-out/gates) + pre_tool_call (verify veto); calls engine then ctx.dispatch_tool
├── lanes/codex.py              # Codex-wrapping worker guidance (reference adapter)
└── skills/
    ├── workflow-author/SKILL.md       # how to write a template
    └── workflow-orchestrator/SKILL.md # kickoff, status, gate resolution, reconcile
```

**Surfaces** (mirroring Kanban's dual-surface design): a `workflow_*` **tool** (an orchestrator agent launches it mid-chat), a `hermes workflow …` **CLI** (humans / cron / scripts), and a `/workflow` **slash command** (in-session). Registered via `ctx.register_tool`, `ctx.register_cli_command`, `ctx.register_command`, `ctx.register_hook`, `ctx.register_skill`.

## 11. Error handling & edge cases

- **Fail-open hook → at-least-once + reconcile** (see §6 design rules): idempotent per-child keys; reconcile each fire; `workflow_reconcile` for manual repair.
- **Hard self-gating;** the hook also fires on *failed* completes, so success must be checked.
- **Handoff reads** from `args.metadata` with `kanban_show` / `latest_run` fallback; a worker that forgot to emit metadata flags the stage in the manifest rather than fanning out on `None`.
- **Fail-fast at `workflow_start`:** unknown bound profile; plugin not enabled in a bound profile's home; a `verify` stage on a `scratch` workspace; a `verifier` profile whose toolset can't run a command.
- **Gate discipline:** sticky gate via `kanban_block` (not `initial_status:blocked`); never archive an open gate; resume only from human / CLI / orchestrator; re-read status after unblock (the tool echoes `ready` even when it parked in `todo`); persist the decision to the manifest (comment thread truncates past 30 comments / 2 KB each).
- **Empty fan-out** (`expand` over `[]`): create no children and gate the join on the *source* stage so it still proceeds.
- **Template validation:** cycle detection over `needs` / `expand`; schema-version stamp; reject unknown role references and malformed `expand.over`.
- **Board resolution:** always pass `board` explicitly on hook-issued mutations.

## 12. Testing strategy (integration-first)

Per project preference: **integration tests are the default; unit tests only where logic carries real weight; no LLM in either.**

- **Unit — only the pure `engine/`:** template parse + validate, the graph function ("completed stages + metadata → next cards"), interpolation, manifest read/update, idempotency-key derivation, empty-fan-out & cycle edges. No board, no LLM.
- **Integration — the bulk, wired to real Hermes, zero LLM:** a real Kanban board + real plugin load + real `kanban_*` tools; "worker" steps driven by calling `kanban_complete` directly with canned metadata (deterministic stubs, not a model). Assert: `workflow_start` materializes the right cards/links; the `post_tool_call` hook fans out correctly; the verify card runs a real shell command and routes on exit code; a gate blocks → unblocks → promotes; `reconcile` self-heals after a simulated hook failure; the per-profile-enablement self-check fails fast. The two de-risking spikes (§14) become the first two integration tests.
- **Optional manual e2e** (one real model run, happy path) — kept out of CI for determinism / cost.

## 13. 0.1.0 scope vs deferred

**0.1.0 scope:** the template DSL (`params`, `roles`/lanes, `needs`, `fanout`, `expand`, `verify`, `gate`); `workflow_start` / `status` / `validate` / `reconcile` as tool + CLI + `/workflow` slash; `post_tool_call` fan-out + `pre_tool_call` verify-veto; root-card manifest + body sentinels; `verifier` profile lane; **one Codex reference lane adapter**; `workflow-author` + `workflow-orchestrator` skills; 1–2 example templates (incl. `build-hermes-plugin`); pip packaging + per-profile enablement installer/self-check; integration-first tests.

**Deferred (designed-for, not built):** per-role safety/acceptance policy text; automatic gateway-tick reconciler (needs a confirmed invocation seam); dashboard workflow badge/chrome; conditional branching / loops beyond `retry`; additional external-lane adapters; true non-Hermes pull-based lanes; multi-host; mirroring the reserved columns for board-level filtering (until Hermes ships a public writer).

## 14. Open questions & de-risking spikes

- **Spike 1 (validates E + C):** create a `verify` Hermes profile with a terminal-capable toolset and `hermes-workflow` enabled in *its* profile home; hand-create a card assigned to it that runs a deterministic command and `kanban_complete`/`kanban_block`s on exit code; confirm it is spawnable (not bucketed `skipped_nonspawnable`), can run the command, and that the `post_tool_call` hook observes its metadata.
- **Spike 2 (15 min, the per-profile landmine):** enable the plugin only in root, dispatch to a *different* profile, confirm the hook does **not** fire; enable it in that profile, confirm it does.
- **Open:** confirm `created_cards` / `HallucinatedCardsError` does not reject hook-created cards (likely fine — the hook calls `kanban_create` directly; verify in Spike 1). Keep the `pre_tool_call` veto a backstop (the worker skill should run verify itself), not the primary path. Confirm a gateway-tick invocation seam *if* the automatic reconciler is pursued later (deferred).

## 15. Worked UX example — build a new Hermes plugin

The operator's experience is **two human touchpoints**: launch, and answer one gate.

**Template** (`build-hermes-plugin.workflow.yaml`): `spec` (architect) → `implement` (builder/Codex, fanned out one card per tool the spec returns, each verified by an import check) → `test` (tester, verified by `pytest`) → `review` (human gate) → `enable` (reporter).

**Launch:**
```
/workflow start build-hermes-plugin \
  --param plugin_name=rss_reader --param purpose="fetch and parse RSS feeds" \
  --bind architect=designer, builder=coder, tester=qa, reporter=writer
```
The engine validates, binds roles → profiles, ensures enablement, and creates the root + `spec` cards on the active board.

**Autonomous execution** (on the normal dashboard): `spec` runs and returns `metadata.tools=[…]`; the hook fans `implement` into one card per tool, each gated by a `verify` import-check; native fan-in holds `test` until all implement cards are `done`; `test` runs with a `pytest` verify; `review` blocks.

**Answer the gate:** `hermes kanban unblock t_review` (approve) — downstream resumes; `enable` finishes and the root card holds the full audit trail. `workflow_status t_root` gives a stage rollup; `workflow_reconcile t_root` re-drives if anything stalls.

**Distinction worth stating:** the workflow's *workers* are real LLM agents doing real work (spec, implement, test, report). Only the **verify** commands are deterministic and LLM-free. The "no-LLM" rule applies to the plugin's *test suite*, not to the workflows it runs.

## 16. References

- Hermes local checkout: `/Users/carlos/cortex-workspace/hermes-agent` (v0.15.1, `c47b9d12`).
- Key source: `model_tools.py` (hook dispatch L991–1006), `tools/registry.py` (`dispatch` L390–416), `tools/kanban_tools.py` (`_handle_create` / `_handle_complete`), `hermes_cli/kanban_db.py` (`_default_spawn`, `recompute_ready`, `dispatch_once`), `hermes_cli/plugins.py` (`PluginContext`, `discover_plugins`, enablement).
- Docs: Kanban (features + worker-lanes), build-a-hermes-plugin, adding-tools, creating-skills, hooks.
- Abandoned upstream lane feature: issue #19931, PR #19924 (both closed) — confirms no public custom-lane registrar.
- Prior art: `tonbistudio/hermes-multi-agent-workflow` (the un-native seam this plugin removes).
