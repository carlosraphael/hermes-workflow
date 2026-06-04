# hermes-workflow — Grill Decisions (change-set for the FINAL spec)

- **Date:** 2026-06-04
- **Status:** ✅ APPLIED (2026-06-04) to `2026-06-03-hermes-workflow-plugin-design-final.md` after a 29-agent source cross-check (verdict: apply all decisions, 0 rejections; with 4 wording fixes — A3/B1/B7/D3 — cite corrections, and 3 grill-missed gaps folded in: a HIGH review-required backstop, a MED abandon worktree-orphan note, a LOW-MED §15 example fix). See the final spec's §0/§6 for the cross-check outcome. Kept as the decision-history artifact.
- **Verified against:** Hermes Agent local checkout `/Users/carlos/cortex-workspace/hermes-agent` (v0.15.1, `c47b9d12`).
- **Relationship:** The FINAL spec remains the base. Every item below is an *accepted* change (✓) to apply to it. Net effect: **two CRITICALs eliminated; the 0.1.0 spine is smaller and safer.**

---

## 0. What this is

A grill session interrogated the FINAL spec branch-by-branch. Each question was grounded in the Hermes source (not docs, not the spec's own claims), and each produced a recommendation the design owner accepted. This document records those decisions with their source evidence and the concrete spec edit each implies, so they can be reviewed before editing `…-final.md`.

## 1. How this was produced

1. Read all three design docs (original, revised, final).
2. **Re-verified the ~21 load-bearing source claims (findings A–U)** against the checkout via 8 parallel source dives. The vast majority held exactly as written.
3. Grilled the design tree one decision at a time (Q1–Q10), exploring the source wherever a question could be answered by reading code.
4. Ran a **31-agent adversarial completeness sweep** over the eight un-grilled dimensions (injection, expand_out veto, schema_version, durability/GC, status rendering, goal_mode wiring, dispatch budget, created_cards/workspace). Every HIGH/CRITICAL candidate was adversarially re-verified against source before surfacing. Result: 17 confirmed/nuanced findings → grilled as Q11–Q13.

## 2. Opening factual corrections (no design change, fix the prose)

- **C1 — Durability justification is wrong.** §11 says `task_runs.metadata` is "GC'd (30-day default)." Source: there is **no `gc_runs`**; `task_runs` persist until hard-delete. Only `task_events` (and only for `done`/`archived` tasks) and worker logs are 30-day GC'd (`kanban_db.py:7191-7229`). The *decision* (durable state → `tasks` row) is safe; the stated reason is false. (See D below for the rewrite.)
- **C2 — "Mirrors native swarm idiom" is a variation, not a mirror.** The native swarm blackboard is read/written via structured `[swarm:blackboard]` *comments* + `latest_blackboard()`, and `decompose_triage_task` links the root as a **child of every child** so it auto-promotes back to `ready`. The spec's done-root-with-sentinel-assignee that is *never* re-promoted is a legitimate variation — say "variation," not "mirror" (`kanban_swarm.py:146-194`).
- **C3 — `protocol_violation` is immediate.** A worker that clean-exits (rc=0) without `kanban_complete` trips the breaker on the **first** occurrence (`failure_limit=1`), emitting `gave_up` (`kanban_db.py:5346-5427`). Finding P's "recoverable" framing is true (auto-recovers when conditions change) but it blocks immediately, not after the default 2.

---

## 3. Decisions (accepted)

### A. Scope cuts — smaller, safer 0.1.0

**A1 ✓ — Cut `verify.command` + `retry` to 0.2.x; keep the veto + `expand_out` + commit-clean. (Q11)**
- **Problem (CRITICAL, confirmed):** `verify: { command: "${params.test_cmd} ${t.file}" }` interpolates LLM-emitted `t.*` (untrusted) into a string run via `subprocess.Popen([bash, "-c", cmd])` (`tools/environments/local.py:544-556`, `tools/process_registry.py:596-597`). `t.file = "x.py; rm -rf ~"` ⇒ arbitrary code execution on every fan-out. No escaping anywhere; "templating is bounded" is a *scope* statement, not a safety guarantee.
- **Decision:** `verify.command` is the **only** veto precondition that runs untrusted input through a shell. `expand_out` (pure data check) and commit-clean (fixed `git -C <engine-derived-worktree> status`) carry no untrusted interpolation. Cut `verify.command` + `retry` to 0.2.x; **keep the veto mechanism + `expand_out` (shape + width cap A4) + commit-clean.** Reject `verify.command`/`retry` in a 0.1.0 template at `workflow_start` with a "0.2.x" fail-fast. 0.2.x re-introduces command verification with injection-hardening (value-charset validation + `shlex`/argv) behind a dedicated spike, slotting into the same already-built veto.
- **Cascade:** this single cut also **retires Q1** (verify-timeout vs claim TTL — commit-clean's git call is fixed/fast; keep a small fixed timeout as hygiene) **and Finding C / `goal_mode` wiring** (`retry: N` was the verify budget; commit-clean/`expand_out` blocks are simple "fix-and-recomplete" in the normal agent loop, no `goal_mode`/`goal_max_turns` to set).
- **Cost:** examples soften — `fix-flaky-tests` loses its `verify` block (the fix worker still self-tests and commits, commit-clean guarantees the commit, the human gate reviews — no worse than a vanilla Hermes worker). Soften §15's "deterministic verification" claim to "shape + commit-clean are the 0.1.0 deterministic gates."

**A2 ✓ — Gate resolution = `approve` + `abandon`; drop the manual `reject`/`modify` runbook. (Q4)**
- **Problem:** §11's 0.1.0 "manual board-op runbook" for `reject`/`modify` relocates the exact R3/R4 hazards (load-bearing re-wire ordering; over-archiving shared DAG nodes) onto an unguarded human procedure — and even the flagship examples aren't clean trees (`report needs [approve, fix]` makes the fix cards shared parents).
- **Decision:** 0.1.0 = `approve` (orchestrator CLI completes the gate — proven: swarm completes a never-claimed `ready` card; orchestrator may complete any card) **+ a new `abandon` command**: enumerate every card with this run's root sentinel and **archive the whole run, leaves-first**, after a `kanban_comment` audit on the gate/root. Whole-run archive is hazard-free (no "outside" node to mis-promote); leaves-first prevents transient `ready` promotion. Then relaunch fresh. Granular `reject`/`modify` → 0.2.x engine commands (R3/R4-hardened). Archiving is reachable via `hermes kanban archive` (`kanban.py:_cmd_archive` → `kb.archive_task`).

**A3 ✓ — Codex lane uses the BUNDLED skill via `card.skills`; don't re-ship. Spike 3 → 0.2.x prerequisite. (Q6)**
- **Problem:** §10 lists the lane skill *inside* the plugin ("re-shipped for self-containment"), which makes it a plugin-namespaced skill and re-triggers the unresolved Spike 3 (can `card.skills` force-load a plugin-namespaced skill?).
- **Decision:** Force-loading a **bundled** skill via `card.skills` is already proven — Hermes' review dispatch sets `claimed.skills = ["sdlc-review"]` and force-loads it via `--skills` (`kanban_db.py:6088-6139`), and `kanban-codex-lane` already ships bundled (`skills/autonomous-ai-agents/kanban-codex-lane/`). So set `card.skills = ["kanban-codex-lane"]` against the **bundled** skill — no Spike 3 dependency. Document the honest cost: 0.1.0 requires a Hermes that bundles `kanban-codex-lane` (a version coupling). **Spike 3 is demoted from a 0.1.0 blocker to a 0.2.x prerequisite** (it only bites for the claude-code lane, which Hermes doesn't bundle, and any re-shipped skill). Mental model to bake into §15: the codex "lane" is a normal LLM worker that *drives* `codex` as a subprocess and then completes — codex never touches the board.

### B. Correctness / mechanism fixes

**B1 ✓ — Race-freedom is R5 (atomic create), not dispatcher timing; reconcile = re-run-graph + create-missing + dedup. (Q2)**
- **Evidence:** `create_task` validates parent existence (`_find_missing_parents`, `kanban_db.py:2235-2245`) ⇒ children-before-join is API-forced; and it computes initial status atomically from *current* parent statuses (`kanban_db.py:2155-2168`). So the join's status is correct whether 0, some, or all children have completed by the time it's created.
- **Decision:** State the invariant as **R5 (a single `create_task` carrying the complete child set)** and retire "before any instance can complete" as the *justification* — it's a true side-effect, not the mechanism. The real crash mode is **partial fan-out** (the fail-open hook dies mid-fire ⇒ *missing* cards), so **`reconcile`'s primary contract is "re-run the graph function and create the missing cards," with dedup as the secondary pass** — not dedup-only. Inputs survive a total crash: source metadata on `task_runs.metadata` (never GC'd) + the template snapshot in the root body. The per-child sentinel `idempotency_key` is a cheap sequential dedup; the **sentinel-identity reconcile is the real exactly-once guard** (native `idempotency_key` is racy/out-of-txn — `kanban_db.py:2106-2119`, comment: "Race is acceptable").

**B2 ✓ — Non-spawnable sentinel = leading-underscore (collision-proof); `workflow_status` is the only gate signal. (Q3)**
- **Evidence:** `done` cards are never dispatch candidates (only `ready`/`review`: `kanban_db.py:5742/5863`, `5768/6099`) ⇒ the root's non-spawnability comes from its `done` status; the **gate** (a `ready` card) depends on the sentinel assignee → `skipped_nonspawnable` (silent, `kanban_db.py:5978-5986`). `profile_exists` returns `False` (never raises) for a non-existent name (`profiles.py:307-312`, `normalize` only raises on empty `:251-266`), and `validate_profile_name` forbids a leading underscore (`:286`, regex `^[a-z0-9][a-z0-9_-]{0,63}$`).
- **Decision:** Use a **leading-underscore sentinel assignee** (e.g. `_workflow_gate`, `_workflow_root`) for every non-worked card. It is reliably `skipped_nonspawnable` *and* impossible to ever collide with a real profile (Hermes can't create one) — replacing the spec's point-in-time collision validation with a structural guarantee. Never leave such a card unassigned (a board `default_assignee` would auto-assign and spawn it — `kanban_db.py:5940+`). Because `skipped_nonspawnable` is **silent** (suppressed "stuck" telemetry by design), **`workflow_status` is the sole "AWAITING APPROVAL" signal** — Hermes will not surface it.

**B3 ✓ — R2 winner: multi-`done` tiebreak; re-wire = link-winner-then-archive-loser (no `unlink`, no single-txn). (Q7)**
- **Evidence:** there is **no model-facing `kanban_unlink`** (tools: show/list/complete/block/heartbeat/comment/create/unblock/link); edge-removal exists only as `kb.unlink_tasks` / `hermes kanban unlink` (`kanban_db.py:2409`, `kanban.py:497`). `link_tasks`/`archive_task` each own their `write_txn` — they cannot be composed into one without raw SQLite (forbidden).
- **Decision:** Three corrections to the R2 mechanism (intent unchanged):
  1. **Multi-`done` tiebreak.** Two duplicate children can both be claimed and completed, so "done wins unconditionally" must disambiguate among ≥2 dones (`task_runs.id` → `created_at` → `min(card_id)`), and note that a discarded `done` duplicate **orphans its branch/worktree**.
  2. **Re-wire = `kanban_link(winner→join)` then archive loser** — no `unlink` needed (the archived loser is a *satisfied* parent for `recompute_ready`, so its dangling edge is harmless). Most duplicates are leaf-dups where the join was wired to the kept card ⇒ no re-wire at all.
  3. **Drop "one `write_txn` with compare-and-set."** Use an ordered two-step (link-winner → archive-loser); it's safe because the loser stays an *unsatisfied* parent until archived, and convergence under concurrency comes from the deterministic winner + idempotent ops — **best-effort**, may waste a little work.

**B4 ✓ — Worktree pre-provisioning: engine, idempotent, base-pinned; template `worktree:` → card `dir:`. (Q5)**
- **Evidence:** Hermes does **not** auto-create worktrees (`resolve_workspace` returns the path; `kanban_db.py:4615-4625`); `dir:` is `mkdir`'d; only `scratch` is cleaned (`_cleanup_workspace:3766-3807`); no auto-commit/merge.
- **Decision:** Baseline **(A)** — engine pre-provisions in the fan-out hook, with: deterministic worktree path/branch from the sentinel identity (idempotent reuse-if-exists, survives hook-refire and reconcile); **provision-then-create per child** (a failed provision ⇒ missing card → reconcile, never a card pointing at a missing worktree); **base ref pinned in provenance** at `workflow_start`; tolerate `git index.lock` contention (brief retry; hook primary, reconcile backstop); cleanup is documented operator work. State the implicit translation explicitly: template `worktree:` ⇒ engine provisions ⇒ card is `dir:<provisioned-path>`. **Add (B) to Spike 3 as the preferred target:** `on_session_start` exists (`plugins.py:127-167`), so if spawn-cwd timing allows, each worker provisions its own worktree at startup (1 op/worker, out of the fail-open hook). Reject (C) LLM-driven provisioning.

**B5 ✓ — `expand_out.max` width cap (~50), veto-enforced at the source. (Q8)**
- **Evidence:** `build_worker_context` surfaces **all** done direct parents, **no count/total cap**, ~4 KB/field ≈ 8 KB/parent (`kanban_db.py:6789-6825`, `_CTX_MAX_FIELD_BYTES`). The spec says "the plugin must own width-limiting" but defers the only named mechanism (aggregator).
- **Decision:** Keep the aggregator deferred (YAGNI), but add a **veto-enforced `expand_out.max`** (default ~50, per-template overridable): the source-stage veto blocks completion if `len(items) > max`. One check bounds three problems — fan-in context (N×8 KB), the synchronous N-create hook cost, and worktree sprawl. Document the per-parent context cost.

**B6 ✓ — Override the review-block habit via the card body; review-column collision is low-risk. (Q10)**
- **Evidence:** the auto-loaded kanban-worker skill teaches coding workers `kanban_block("review-required: …")` rather than complete (`skills/devops/kanban-worker/SKILL.md:50`). A workflow coding stage following that habit would block instead of completing → the join (promotes only on all-parents-`done`/`archived`) never advances → run stalls, defeating the single-gate design. Separately, `status='review'` is *not* entered by default workers (no tool sets it; only dashboard-drag or sdlc flow), so the §14 review-column collision is low-risk.
- **Decision:** Engine **prepends a workflow-stage lifecycle preamble to every stage card's body** ("complete via `kanban_complete`; emit declared metadata; commit before completing; do NOT block for review — the workflow's gate handles that"). Use the **body**, not a `workflow-stage` *skill*, to stay Spike-3-free (a new plugin skill would re-trigger Spike 3). A proper bundled `workflow-stage` skill → 0.2.x. Residual deviation is caught by reconcile's diagnosis + operator unblock; do **not** intercept `kanban_block` in the veto. Close §14's review-column question as low-risk/documented (never give stages `sdlc-review`; never enter `review` status).

**B7 ✓ — Worker-side `schema_version` gate in hook + veto; visible refuse, never a swallowed raise. (Q12)**
- **Problem (CRITICAL, confirmed):** §2's "never a silent mis-drive" is unimplemented. The hook and veto run in the **worker's** process under its profile's `HERMES_HOME` (`_default_spawn` sets it; `kanban_db.py:6468`), loading the worker profile's plugin version — which can differ from the orchestrator's stamped `schema_version` (realistically via a mid-run `pip --upgrade`). The hook's self-gate checks only the sentinel; `workflow_start` checks enablement, not version. And because the hook is fail-open with swallowed exceptions, a version-mismatched hook that `raise`s is *silently* dropped.
- **Decision:** **Stamp the plugin version (not just `schema_version`) in provenance**; the plugin declares its supported-`schema_version` set at load. **Add a `schema_version` check to the hook's self-gate and the veto** (both read the root provenance via `kanban_show`). On mismatch → **visible refuse, not a raise**: the hook posts a `kanban_comment` on the **root** (cross-task commenting is unrestricted, author forced — `kanban_tools.py:705-706`; visible on dashboard *and* in downstream worker context) and declines to fan out; the veto **blocks** the completion with the mismatch message. Keep "drain before upgrade" as the primary operational control; this worker-side gate is what makes the §2 claim true. Cheap — the hook already reads provenance.

### C. Hardening / process

**C-pf ✓ — Per-profile pre-flight = a spawned loadability probe per distinct profile. (Q9)**
- **Evidence:** the only config-level CLI (`plugins list`) is **config-only** — it cannot see whether a plugin actually *loaded* (vs. is merely enabled), let alone the load error. In-process truth lives in `get_plugin_manager()._plugins[...].enabled/.error` (`plugins_cmd.py:1479-1490`), which only exists inside a process under that profile's `HERMES_HOME`.
- **Decision:** `workflow_start`'s pre-flight **spawns a loadability probe per *distinct* bound profile** (deduped): each runs `discover_plugins()` under that profile's home and reports `hermes-workflow`'s `LoadedPlugin.enabled`/`.error` (codex profiles also confirm the bundled lane skill resolves + the `codex` binary). Derive remediation from the probe: not-enabled → `plugins enable`; enabled-but-`.error` → surface the load error (don't say "enable"). Fail-fast, zero cards on failure. Reconcile's "done, downstream absent ⇒ probable not-enabled" stays a *probable* hint; the cause-agnostic repair (re-run-graph) is automatic (B1).

### D. Doc / clarity corrections (Q13 batch)

**D1 ✓ — Durability wording.** Rewrite §11: *"durable state lives in the `tasks` row (body/status), persisting until hard-delete; `task_runs.metadata` also persists indefinitely (no time-GC); only `task_events` (done/archived tasks) and worker logs are 30-day GC'd."* (`kanban_db.py:7191-7229`; no `gc_runs`.)

**D2 ✓ — Enumeration.** Fix §10:246 — `workflow_status` enumerates via **link-walk from the root** (`kanban_show` → body+children+sentinels; O(N) shows for an N-card run, fine on-demand). `kanban_list` returns **no body** (`_task_summary_dict`, `kanban_tools.py:309-332`) and no run-filter, so it's for board-wide sweeps (reconcile), not run enumeration. (§5:122 is already correct.)

**D3 ✓ — Path/workspace/body.**
- Expand-vars **forbidden in `workspace:` paths** (the per-child worktree path is engine-derived per B4, so they're unnecessary; only `${params.*}`, `normpath`'d + containment-checked) — eliminates the path-traversal vector. (Carries over from Q11; kept after the A1 cut.)
- Add the **workspace-inheritance rationale** to §9: a hook `kanban_create` that omits workspace inherits the *source* worker's workspace (`kanban_tools.py:788`), so the engine sets explicit `workspace_kind/path` on every hook create (rule already at §6:123).
- **Body is Markdown**: dashboard escapes HTML and whitelists link schemes (no XSS); cosmetic escaping deferred.

**D4 ✓ — Dispatch budget.** Document that a wide fan-out (≤ `expand_out.max`) bound to one profile **serializes at that profile's concurrency cap** (fine, bounded) but can **starve co-resident runs** sharing it; mitigations: the B5 width cap, `--board` isolation, and a dedicated fan-out profile. (Note the Hermes quirk that review-status dispatch bypasses the per-profile cap — `kanban_db.py:5993-5999` vs `6088-6162` — but workflow stages never use `review` status per B6, so it doesn't affect us.)

---

## 4. Net effect on the 0.1.0 spine

**Kept:** declarative versioned template → lazy single-level fan-out → race-free join (R5) → human gate (`approve`/`abandon`) → bundled codex lane → engine-provisioned worktrees → reconcile (re-run-graph + R2 dedup); `expand_out` (shape + `max`); commit-clean veto; per-profile loadability pre-flight; worker-side `schema_version` gate; body lifecycle preamble; non-spawnable leading-underscore sentinel; `workflow_status` as the gate signal.

**Removed from 0.1.0:** `verify.command` + `retry` (→ 0.2.x); the verify-timeout/heartbeat machinery; `goal_mode`/`goal_max_turns` wiring; the manual `reject`/`modify` runbook; the re-shipped lane skill.

**Deferred to 0.2.x:** command-based verification (injection-hardened); granular `reject`/`modify` engine commands; the claude-code lane; a bundled `workflow-stage` skill; the fan-in aggregator; nested fan-out; and everything already deferred in §13. **Spike 3** now gates 0.2.x only.

## 5. New build & spike items this created

- `abandon` command (whole-run, leaves-first, audited). [A2]
- Worker-side `schema_version`/version gate in hook + veto, with visible-refuse. [B7]
- `expand_out.max` width cap (+ value-charset validation deferred with `verify.command`). [B5, A1]
- Card-body lifecycle preamble injected per stage. [B6]
- Spawned loadability-probe pre-flight (per distinct profile). [C-pf]
- Idempotent, base-pinned worktree provisioning; evaluate `on_session_start` provisioning in **Spike 3**. [B4]
- Reconcile as re-run-graph + create-missing + dedup. [B1]

## 6. Spec-edit checklist (to apply to `…-final.md`)

- [ ] §2 — add the worker-side version-gate mechanism behind "never a silent mis-drive" [B7].
- [ ] §5.5 / §7 — remove `verify.command` + `retry` from the 0.1.0 veto/DSL; keep `expand_out` (+ `max`) and commit-clean; add the `workflow_start` rejection of `verify`/`retry` [A1, B5].
- [ ] §5.6 / §11 — replace manual `reject`/`modify` with `approve` + `abandon` [A2].
- [ ] §5.2 / §5.7 — reframe race-freedom as R5; redefine reconcile as re-run-graph + create-missing + dedup; fix R2 winner (multi-done tiebreak, link-winner-then-archive, drop single-txn/CAS) [B1, B3].
- [ ] §5.4 / §11 — leading-underscore sentinel; `workflow_status` as the sole gate signal [B2].
- [ ] §7 — `worktree:`→`dir:` translation; forbid expand-vars in `workspace:`; `expand_out.max`; rewrite "Templating is bounded" as safety + scope [B4, B5, D3].
- [ ] §9 — workspace-inheritance rationale; body lifecycle preamble; pre-flight = loadability probe [D3, B6, C-pf].
- [ ] §10 — bundled (not re-shipped) lane skill; fix `workflow_status`→link-walk; drop the `workflow-stage`/lane-reship implications [A3, D2].
- [ ] §11 — durability rewrite; fan-out-vs-cap note [D1, D4].
- [ ] §13 — move to 0.2.x: `verify.command`/`retry`, `goal_mode` wiring, manual reject/modify, re-shipped skill; keep Spike 3 as 0.2.x-only [A1, A2, A3].
- [ ] §14 — close the review-column open question (low-risk); add Spike-3 `on_session_start` provisioning; drop the obsolete verify-timeout spike [B6, B4, A1].
- [ ] §15 — soften "deterministic verification" to "shape + commit-clean"; clarify the codex-lane mental model [A1, A3].
- [ ] Findings table — note the `verify.command` shell-exec path and the `task_runs`-not-GC'd correction [A1, D1].

## 7. Key source references the decisions rest on

- Hooks: `model_tools.py:928-943` (pre_tool_call block), `:995-1006` (post fires in-process incl. failures, return ignored, exceptions swallowed); `plugins.py:467-494` (`dispatch_tool` bypasses hooks), `:127-167` (`VALID_HOOKS` incl. `on_session_start`), `:1554-1568` (no per-hook timeout).
- Ownership/tools: `kanban_tools.py:132-161` (`_enforce_worker_task_ownership`; on complete/block/heartbeat at `:483/605/651`), `:705-706` (comment unrestricted), `:862-881` (link no guard), `:309-332` (`kanban_list` no body), `:415-417` (`kanban_list` orchestrator-only), `:339-362` (`kanban_show` body+parents+children).
- State machine: `kanban_db.py:2143-2174`+`2235-2245` (`create_task` parent-existence + atomic status), `:2106-2119` (racy idempotency), `:2356-2383` (`link_tasks` no recompute, demotes), `:2409` (`unlink_tasks`, no tool), `:2858-2908` (`recompute_ready`), `:3576-3586` (`complete_task` source statuses, no rollup), `:2939-2955`+`:111` (claim re-check, 900s TTL), `:4486-4508` (`archive_task` → `recompute_ready`).
- Dispatch/spawn: `:5742/5863`+`:5768/6099` (ready/review candidates only), `:5978-5986` (`skipped_nonspawnable`), `:5993-5999` vs `:6088-6162` (per-profile cap in ready, not review), `:6088-6139` (review force-loads `sdlc-review` via `card.skills`), `:6452+` (`_default_spawn` always `hermes chat`), `:6468` (`HERMES_HOME` = assignee profile).
- Workspaces/context: `:4615-4625` (worktree not auto-created), `:3766-3807` (cleanup preserves worktree/dir), `:6789-6825`+`:182` (fan-in: all done direct parents, ~8 KB each, no cap), `:7191-7229` (gc_events/logs only; no gc_runs).
- Escalation: `:5346-5427` (protocol_violation, failure_limit=1), `:2786-2822`+`:5557` (blocked vs gave_up), `:4692` (`DEFAULT_FAILURE_LIMIT=2`); `goals.py:876-886`+`:47` (budget exhaustion → block; `DEFAULT_MAX_TURNS`).
- Profiles: `profiles.py:307-312` (`profile_exists`), `:251-266` (`normalize`), `:286` (regex forbids leading `_`).
- Shell exec: `tools/environments/local.py:544-556`, `tools/process_registry.py:596-597` (`Popen([bash,"-c",cmd])`).
- Prior art: `kanban_swarm.py:146-194` (done-root blackboard via comments; join-as-child `create_task(parents=worker_ids)`); bundled `skills/autonomous-ai-agents/kanban-codex-lane/`; `skills/devops/kanban-worker/SKILL.md:50` (review-required block habit).
