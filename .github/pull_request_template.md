<!--
  Thanks for contributing to hermes-workflow! Keep one logical change per PR
  (don't mix a fix with a refactor with a feature). See CONTRIBUTING.md.
-->

## What does this PR do?

<!-- Describe the change clearly. What problem does it solve, and why is this the right approach? -->



## Related Issue

<!-- Link the issue this PR addresses. -->

Fixes #

## Type of Change

<!-- Check the one that applies — it should match your branch prefix and commit type. -->

- [ ] 🐛 Bug fix — restores a broken invariant (`fix/…`, `fix(scope):`)
- [ ] ✅ Tests — coverage for an existing surface (`test/…`, `test(scope):`)
- [ ] 📝 Documentation (`docs/…`, `docs(scope):`)
- [ ] ✨ New behaviour — **within the 0.1.0 scope** (`feat/…`, `feat(scope):`)
- [ ] ♻️ Refactor — no behaviour change (`refactor/…`, `refactor(scope):`)
- [ ] 🔧 Chore / CI / packaging (`chore/…`, `chore(scope):`)

## Changes Made

<!-- The specific changes, with file paths. -->

-

## How to Test

<!-- How a reviewer verifies this. For a bug fix: the failing test that now passes. -->

```sh
python3 -m pytest -m 'not integration'   # unit suite (always runs)
# Integration (real board, no LLM) needs a Hermes Agent v0.15.x checkout:
export HERMES_AGENT_ROOT=/abs/path/to/hermes-agent
python3 -m pytest                         # full suite (137 with the checkout)
```

1.
2.

## Checklist

<!-- Complete before requesting review. CONTRIBUTING.md#pull-request-process is the source of truth. -->

### Contribution hygiene

- [ ] My commits follow [Conventional Commits](https://www.conventionalcommits.org/) in `type(scope):` form (`fix(veto):`, `feat(engine):`, `test(provenance):`, `docs(agents):`, `chore(ci):`, … — scope optional for repo-wide changes)
- [ ] My branch is named `type/short-slug`
- [ ] This PR is **one logical change** — no unrelated fix/refactor/feature mixed in
- [ ] I searched for [existing PRs](https://github.com/carlosraphael/hermes-workflow/pulls) so this isn't a duplicate

### Tests

- [ ] `python3 -m pytest -m 'not integration'` passes (unit suite)
- [ ] `python3 -m pytest` passes with `HERMES_AGENT_ROOT` set (full suite) — or I've stated why the integration tier couldn't run
- [ ] I added tests for my change (**required** for bug fixes, strongly encouraged for features) and did not weaken existing coverage
- [ ] No LLM in any test; new integration tests use the no-LLM board harness

### Key invariants intact ([AGENTS.md#key-invariants](https://github.com/carlosraphael/hermes-workflow/blob/main/AGENTS.md#key-invariants))

<!-- Check each that your change preserves; check N/A only if the area is untouched. -->

- [ ] **No raw SQLite** — all board access stays on `ctx.dispatch_tool` / host `kb.*`; no new DB handle or string-built SQL (the `test_no_raw_sqlite` meta-test still passes) — or N/A
- [ ] **Engine stays pure** — engine code imports stdlib + PyYAML + intra-package only (no board, no Hermes) — or N/A
- [ ] **Completion gate stays injection-free & fail-closed** — no LLM in the veto; every `subprocess.run` uses a fixed argv with no shell/untrusted interpolation; the gate returns a block dict on any error (never raises, never `None`) — or N/A
- [ ] **Fan-out hook stays fail-open** — the `post_tool_call` body logs-and-swallows and never raises — or N/A
- [ ] **Version gate stays total** — `is_version_compatible` never raises and a schema mismatch is a visible refuse — or N/A
- [ ] **Provenance envelope stays robust** — payloads stay base64-encoded so `-->` in worker content can't truncate serialization — or N/A
- [ ] **Sentinel assignees stay non-spawnable** — `_workflow_root` / `_workflow_gate` keep their leading `_` — or N/A

### Dependencies & docs

- [ ] Any new PyPI dependency has a `<next_major` upper bound; any new GitHub Action is SHA-pinned with a `# vX.Y.Z` comment ([dependency-pinning policy](https://github.com/carlosraphael/hermes-workflow/blob/main/CONTRIBUTING.md#dependency-pinning-policy)) — or N/A
- [ ] I updated relevant docs (`README.md`, `AGENTS.md`, `docs/`, `CHANGELOG.md`) — or N/A
