# hermes-workflow → Hermes Agent Conformance Audit

- **Date:** 2026-06-05
- **Baseline:** upstream `NousResearch/hermes-agent` `AGENTS.md` / `CONTRIBUTING.md`
  / `SECURITY.md` and `.github/` (as of this audit).
- **Posture:** proportionate conformance — adopt every applicable upstream rule;
  satisfy core-only rules by a deliberate, documented posture rather than literal
  mirroring (see the N/A-by-posture rows).
- **Severity:** CRITICAL (breaks a stated guarantee / supply-chain hole) ·
  HIGH (clear drift a reviewer would flag) · MEDIUM (maintainability / consistency)
  · LOW (cosmetic / optional) · N/A (core-only, or satisfied by construction). The
  severity shown per row is the **pre-remediation** severity of the gap that was
  closed; `conformant` / N/A rows carry no severity (`—`).
- **Status vocabulary:** `fixed-P1` = gap closed in this initiative's Phase 1 ·
  `conformant` = already satisfied before this initiative · `N/A` = deliberate
  non-adoption with a documented posture.

## Result

**No open CRITICAL or HIGH findings.** Phase 1 closed every MEDIUM/LOW governance,
convention, and supply-chain gap against the upstream baseline; the code was
already conformant *by construction* (POSIX-clean — argv-list subprocess, `pathlib`,
`sys.executable`, `shutil.which`; no `os.kill`/signal liveness, no `shell=True`,
no hardcoded temp paths, no `psutil`), and broad `except` is confined to the four
documented fail-open/fail-closed seams. `AGENTS.md` is now an enforceable contract:
9 merge-blocking Key Invariants (7 of 9 test-pinned) plus a mandatory, evidence-backed
`## Definition of Done` gate. All gates are green (71 unit + 72 integration passed,
`ruff check` clean). The Phase-2 confirmation sweep (below) surfaced **no residuals**.

## Traceability matrix

One row per *applicable* upstream rule (or deliberate non-adoption) → plugin
location → status. Every `fixed-P1` / `conformant` row was independently re-verified
against the live files during this audit (see Methodology).

### Phase-1 closures (gaps remediated in this initiative)

