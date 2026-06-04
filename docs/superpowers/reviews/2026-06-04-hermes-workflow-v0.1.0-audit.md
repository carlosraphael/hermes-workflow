# hermes-workflow v0.1.0 — Release-Readiness Audit

- **Date:** 2026-06-04
- **Target:** tag `hermes-workflow-v0.1.0` (`d7fef01`) on branch `workflow/0.1`; 117 tests passing.
- **Method:** 21-agent adversarial audit (10 dimensions × find→verify + synthesis) grounded in three sources of truth — the final spec, the **real Hermes v0.15.1 source** (`/Users/carlos/cortex-workspace/hermes-agent` @ `c47b9d12`), and the committed code. Only `status="confirmed"` findings are reported (1 false-positive dropped: D1-04, folded into D1-01).
- **CRITICAL independently re-verified** by reading `hermes-agent/hermes_cli/plugins_cmd.py:705-728` (`_plugin_exists` is entry-point-blind) and `plugins.py:1171-1173` (loader honors `plugins.enabled` by key/name regardless of source).

---

## 1) VERDICT

**DO-NOT-SHIP** — 1 CRITICAL + 2 HIGH must be fixed first. The suite is green but does not cover the two HIGH fail-open/fail-silent regressions, and the CRITICAL blocks the only documented activation path.

## 2) MUST-FIX-BEFORE-RELEASE (CRITICAL + HIGH)

| Severity | Title | Location | One-line fix |
|---|---|---|---|
| **CRITICAL** (D7-001) | Documented `hermes plugins enable hermes-workflow` fails for the pip/entry-point distribution (`_plugin_exists()` is entry-point-blind → `sys.exit(1)`); yet the loader honors `plugins.enabled` by key/name | dead command emitted at `README.md:50`, `docs/operations.md:42`, `hermes_workflow/tools.py:52-59` (`_remediation`); root cause `hermes-agent/hermes_cli/plugins_cmd.py:658-660,705-728` vs loader `plugins.py:1171-1173` | Stop relying on `plugins enable` for an entry-point plugin. Document adding `hermes-workflow` to each bound profile's `config.yaml` `plugins.enabled` list (or installing it as a user directory plugin so `_plugin_exists` sees it), and update README:50, operations.md:42, and `_remediation()` to emit that instead. |
| **HIGH** (D1-01) | `-->` in author-controlled template content corrupts sentinel/snapshot serialization (breaks identity, version-gate, reconcile) | `hermes_workflow/engine/provenance.py:31-60` | Make serialization total against the `-->` terminator: base64-encode the embedded JSON payload (decode in extract/parse), or read a full delimited line instead of `find('-->')`. Add roundtrip tests with `-->` in `template_id`, `template_version`, and `template_yaml`. Optional defense-in-depth: reject `-->` at template validation. |
| **HIGH** (D6-01) | `on_tool_pre`'s own hook-level fail-closed `except` is never tested — only the pure gate is. A refactor could flip the **only blocking channel** fail-OPEN with every test still green | `hermes_workflow/hooks.py:114-115`; tests `tests/unit/test_veto.py:36-41`, `tests/integration/test_veto_hook.py` | Add an integration test on a real seeded card that monkeypatches `parse_root_body`/`_stage_gate_inputs` to raise after sentinel resolution, asserting `on_tool_pre` returns `{"action":"block",...}` — never `None`, never an exception. |

## 3) SHOULD-FIX (MEDIUM) / NICE-TO-HAVE (LOW·INFO)

**MEDIUM**
- **D8-01** — base-ref never pinned in provenance; fan-out worktrees branch from live HEAD, not the commit at `workflow_start` (a locked 0.1.0 decision). Capture `git rev-parse HEAD` at start, store in `CompiledSnapshot`, thread through `materialize()`. (`provenance.py:22-29,49-53`, `worktree.py:56`, call sites `tools.py:116,274`, `hooks.py:85`.)
- **D3-01 / D3-03** — `workflow_start` post-probe block + `cli_dispatch` are not exception-proof (a bad `--template` path or worktree-provision failure dumps a raw traceback). Wrap `workflow_start`'s create/complete/materialize in try/except (mirrors the guarded reconcile path `tools.py:271-277`) and broaden CLI/slash `except`. (`tools.py:98-117,617-621,635-639`.)
- **D6-02** — abandon "reclaim running workers FIRST" branch (`tools.py:397-402`) is never exercised. Add a test: `kb.claim_task` a fan-out card to running, then `workflow_abandon`, assert reclaim + full archive.
- **D6-03** — post-hook success self-gate never asserted for a *failed* `kanban_complete`. Add: feed `{"ok":false}`/`{"error":...}` to a real sentinel card, assert no fan-out. (`hooks.py:56-58`.)

