# Ship as a standalone, dedicated-repo Hermes plugin (src-layout, namespaced import name)

We package `hermes-workflow` as a **standalone, pip/entry-point Hermes plugin in
its own dedicated repo** (`github.com/carlosraphael/hermes-workflow`), using a
`src/` layout (`src/hermes_workflow/`) and keeping the **namespaced import package
`hermes_workflow`** even though every runtime surface (`/workflow`,
`workflow_start`, toolset `workflow`) is the shorter unprefixed `workflow`. We do
this — rather than landing the code in `hermes-agent/plugins/<name>/` — because
Hermes' own governance now prefers new plugins to ship as standalone repos
(installed via pip entry point or `~/.hermes/plugins/`) and forbids plugins from
modifying core files, so "contribution-ready" means *meeting the standalone bar*,
not literally merging in-tree.

## Considered options

- **In-tree `hermes-agent/plugins/hermes-workflow/`** — matches one Hermes
  convention, but in-tree plugins are path-loaded with **relative** imports and
  no entry point; Hermes policy steers new plugins away from in-tree. Rejected as
  the *current* home (remains the eventual port target).
- **Monorepo branch in `cortex`** (status quo) — forced the awkward
  `hermes-workflow-v*` tag namespacing and hides the plugin as a branch. Rejected.
- **Literal `src/workflow/` (import name `workflow`)** — shortest, but claims a
  generic top-level name in shared site-packages (collision/shadowing risk) and
  rewrites ~67 import sites. Rejected.

## Consequences

- The import package stays `hermes_workflow`: collision-safe in a shared Hermes
  environment, zero import churn on the move (only `pyproject` gains
  `packages.find where=["src"]`).
- In a dedicated repo the `hermes-workflow-` tag prefix is no longer needed —
  releases are re-tagged clean `v0.1.0` / `v0.1.1`; Cortex's `v0.x` tags stay
  behind.
- Eventual in-tree contribution still requires an absolute→relative import
  conversion; that is deliberately deferred until the plugin is mature.
- See [CONTEXT.md](../../CONTEXT.md) for the naming taxonomy (distribution name
  vs import package vs plugin name vs runtime surface) this decision rests on.