| # | Upstream rule / dimension | Sev | Status | Where satisfied |
|---|---|---|---|---|
| 1 | Dependency pinning — 4 source types + pre-1.0 `<0.(minor+2)` ceiling + incident cross-ref | M | fixed-P1 | `CONTRIBUTING.md` "Dependency pinning policy" (PyPI / Git-URL / Actions / CI-only `==exact`); enforced by `tests/unit/test_supply_chain_pins.py` |
| 2 | Supply-chain audit **gate** (make the pinning rule self-enforcing in CI) | M | fixed-P1 | **`tests/unit/test_supply_chain_pins.py`** — a CI unit meta-test (every dep upper-bounded + every Action SHA-pinned). Realized as a unit test, **not** a `supply-chain-audit.yml` workflow (none exists). |
| 3 | CI-only pip `==exact` on the publish/build path | M | fixed-P1 | `release.yml` Build step pinned `python -m pip install "build==1.5.0"`; `pyproject.toml` `[build-system].requires = ["setuptools>=61,<81"]` |
| 4 | GitHub Actions SHA-pinned + automated refresh | M | conformant + fixed-P1 | all `uses:` already pinned to a 40-char SHA + `# vX.Y.Z` comment (6 distinct SHAs across ci/osv/release); `.github/dependabot.yml` (github-actions ecosystem only) refreshes them |
| 5 | OSV / known-vulnerability scanning | M | fixed-P1 | `.github/workflows/osv-scanner.yml` — `google/osv-scanner-action/…@9a498708…edbc2 # v2.3.8` (SHA-pinned), PR + weekly (Mon 06:00 UTC) + dispatch, scans `--lockfile=pyproject.toml` |
| 6 | Lint in CI | L | fixed-P1 | `ci.yml` `lint` job runs **`ruff check src tests` (lint-only)** + `[tool.ruff.lint] select=["E","F","B","UP"], ignore=["E501"]`. **No `ruff format` / no `[tool.ruff.format]` / no isort `I`** — a deliberate scope correction honoring upstream's "no formatter" posture and the surgical-changes principle. `ruff>=0.15,<0.17` in dev extras. |
| 7 | Conventional Commits `type(scope):` + plugin scope list | M | fixed-P1 | `CONTRIBUTING.md` "Pull request process" (scope list + ci/build/packaging/deps fold into `chore`); `.github/pull_request_template.md` (scoped checkbox + Type-of-Change matrix) — kept in lockstep |
| 8 | Code style (PEP 8, catch-*specific*-exceptions, logging, comments, cross-platform) | M | fixed-P1 | `CONTRIBUTING.md` "Code style" — names the 4 sanctioned broad-`except` seams + log-free purity + `log.exception` fail-open surface |
| 9 | Don't-write-change-detector tests + plain-pytest posture | M | fixed-P1 | `AGENTS.md` "## Testing" → "Don't write change-detector tests" + "Why plain `pytest` (no hermetic wrapper)" |
| 10 | `AGENTS.md` as an enforceable contract: merge-blocking invariants + per-invariant test pins + binding top-pointer | M | fixed-P1 | `AGENTS.md` "## Key invariants" — **9** invariants, framed merge-blocking; **7/9 cite a pinning test** |
| 11 | Mandatory Definition-of-Done self-review gate (evidence, not assertion) | M | fixed-P1 | `AGENTS.md` "## Definition of Done" (authoritative pre-submit gate); `CONTRIBUTING.md` "Before opening" + PR template mirror it (DRY / lockstep) |
| 12 | Engine-purity invariant (stdlib + PyYAML + intra-package only) | M | fixed-P1 | `AGENTS.md` "## Key invariants"; pinned by `tests/unit/test_engine_purity.py` (AST-based) |
| 13 | No-core-modification invariant (reach Hermes only via `ctx.register_*`) | M | fixed-P1 (structural) | `AGENTS.md` "## Key invariants" — structural (standalone repo); not separately test-pinned |
| 14 | Fan-out fails OPEN invariant | M | fixed-P1 | `AGENTS.md` "## Key invariants"; pinned by `tests/integration/test_hook_fanout.py::test_hook_never_raises_on_garbage` |
| 15 | Cross-platform "never assume Unix" posture + metadata fixes | M | fixed-P1 | `AGENTS.md` "## Cross-platform" (POSIX: Linux/macOS/WSL2; native Windows out of scope for 0.x); `pyproject.toml` classifiers `POSIX :: Linux` + `MacOS`; `tools.py::_read_template` `read_text(encoding="utf-8-sig")` (pinned by `tests/unit/test_read_template.py`) |
| 16 | Skill-authoring standards (≤60-char description, section order, …) | L | fixed-P1 | `CONTRIBUTING.md` "Skill authoring"; both bundled skills already conform (`workflow-author` 48, `workflow-orchestrator` 58 chars) |
| 17 | Conformance / upstreaming charter (file→upstream map + maturity gates) | M | fixed-P1 | `CONTRIBUTING.md` "## Conformance & upstreaming" (gates: stable 0.2.x surface, abs→rel import per ADR-0001, green audit under `docs/audit/`); stale "Future work" footer dropped; README rows for `SECURITY.md` + `examples/` |

### Already conformant (no change needed)

