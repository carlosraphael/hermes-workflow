# Changelog

All notable changes to `hermes-workflow` are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0/).
Versions refer to the **distribution** `hermes-workflow`; the run-snapshot
`SCHEMA_VERSION` (`0.1`) is tracked separately in
[`src/hermes_workflow/version.py`](src/hermes_workflow/version.py).

## [Unreleased]

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

[Unreleased]: https://github.com/carlosraphael/hermes-workflow/compare/v0.1.2...HEAD
[0.1.2]: https://github.com/carlosraphael/hermes-workflow/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/carlosraphael/hermes-workflow/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/carlosraphael/hermes-workflow/releases/tag/v0.1.0