**LOW / INFO** (batch into a hygiene pass or defer to 0.1.1)
- D1-02 — `expand_out` source on `scratch` not rejected (`template.py:86-87`); extend the scratch guard to `s.expand_out`.
- D1-03 — gate value not constrained to `human` (`template.py:56-60`, `graph.py:90`); reject non-`human` gate values.
- D3-02 — `slash_dispatch` narrow `except`; broaden to `except Exception` for a flat-JSON error. (`tools.py:635-639`.)
- D3-04 — `_workflow_gate` literal duplicated (`graph.py:7` / `version.py:5`); import the constant or assert equality.
- D3-05 — review-required backstop reads the 50-event-capped `kanban_show` tail (`tools.py:157-169`); read the block reason from the uncapped `runs` list instead.
- D4-001 — reconcile dedup re-wire uses the `kanban_link` model tool, not host `kb.link_tasks` as SPIKES.md/§5.7 state — functionally fine; update the docs (`SPIKES.md:531-532`, spec §5.7).
- D5-01 — workspace params not `normpath`'d / containment-checked despite the spec promise (`template.py:82-85`, `materialize.py:123-125`).
- D7-002 — example templates not shipped in the wheel; README quickstart `--template examples/...` is checkout-relative (`pyproject.toml:18`).
- D7-003 — wheel METADATA lacks Summary/README/License/classifiers/authors (`pyproject.toml:5-15`).
- D10-1 — `package-data` glob `skills/*/SKILL.md` would drop future non-SKILL.md skill assets; broaden to `skills/**/*`.
- D9-01 / NEW-D9-02 — `project_plugin` is dead plumbing (`tools.py:89`, `preflight.py:73,100-101`); document pip-only scope or remove the parameter.
- INFO — D2-01/D2-02 (tighten the post-hook success gate to positive `parsed.get("ok") is True`), D5-03/04/05 (injection / sentinel-collision / version-gate-forgery surfaces verified **clean**), D1-04 (false-positive, no action).

## 4) CONFIRMED SOLID (do not re-litigate)

- **A1 shell-injection CUT**: every `subprocess.run` uses fixed argv lists, no shell, no untrusted interpolation (`veto.py:76-79` commit-clean = fixed `["git","-C",dir,"status","--porcelain"]`; `worktree.py:57` engine-derived branch; `preflight.py:103` = `[sys.executable,"-m",...]`). `verify.command`/`retry` rejected at `template.py:68-69`.
- **No raw SQLite anywhere** in `hermes_workflow/`; all mutations via `ctx.dispatch_tool` (WorkerBoard) or host `kb.*` (HostBoard).
- **Engine purity**: `engine/*` + `lanes/presets.py` import only stdlib + PyYAML + intra-package; nothing from Hermes.
- **post_tool_call fail-open**: whole body in one try/except that logs+swallows, never raises; self-gates on `tool==kanban_complete` + success + sentinel; version-mismatch comments on root and returns before fan-out (`hooks.py:52-87`).
- **pre_tool_call fail-closed**: returns a block dict on ANY internal error, never `None`/raise; `_check_expand_out` is a total shape-check (`hooks.py:98-115`, `veto.py:27-66`).
- **Hermes coupling**: `invoke_hook` swallows raising callbacks (`plugins.py:1556-1567`); `get_pre_tool_call_block_message` blocks only on a returned dict (`plugins.py:1698-1707`) — returning the block dict is the only correct mechanism, and it is honored.
- **Sentinel security**: leading-underscore assignees can't be real profiles → `skipped_nonspawnable`; default-assignee auto-spawn fires only on empty assignee; `kanban_complete` ownership-scoped; `workflow_approve` orchestrator-only; the version-refuse comment author is forced by Hermes (cannot be forged).
- **Reconcile correctness**: `pick_winner` tiebreak (done / run_id / created / min-id) verified; RunView latest-done converges.
- **Idempotency**: `materialize` uses `_idem(root_id, identity)`; `provision_worktree` is reuse-if-exists.
- **Packaging sanity**: wheel builds; entry point resolves to `hermes_workflow`; `register` callable; `plugin.yaml` + both `skills/*/SKILL.md` ship; tag == `workflow/0.1` HEAD; versions agree across `version.py` / `pyproject.toml` / `plugin.yaml`.

## 5) RECOMMENDED FIX ORDER

1. **D7-001 (CRITICAL)** — fix the activation docs + `_remediation()` (and decide the canonical activation mechanism). Without it the plugin can't be loaded by any documented means. Pure docs/string change.
2. **D1-01 (HIGH)** — make `provenance.py` serialization total against `-->` (subsumes D1-04 and most of D5-02). Self-contained engine change + roundtrip tests.
3. **D6-01 (HIGH)** — add the fail-closed test for `on_tool_pre`'s own except branch; pins the only blocking channel so steps 2 (and future refactors) can't flip it open.
4. **D3-03 → D3-01/D3-02 (MED/LOW)** — one internal try/except in `workflow_start` fixes the raw-traceback path across tool/CLI/slash.
5. **D8-01 (MED)** — pin base-ref in provenance (restores fan-out determinism across HEAD drift / reconcile re-provision).
6. **D6-02 / D6-03 (MED)** — add the abandon-reclaim and post-hook-failure tests.
7. **Batch the LOW/INFO** items, or defer to 0.1.1.

## 6) TEST GAPS the fix session MUST close

1. Blocking-channel fail-closed: drive `on_tool_pre`'s own `except` (monkeypatch to raise after sentinel resolution) → asserts block dict (D6-01).
2. `-->` serialization roundtrip in `template_id`/`template_version`/`template_yaml` (D1-01).
3. Abandon reclaim-running-first (`kb.claim_task` → running → abandon) (D6-02).
4. Post-hook failed-`kanban_complete` self-gate → no fan-out (D6-03).
5. Sentinel non-spawnability vs `kanban_db.dispatch_once(dry_run=True)` → `skipped_nonspawnable` (D6-04).
6. `LIFECYCLE_PREAMBLE` present on materialized bodies (D6-05).
7. Gate-less consumer stays `todo` until all fan-out instances done (D6-06).
8. Raw-SQLite regression meta-test walking `hermes_workflow/*.py` (D6-07).
9. Base-ref pinning across a simulated HEAD move (supports D8-01).
10. CLI/slash error contract: bad `--template` / missing repo → flat `{"error":...}` not a traceback (D3-01/02/03).

---

*Provenance: audit workflow run `wf_c0650497-26f`. Full per-dimension findings (including false-positives and the adversarial-verifier reasoning) are in that run's transcript.*