| # | Upstream rule / dimension | Status | Where satisfied |
|---|---|---|---|
| 18 | `SECURITY.md` trust model / scope / 90-day coordinated disclosure | conformant | `SECURITY.md` §3 / §6 (best-aligned file; no edit) |
| 19 | Skill-vs-tool split | conformant | `CONTRIBUTING.md` "## Should it be a Skill or a Tool?" |
| 20 | Inbound = outbound MIT clause | conformant | `CONTRIBUTING.md` "## License" |
| 21 | OIDC Trusted Publishing release (no stored token) | conformant | `release.yml` — `pypa/gh-action-pypi-publish@cef2210…277b # v1.14.0`, `permissions: id-token: write` only |
| 22 | Two-tier, no-LLM/no-credential tests | conformant | `tests/` (unit + integration markers), `conftest.py`; `ci.yml` runs the unit tier |
| 23 | Injection-free deterministic gate (argv lists, no shell) | conformant | `AGENTS.md` "## Key invariants" — not yet test-pinned (add a test if you touch the gate's argv construction) |

### N/A by posture (deliberate non-adoptions — spec §6 register)

Each was verified core-only or satisfied by construction; recorded so a reviewer
does not mistake any for an oversight.

| # | Upstream artifact / rule | Status | Posture (why N/A) |
|---|---|---|---|
| 24 | `GOVERNANCE.md` / `CODEOWNERS` / `CODE_OF_CONDUCT` | N/A | Upstream has none; a new file would diverge from upstream's deliberate single-maintainer pre-1.0 posture. Charter folded into `CONTRIBUTING.md`. |
| 25 | `scripts/run_tests.sh` hermetic wrapper / subprocess-per-test isolation | N/A | Tests use no LLM and no credentials; the one process-global (`pre_tool_call` hooks) is isolated by the `register_pre_hook` fixture teardown; `HERMES_HOME` → `tmp_path` via `tmp_board`. |
| 26 | MCP supply-chain guards | N/A | Plugin launches no MCP server (it provides tools + hooks via `register(ctx)`). |
| 27 | `uv.lock` / hash lockfile | N/A | setuptools build; a two-spec runtime/dev dependency surface — a lockfile buys nothing here. |
| 28 | Adding-Configuration schema | N/A | No plugin-owned `config.yaml` section or `.env` config surface. |
| 29 | `contributor-check` / `history-check` workflows | N/A | Core-only / many-contributor concern; single-maintainer pre-1.0. |
| 30 | `setup_help` issue template | N/A | Targets the core `hermes setup` wizard, which this plugin does not own. |
| 31 | Docusaurus site / `docs/security/` subtree | N/A | Core-only documentation surface. |
| 32 | Skill `platforms:` frontmatter | N/A | Neither bundled skill uses POSIX-only primitives that would need platform gating. |
| 33 | Native-Windows code paths / `check-windows-footguns.py` | N/A | POSIX-only posture (Linux/macOS/WSL2); native Windows out of scope for 0.x. |
| 34 | `psutil` process remedies | N/A | The plugin owns no process lifecycle; the dependency floor stays at PyYAML. |
| 35 | commit-lint CI | N/A | Upstream has none; the PR template + review enforce Conventional Commits. |

## Methodology

This audit rests on three layers of evidence:

1. **Grounding gap analysis** (the seed): a 10-dimension, adversarially-verified
   inventory (finders → per-dimension skeptic verifiers → completeness critic;
   ≈40 verified findings + ≈13 N/A-by-posture verdicts) that produced the rows
   above.
2. **Phase-1 remediation**, landed as 14 one-logical-change commits (`e4600bc`…
   `5864748`), each Conventional-Commit scoped; three of them add invariant
   meta-tests (`test_supply_chain_pins`, `test_engine_purity`, `test_read_template`).
3. **Independent re-verification for this report**: a 6-cluster adversarial
   verification pass (one auditor per cluster — supply-chain, CI workflows,
   `AGENTS.md`, `CONTRIBUTING.md` + PR template, code defects + meta-tests,
   conformant + N/A register — plus a completeness critic) read the live files and
   returned per-claim verdicts with `file:line` evidence. **All claims confirmed;
   zero discrepancies.** Plus the Phase-2 confirmation sweep recorded below.

**Auditor notes (informational, no severity):**

- The supply-chain audit and lint gates were realized more proportionately than the
  original plan envisioned: the supply-chain gate is a **CI unit test**
  (`test_supply_chain_pins.py`) rather than a standalone `supply-chain-audit.yml`
  workflow, and the lint job is **ruff lint-only** (no formatter, no import sorting)
  to respect the surgical-changes principle and upstream's no-formatter posture.
- `src/` contains 14 `except Exception` sites; all are concentrated in the four
  documented broad-`except` surfaces (the fail-open `post_tool_call` hook and its
  per-stage guards, the fail-closed `pre_tool_call` gate, the veto internal-error
  guard, the tool-handler error envelope, and the fail-soft provenance
  `extract_sentinel`) — consistent with `CONTRIBUTING.md`'s "4 sanctioned seams"
  rule, which governs *where* broad-`except` is permitted, not a raw count.
