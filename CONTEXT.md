# hermes-workflow

A declarative, versioned, multi-stage workflow primitive over the Hermes Kanban
board, shipped as a standalone Hermes plugin. This context exists to keep the
plugin's **naming taxonomy** unambiguous — the same word ("workflow") means
different things at different layers, and conflating them causes real packaging
and import bugs.

## Language

**Distribution name** (`hermes-workflow`):
The PyPI project name — the `pip install` target and the `name` in `pyproject.toml`.
Stays namespaced; `pip install workflow` would be generic and confusing.
_Avoid_: package name (ambiguous with import package).

**Import package** (`hermes_workflow`):
The importable Python top-level package — what `import` resolves to in a shared
site-packages, the entry-point target, and the `src/hermes_workflow/` folder.
Stays namespaced to avoid top-level collision in the user's Hermes environment.
_Avoid_: module, library.

**Plugin name** (`hermes-workflow`):
The Hermes-facing identity — `name:` in `src/hermes_workflow/plugin.yaml` and
the key a user adds to `plugins.enabled` in each bound profile's `config.yaml`.
_Avoid_: plugin id.

**Runtime surface** (`workflow`):
Every name a user types or sees at run time — the CLI command (`hermes workflow`),
the slash command (`/workflow`), the toolset (`workflow`), and the tool names
(`workflow_start`, `workflow_status`, …). Deliberately **unprefixed**; the
redundant `hermes` is already dropped here.
_Avoid_: command name (too narrow — it covers tools + toolset too).

**Standalone (entry-point) plugin**:
A plugin distributed on its own and discovered via a pip `hermes_agent.plugins`
entry point or `~/.hermes/plugins/`. This plugin's chosen model.
_Avoid_: external plugin.

**In-tree plugin**:
A plugin that lives inside `hermes-agent/plugins/<name>/`, path-loaded with
**relative** imports and no entry point (e.g. `disk-cleanup`). The model this
plugin deliberately does **not** adopt, despite the eventual-contribution goal.

**src-layout**:
Packaging idiom where importable code lives under `src/` (`src/hermes_workflow/`)
rather than at the repo root, so tests run against the *installed* package, not
the working copy.

## Relationships

- One **Distribution name** ships exactly one **Import package**; here they
  differ only by `-` vs `_` (`hermes-workflow` → `hermes_workflow`).
- The **Plugin name** equals the **Distribution name** string; both are the
  namespaced `hermes-workflow`.
- Every **Runtime surface** is unprefixed `workflow`; none carries the
  **Plugin name**'s `hermes-` prefix.
- A **Standalone plugin** exposes its **Import package** in shared
  site-packages — which is *why* the import package stays namespaced; an
  **In-tree plugin** would not (relative imports), so the constraint is
  specific to the standalone model.

## Example dialogue

> **Contributor:** "It's a Hermes-only plugin — can't we just call the package
> `workflow` and drop the redundant prefix?"
> **Maintainer:** "At the **runtime surface** it already is `workflow` —
> `/workflow`, `workflow_start`. But the **import package** lands in a shared
> site-packages as a **standalone plugin**, so a bare `workflow` would collide
> with any other top-level `workflow` on the path. The prefix only survives
> where namespacing earns its keep."

## Flagged ambiguities

- "workflow" was used to mean both the **import package** and the **runtime
  surface** — resolved: import package stays `hermes_workflow`, runtime surface
  is `workflow`. They are distinct layers.
- "package name" was ambiguous between **Distribution name** and **Import
  package** — resolved: always say which layer.
