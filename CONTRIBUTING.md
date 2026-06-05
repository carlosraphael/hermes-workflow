# Contributing to hermes-workflow

A lean onboarding guide. It does **not** re-explain how the plugin works — that
lives in [`AGENTS.md`](AGENTS.md). Read [`CONTEXT.md`](CONTEXT.md) first for the
naming taxonomy (distribution `hermes-workflow`, import `hermes_workflow`, runtime
surface `workflow`); never conflate those layers in code or prose.

## Contribution priorities

What's wanted, in order:

1. **Bug fixes** — anything that breaks an invariant in
   [AGENTS.md#key-invariants](AGENTS.md#key-invariants). Always top priority.
2. **Test coverage** for an existing surface that isn't pinned yet.
3. **Documentation** — fixes, clarifications, examples.
4. **New behaviour** — only within the 0.1.0 scope below.

**0.1.0 scope** (verify against the README "0.1.0 scope" section):

- Lanes are `{profile, codex}` only. `claude-code` is **deferred to 0.2.x**.
- `verify.command` / `retry` and granular `reject` / `modify` are **deferred to
  0.2.x** (rejected at template validation today).
- Nested fan-out — an `expand` stage that is itself an `expand` source — is
  **forbidden** in 0.1.0.

End-goal: this matures into an official Hermes Agent contribution. Conform to
Hermes conventions throughout (Conventional Commits, the skill-vs-tool split, the
dependency-pinning policy below) so the eventual upstreaming is mechanical, not a
rewrite.

## Should it be a Skill or a Tool?

A lightweight adaptation of Hermes' guidance. This plugin ships **both** — six
`workflow_*` tools plus a `pre`/`post` hook pair, and two skills.

- **Tool or hook** when the behaviour must be **deterministic and always
  available** — it runs the same way every time, with no LLM in the path. The
  completion gate (`pre_tool_call` veto) and the fan-out (`post_tool_call` hook)
  are tools/hooks precisely because they are injection-free and must not be
  "best effort". See [AGENTS.md#architecture](AGENTS.md#architecture).
- **Skill** when it's an **agent-facing how-to** — instructions the model reads
  and acts on. `workflow-author` (writing a `*.workflow.yaml`) and
  `workflow-orchestrator` (start / status / approve / abandon / reconcile) are
  skills because they guide an agent, not enforce a rule.

When in doubt, prefer a skill; a new tool needs a deterministic reason to exist.

## Development setup

```sh
git clone https://github.com/carlosraphael/hermes-workflow
cd hermes-workflow

python3 -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'          # PyYAML runtime + pytest

# Point the integration suite at a Hermes checkout (v0.15.x):
export HERMES_AGENT_ROOT=/abs/path/to/hermes-agent

python3 -m pytest
```

The package uses **src-layout** — importable code is under `src/hermes_workflow/`,
so tests run against the installed package, not the working copy. The integration
tests **skip** when `HERMES_AGENT_ROOT` points at no real checkout (they need a
live board + plugin load, no LLM); unit tests always run.

For how the code is laid out and how a run actually executes, read
[AGENTS.md#project-structure](AGENTS.md#project-structure) and
[AGENTS.md#architecture](AGENTS.md#architecture).

## Code style

- **Immutability** — build new objects; never mutate engine inputs in place.
- **KISS / DRY** — the simplest thing that holds the invariant; extract real
  repetition, not speculative generality.
- **Surgical changes** — touch only what the change requires; match the
  surrounding style; don't refactor what isn't broken.

The full rationale (engine purity, the fail-open/fail-closed split) is in
[AGENTS.md#working-principles](AGENTS.md#working-principles).

## Dependency pinning policy

This adopts Hermes' supply-chain rule (rationale: the litellm and Mini
Shai-Hulud supply-chain incidents; mutable tag refs — see Hermes
`CONTRIBUTING.md` → "Dependency pinning policy"). Every dependency carries an
upper bound to limit supply-chain attack surface:

| Source | Treatment |
|---|---|
| **PyPI package** | `>=floor,<next_major` (e.g. `PyYAML>=6,<7`). For a **pre-1.0 (0.x)** package use `<0.(current_minor + 2)` (a tight minor window), **not** `<1`. |
| **Git URL** (none today) | Full commit SHA (`git+https://…@<40-char-sha>`). |
| **GitHub Actions** | Full commit SHA + version comment: `uses: owner/action@<sha>  # vX.Y.Z`. |
| **CI-only pip install** | `==exact` (hermetic CI builds; churn is acceptable). |

An unbounded `>=X` spec will be rejected in review.

Today this repo's runtime/dev deps are **PyYAML** and **pytest**, and the
build-system requires **setuptools** — all three bounded in `pyproject.toml`
(including `[build-system].requires`). Keep it that way; new dependencies are a
high bar. The `tests/unit/test_supply_chain_pins.py` meta-test (Task 2) enforces
this in CI.

## Pull request process

- **Branch naming:** `type/short-slug` — `fix/…`, `feat/…`, `test/…`, `docs/…`,
  `refactor/…`, `chore/…`.
- **Commits:** [Conventional Commits](https://www.conventionalcommits.org/) —
  `feat`, `fix`, `test`, `docs`, `chore`, `refactor`, `perf`.
- **Before opening:** all tests green and the invariants in
  [AGENTS.md#key-invariants](AGENTS.md#key-invariants) intact — no raw SQLite,
  engine stays pure (stdlib + PyYAML + intra-package only), the gate stays
  injection-free and fail-closed, the fan-out hook stays fail-open.
- **One logical change per PR.** Don't mix a fix with a refactor with a feature.
- **Release tags** are clean `vMAJOR.MINOR.PATCH` (e.g. `v0.1.1`).

## Reporting issues

Open a [GitHub issue](https://github.com/carlosraphael/hermes-workflow/issues)
with a minimal reproduction and the version (`pip show hermes-workflow`).

## License

MIT — see [`LICENSE`](LICENSE). By contributing you agree your contributions are
licensed under it.

---

_Future work / not yet in place:_ `SECURITY.md`, issue/PR templates, a
`CHANGELOG`, a broader test-convention audit, and PyPI publishing.
