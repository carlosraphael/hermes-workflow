# Changelog

All notable changes to `hermes-workflow` are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0/).
Versions refer to the **distribution** `hermes-workflow`; the run-snapshot
`SCHEMA_VERSION` (`0.1`) is tracked separately in
[`src/hermes_workflow/version.py`](src/hermes_workflow/version.py).

## [Unreleased]

### Changed

- **`tools.py` split into cohesive modules (SRP).** The 779-LOC `tools.py` is
  decomposed so every module lands well under the 400-LOC target: the tool JSON
  schemas move to `schemas.py`; the `COMMANDS` descriptor table + CLI/slash
  dispatch to `cli.py`; the duplicate-collapse board executor
  (`_relink_created_to_joins` / `_enumerate_cards` / `_card_node` /
  `_collapse_duplicates` / `_host_board`) to `reconcile_exec.py`, pairing with the
  pure `engine/reconcile.py`; `_remediation` to `preflight.py` and
  `_orphaned_branches` to `worktree.py` (cohesive, purity-preserving homes).
  `tools.py` keeps only the six `workflow_*` functions and their small helpers.
  Pure structural move — no behaviour change, no new tools, every invariant intact
  (the no-raw-SQLite meta-test's only edit is its docstring pointer to the
  relocated `_host_board`).
- **The workflow command set is now defined once.** A single frozen `COMMANDS`
  descriptor tuple (one `Command` per tool: `name`, `fn`, `schema`,
  `bind`, `positional`, `cli_args`) replaces the four parallel structures
  (`TOOL_SPECS`, the per-command `cli_setup` subparsers, the `_dispatch_ns`
  if/elif chain, and the duplicated `<start|status|…>` usage hint). Tool
  registration, the `hermes workflow <cmd>` CLI, and `/workflow` dispatch are all
  derived from it, so adding a tool touches exactly one descriptor. Pure
  structural refactor — no change to any tool's inputs, outputs, error strings,
  or the flat-error contract.
