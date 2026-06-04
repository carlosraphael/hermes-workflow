# hermes-workflow Security Policy

`hermes-workflow` is a **Hermes Agent plugin** — a declarative, multi-stage
workflow primitive over the Hermes Kanban board. It loads into the Hermes
agent process and inherits Hermes Agent's trust model. This document states
where that model puts the boundary, names the design guarantees this plugin
is responsible for upholding, and defines the scope for vulnerability
reports.

Read [Hermes Agent's `SECURITY.md`](https://github.com/NousResearch/hermes-agent/blob/main/SECURITY.md)
first — it is the umbrella policy. This document does not restate it; it
covers only what is specific to this plugin.

## 1. Supported Versions

`hermes-workflow` is pre-1.0 (`Development Status :: 3 - Alpha`). Only the
latest `0.1.x` release receives security fixes; there is no back-porting to
earlier `0.1.x` patch releases.

| Version | Supported |
|---------|-----------|
| `0.1.x` (latest patch) | ✅ |
| `0.1.x` (older patch)  | ❌ — upgrade to the latest `0.1.x` |
| `< 0.1.0`              | ❌ |

The plugin version is `pip show hermes-workflow`; the run-snapshot schema
version is `SCHEMA_VERSION` in
[`src/hermes_workflow/version.py`](src/hermes_workflow/version.py).

## 2. Reporting a Vulnerability

Report privately via
[GitHub Security Advisories](https://github.com/carlosraphael/hermes-workflow/security/advisories/new)
("Report a vulnerability" on the repository's **Security** tab). **Do not
open a public issue for a security vulnerability.** If you cannot use GHSA,
reach the maintainer through the contact on their
[GitHub profile](https://github.com/carlosraphael) rather than a public
channel. This project does **not** operate a bug-bounty program.

A useful report includes:

- A concise description and a severity assessment.
- The affected component by **file path and line range** (e.g.
  `src/hermes_workflow/veto.py:40-72`).
- Environment: `pip show hermes-workflow`, the Hermes Agent version, OS, and
  Python version.
- A reproduction against `main` or the latest release.
- A statement of **which guarantee in §4 the report claims is broken**.

Please read §3 and §5 before submitting. A report that demonstrates the
limits of something this policy does not treat as a guarantee will be closed
as out-of-scope under §5 — but it is still welcome as a regular issue or PR
(§5.2), just not through the private channel.

## 3. Trust Model

`hermes-workflow` is a plugin, so the trust model is Hermes Agent's, not a
new one. Two consequences carry over verbatim and reporters should reason in
these terms:

- **The only boundary against an adversarial LLM is the operating system.**
  Nothing inside the agent process — including anything this plugin does — is
  containment. The completion gate (§4.2) is a *deterministic* control over
  board transitions, not a sandbox; it constrains which `kanban_complete`
  calls succeed, not what a compromised process can do.
- **Plugins run with full agent privileges.** Once loaded, this plugin can
  read the same credentials, call the same tools, and register the same hooks
  as anything shipped in-tree. The boundary for installing a third-party
  plugin is **operator review before install** (Hermes `SECURITY.md` §2.5).
  A malicious *fork* of this plugin is not a vulnerability in the upstream
  project.

What is specific — and reduces this plugin's marginal attack surface — is
that `hermes-workflow` **opens no socket, binds no port, and adds no external
surface.** It registers six `workflow_*` tools and a `pre`/`post` hook pair
in-process; all run on the operator's own board through the Hermes board
APIs. It introduces no new network-exposed adapter (cf. Hermes `SECURITY.md`
§2.6), so the surfaces that policy governs do not grow when this plugin is
installed.

**Content trust.** Workflow *templates* (`*.workflow.yaml`) are authored by
the operator and are trusted input. Card **bodies** produced by workers are
LLM output and are treated as untrusted for the one purpose where they touch
serialization — see §4.4.

## 4. Design Guarantees

These are the properties the plugin's own code is responsible for holding.
They are *correctness* guarantees of a deterministic component, not a
sandbox. Each is cross-referenced in
[`AGENTS.md#key-invariants`](AGENTS.md#key-invariants) and pinned by a test.
A code change that breaks one is in scope under §5.1.

### 4.1 No raw SQLite — all state through the board APIs

The plugin never opens its own database handle and never builds SQL. Every
read or write goes through `ctx.dispatch_tool` (`WorkerBoard`) or the host
`kb.*` surface (`HostBoard` / `RunView`); the single host connection is
opened via `kanban_db.connect_closing` (which closes the FD on exit).
Consequence: there is no string-built query and therefore no SQL-injection
surface inside this plugin, no second connection that could observe a
partial write, and no coupling to the board's on-disk schema. A
`test_no_raw_sqlite` meta-test walks the package to keep this true.

### 4.2 Injection-free deterministic completion gate (no LLM in the veto)

The `pre_tool_call` veto (`veto.evaluate_completion_gate`) is the **only
blocking channel**. It is pure and total: its decision is a function of board
state and the compiled template shape (`expand_out` shape + `max`, and
commit-clean for worktree stages) — **never of model output.** An
adversarial LLM cannot argue its way past it. Every `subprocess.run` in the
gate path uses a **fixed argv list with no shell and no untrusted
interpolation** (e.g. commit-clean is
`["git", "-C", dir, "status", "--porcelain"]`; the worktree branch is
engine-derived; pre-flight is `[sys.executable, "-m", …]`), so author or
worker content cannot reach a command line.

### 4.3 Fail-closed veto, fail-open fan-out

The two hooks have deliberately opposite failure modes, both load-bearing:

- **Veto fails CLOSED.** A *raising* `pre_tool_call` fails **open** at the
  host (the completion proceeds), so `evaluate_completion_gate` and the
  `on_tool_pre` `except` both **return a block dict on any internal error** —
  they never raise and never return `None` on an unexpected path. The version
  gate `is_version_compatible` is likewise total: it returns `False` for
  anything it cannot positively confirm (a bare-string `supported` is
  rejected rather than character-split into a false accept).
- **Fan-out fails OPEN.** The `post_tool_call` driver is a side-effect that
  materializes the next layer; its whole body is one `try/except` that logs
  and swallows and **never raises**, because a raising side-effect hook would
  wedge the worker that just completed legitimate work.

A schema-version mismatch is therefore a **visible refuse**, never a silent
mis-drive.

### 4.4 Base64 provenance envelope neutralizes `-->`

Run provenance (the per-card `Sentinel` and the root `CompiledSnapshot`) is
embedded in card bodies inside an HTML comment terminated by `-->`. The
payloads are **base64-encoded** (`engine/provenance.py::_encode`). The
base64 alphabet is `[A-Za-z0-9+/=]`, which cannot contain `-->`, so worker
content that itself contains `-->` cannot terminate the comment early and
truncate or forge the envelope. Recovery stays asymmetric on purpose:
`extract_sentinel` is **fail-soft** (returns `None` on a corrupt sentinel, so
one bad card does not crash enumeration), while `parse_root_body` **raises by
design** (a corrupt *root* snapshot must wedge the run loudly — fail-closed
at the veto, `WorkflowError` at reconcile — never drive on a half-parsed
root).

### 4.5 Sentinel assignees are non-spawnable

The blackboard root and human-gate cards carry the assignees
`_workflow_root` and `_workflow_gate`. Both lead with `_`, so the Hermes
dispatcher classifies them `skipped_nonspawnable`: the root snapshot and
human approval gates **never auto-spawn a worker**.

## 5. Scope

### 5.1 In Scope

- A code path that **breaks a §4 guarantee**: raw SQLite or string-built SQL
  introduced into the package; the veto failing **open** (a reachable path
  where it raises or returns `None`/non-block on error); `is_version_compatible`
  false-accepting an unsupported schema; untrusted content reaching a
  `subprocess` argv in the gate path; worker content truncating or forging
  the provenance envelope; a sentinel assignee becoming spawnable.
- A defect in the plugin's own logic that lets a stage complete or fan out in
  violation of the compiled template the run was started with (e.g. the gate
  admitting an `expand_out` that exceeds `max`).

### 5.2 Out of Scope

"Out of scope" means "not a security vulnerability under this policy," not
"not worth reporting." Hardening ideas and correctness fixes are welcome as
regular issues or PRs.

- **Anything the OS boundary owns (Hermes `SECURITY.md` §2.2/§3.2).** This
  plugin runs in the agent process; what that process can do to the host is
  governed by the operator's chosen isolation posture, not by this plugin.
- **Prompt injection per se.** Getting a worker LLM to emit unusual content
  is not, by itself, a finding — see §4.4 for the one serialization-integrity
  guarantee that worker content *does* engage.
- **A malicious or buggy third-party fork** of this plugin. Installing a
  plugin is an operator-review decision (§3).
- **Behaviour of a `0.2.x`-deferred feature.** Nested fan-out, `verify` /
  `retry`, granular `reject` / `modify`, and the `claude-code` lane are
  rejected or absent in `0.1.0` by design; reports that they are missing are
  feature requests, not vulnerabilities.
- **Operator misconfiguration** the docs warn against — e.g. a worker profile
  setting `worktree:true` (double-provisions), or enabling the plugin in only
  the orchestrator profile. These are documented pitfalls (`AGENTS.md`), not
  plugin defects.

## 6. Disclosure

- **Coordinated disclosure window:** 90 days from the report, or until a fix
  is released, whichever comes first.
- **Channel:** the GHSA thread for the report.
- **Credit:** reporters are credited in the `CHANGELOG.md` / release notes
  unless anonymity is requested.