- **`engine/reconcile.py` deepened from a tiebreak into a duplicate-collapse
  planner.** A new pure `plan_collapse(template, nodes) -> CollapsePlan` decides
  the winner, the join re-link edges, the running-loser reclaims, and the
  archives over board-free `CardNode`s; `workflow_reconcile`'s executor only
  applies the returned plan. The collapse decision — winner selection, the
  idempotent relink-skip, and template-derived join detection (now sharing
  `_relink_created_to_joins`'s rule) — is unit-tested without a board.

### Fixed

- **`workflow_reconcile` no longer orphans a running duplicate's worker** — a
  running loser is reclaimed before its card is archived (matching
  `workflow_abandon`).
- **A board error mid-collapse no longer discards the pass** — `workflow_reconcile`
  returns a best-effort `failures` list (per-op isolation) and keeps its
  `created` / `relinked` / `deduped` progress instead of aborting on the first
  error.
- **A failed winner→join relink no longer prematurely promotes a join** — if any
  relink fails, the collapse now defers its whole retire phase (losers stay live)
  rather than archiving a loser whose join never gained the winner edge. An
  archived parent counts as *satisfied* by the board's ready-sweep, so archiving
  off a missing winner-edge would promote the join with no live producer; the
  deferral leaves the duplicate for the next, self-healing reconcile.

## [0.1.4] - 2026-06-05

Examples + documentation release. No plugin runtime behaviour changed.

### Changed

- **`build-hermes-plugin` example** rewritten as a dogfooding workflow that
  extends `hermes-workflow` itself with new `workflow_*` surfaces — params
  `repo` + `capability`; stages `spec → implement → integrate → test → review →
  report`; bodies cite the real "Adding a tool or hook" contract
  ([`AGENTS.md`](AGENTS.md)) with explicit files, the `metadata` return
  contract, and commit/scope instructions per stage.
- Quickstart and the bundled `workflow-author` / `workflow-orchestrator` skills
  retargeted off the removed `fix-flaky-tests` example.

### Added

- **`feature-delivery` example** — a generic, repo-agnostic feature-delivery
  SDLC: `design → implement (parallel worktrees) → integrate → test → review →
  ship (open PR)`.

### Removed

- `fix-flaky-tests` is no longer a shipped example; it now lives as the
  integration smoke fixture
  [`tests/integration/fixtures/fanout-smoke.workflow.yaml`](tests/integration/fixtures/fanout-smoke.workflow.yaml),
  decoupling the test suite from the example catalog.

## [0.1.3] - 2026-06-04

Governance and release-tooling release — first published to PyPI. No plugin
runtime behaviour changed.

### Added

- [`SECURITY.md`](SECURITY.md) — security policy: supported versions, a private
  GitHub Security Advisories reporting channel, and the plugin's design
  guarantees (no raw SQLite, injection-free fail-closed completion gate,
  fail-open fan-out, base64 provenance envelope, non-spawnable sentinels).
- GitHub issue forms (`bug_report`, `feature_request`, `config`) and a
  `pull_request_template.md` encoding the contribution checklist and the
  [`AGENTS.md#key-invariants`](AGENTS.md#key-invariants) gate.
- This `CHANGELOG.md`, backfilled to v0.1.0.
- [`.github/workflows/release.yml`](.github/workflows/release.yml) — builds
  sdist + wheel and publishes to PyPI on a `vMAJOR.MINOR.PATCH` tag via Trusted
  Publishing (OIDC, no stored token); every action SHA-pinned.

### Fixed

- Test isolation: `tests/integration/test_spike_preflight.py` now resets the
  process-global `PluginManager` singleton in a finalizer, so its
  `tmp_path`-bound discovery cache can't leak across tests in the single-process
  suite (Tier-3 test-convention audit, finding IN-01). No coverage change — 137
  tests still pass.

## [0.1.2] - 2026-06-04

### Changed

- Repackaged to a **src-layout**: importable code now lives under
  `src/hermes_workflow/`, so the test suite runs against the *installed*
  package rather than the working copy (`pyproject` resolves packages from
  `src/`). Pure import churn — no runtime behaviour change.

### Added

- Hermes-grade governance scaffolding: [`AGENTS.md`](AGENTS.md) (engineering
  guide + key invariants), [`CONTRIBUTING.md`](CONTRIBUTING.md),
  [`CONTEXT.md`](CONTEXT.md) (the distribution / import / plugin / runtime
  naming taxonomy), [`ADR-0001`](docs/adr/0001-standalone-dedicated-repo-plugin.md)
  (ship as a standalone dedicated-repo plugin), and a SHA-pinned
  [`ci.yml`](.github/workflows/ci.yml) running the unit suite on Python
  3.11–3.13.

## [0.1.1] - 2026-06-04

Hardening release: applies the fixes from the v0.1.0 release-readiness audit
(1 critical + 2 high), re-audited to SHIP.

### Security

- **Provenance envelope (`engine/provenance.py`):** base64-encode the sentinel
  and snapshot payloads so worker content containing `-->` can no longer
  truncate or forge the HTML-comment serialization (the base64 alphabet
  `[A-Za-z0-9+/=]` cannot contain `-->`).

### Fixed

- **Template validation:** reject non-human gate values and pin the gate
  assignee to the `SENTINEL_GATE_ASSIGNEE` constant, so human-gate cards stay
  non-spawnable.
- **`workflow_start`:** honour the flat-error contract when seeding the root
  and prefix, and on CLI / slash dispatch — failures return `{"error": …}`
  instead of leaking an exception.
- **Activation:** document that the plugin is enabled via the
  `plugins.enabled` *list* in each bound profile's `config.yaml` (not
  `hermes config set`, which writes a scalar and breaks the loader).

### Added

- **Worktree determinism:** pin the worktree `base_ref` at `workflow_start`
  and carry it in the compiled snapshot, so fan-out children provision from a
  stable base.
- Tests closing the §6 coverage gaps: `pre_tool_call` fail-closed on internal
  error, sentinel non-spawnability, the lifecycle preamble, the gate-less
  join, abandon reclaim-running-first ordering, the post-hook failed-complete
  self-gate, and a `test_no_raw_sqlite` meta-test.

## [0.1.0] - 2026-06-04

Initial release: a declarative, versioned, multi-stage workflow primitive
over the Hermes Kanban board, shipped as a standalone (entry-point) plugin.

### Added

- **Engine (pure, no board):** YAML template data model + parser; template
  validation (roles, cycles, nested-fanout rejection, `verify`/`retry`
  rejection, workspace safety); bounded `${params.*}` / `${expand-var.*}`
  interpolation; the `cards_for_run` graph (dynamic-free prefix, single-level
  fan-out, joins, idempotent); progress-aware reconcile winner; and the
  provenance layer (sentinels, compiled snapshot, total version gate).
- **Board integration:** the `WorkerBoard` / `HostBoard` adapter pair; `RunView`
  link-walk enumeration with identity resolution and completed-metadata; and
  the materializer that turns engine `CardSpec`s into real board cards
  (sentinel + lifecycle preamble, explicit workspace, idempotency key,
  join-wired). Idempotent, base-pinned worktree pre-provisioning.
- **Hooks:** the `post_tool_call` fan-out driver (version-gated, fail-open,
  never raises) and the `pre_tool_call` completion gate (`expand_out` shape +
  `max`, commit-clean, version; fails closed).
- **Tools:** the six orchestrator-facing `workflow_*` tools — `workflow_start`
  (validate, reject `verify`, per-profile pre-flight, seed root + prefix),
  `workflow_status`, `workflow_validate`, `workflow_reconcile`,
  `workflow_approve`, and `workflow_abandon` (reclaim-then-archive
  leaves-first, orphan audit) — plus CLI (`hermes workflow`) and slash
  (`/workflow`) surfaces.
- **Skills:** the bundled `workflow-author` and `workflow-orchestrator` skills,
  and the `codex` lane preset (reusing Hermes' bundled `kanban-codex-lane`).
- **Examples:** the `fix-flaky-tests` and `build-hermes-plugin` templates.
- **Packaging:** entry-point plugin (`hermes_agent.plugins`); the wheel ships
  `plugin.yaml` and the bundled skills via `package-data`.

[Unreleased]: https://github.com/carlosraphael/hermes-workflow/compare/v0.1.4...HEAD
[0.1.4]: https://github.com/carlosraphael/hermes-workflow/compare/v0.1.3...v0.1.4
[0.1.3]: https://github.com/carlosraphael/hermes-workflow/compare/v0.1.2...v0.1.3
[0.1.2]: https://github.com/carlosraphael/hermes-workflow/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/carlosraphael/hermes-workflow/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/carlosraphael/hermes-workflow/releases/tag/v0.1.0
