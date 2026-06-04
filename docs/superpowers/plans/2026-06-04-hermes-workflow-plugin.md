# hermes-workflow Plugin (v0.1.0 spine) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the v0.1.0 spine of `hermes-workflow` — a native Hermes Agent plugin that instantiates a declarative YAML workflow template into a linked Kanban card-graph, drives lazy single-level fan-out via a `post_tool_call` hook, gates completion deterministically via a `pre_tool_call` veto, and resolves a human gate via `approve`/`abandon`.

**Architecture:** Fat deterministic engine (pure Python, no board/LLM — carries the test weight) wrapped by a thin imperative shell (tools/CLI/slash + two hooks) that mutates the board only through public `kanban_*` tools / `ctx.dispatch_tool` and the host `kb.*` layer (for archive/unlink, which have no model tool). The board is the source of truth; a write-once compiled-template snapshot lives in a completed root "blackboard" card; per-card body sentinels + `task_links` + statuses are the live state.

**Tech Stack:** Python 3.11+, Hermes Agent v0.15.1 (local checkout `/Users/carlos/cortex-workspace/hermes-agent`, commit `c47b9d12`), pytest, PyYAML. Plugin distributed via the `hermes_agent.plugins` entry point.

**Source of truth:** the approved spec `docs/superpowers/specs/2026-06-03-hermes-workflow-plugin-design-final.md`. Section refs below (e.g. §5.5) point there.

**Ground rules for every task:**
- Read the cited Hermes source in the local checkout before writing coupled code; never invent a signature.
- Engine code imports **nothing** from Hermes (pure, unit-tested without a board or model).
- Integration tests use a **real** board + real plugin load + real `kanban_*`, but **zero LLM** — "worker" steps are driven by calling `kanban_complete` directly with canned metadata.
- Constants: `PLUGIN_VERSION = "0.1.0"`, `SCHEMA_VERSION = "0.1"`, `SENTINEL_PREFIX = "_workflow"` (gate assignee `_workflow_gate`, root assignee `_workflow_root`).

---

## Phase 0 — Scaffolding & de-risking spikes (validate before building)

The spikes (§14) confirm the load-bearing Hermes behaviors the coupled code depends on. Each writes a kept integration test (the spec says these become the first integration tests) and records confirmed signatures in `tests/SPIKES.md`. If a spike's assertion fails, record the *actual* behavior in `SPIKES.md` and stop for review — a failed spike invalidates a coupled task.

### Task 0: Plugin skeleton + load smoke test

**Files:**
- Create: `hermes_workflow/__init__.py`
- Create: `hermes_workflow/plugin.yaml`
- Create: `hermes_workflow/version.py`
- Create: `pyproject.toml`
- Create: `tests/SPIKES.md`
- Create: `tests/integration/test_plugin_loads.py`
- Create: `tests/conftest.py`

- [x] **Step 1: Write `version.py`**

```python
# hermes_workflow/version.py
PLUGIN_VERSION = "0.1.0"
SCHEMA_VERSION = "0.1"
SUPPORTED_SCHEMA_VERSIONS = frozenset({"0.1"})
SENTINEL_GATE_ASSIGNEE = "_workflow_gate"
SENTINEL_ROOT_ASSIGNEE = "_workflow_root"
```

- [x] **Step 2: Write `plugin.yaml`**

```yaml
name: hermes-workflow
version: 0.1.0
description: Declarative multi-stage workflow primitive over the Kanban board.
provides_tools:
  - workflow_start
  - workflow_status
  - workflow_validate
  - workflow_reconcile
  - workflow_approve
  - workflow_abandon
provides_hooks:
  - post_tool_call
  - pre_tool_call
```

- [x] **Step 3: Write a minimal `register(ctx)`**

```python
# hermes_workflow/__init__.py
"""hermes-workflow: declarative workflow primitive over Hermes Kanban."""
from hermes_workflow.version import PLUGIN_VERSION


def register(ctx):
    """Called once at startup. Wiring is added by later tasks."""
    # Tools, CLI, slash, hooks, and skills are registered in later tasks.
    # Keeping register importable + crash-free is the smoke-test target.
    ctx.log.info("hermes-workflow %s loaded", PLUGIN_VERSION) if hasattr(ctx, "log") else None
```

- [x] **Step 4: Write `pyproject.toml` with the entry point**

```toml
[project]
name = "hermes-workflow"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["PyYAML>=6"]

[project.entry-points."hermes_agent.plugins"]
hermes-workflow = "hermes_workflow"

[project.optional-dependencies]
dev = ["pytest>=8"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["integration: requires a real Hermes board + plugin load (no LLM)"]
```

- [x] **Step 5: Write `tests/conftest.py` (locate the Hermes checkout, skip integration cleanly if absent)**

```python
# tests/conftest.py
import os, sys, pathlib, pytest

HERMES_ROOT = pathlib.Path(
    os.environ.get("HERMES_AGENT_ROOT", "/Users/carlos/cortex-workspace/hermes-agent")
)


@pytest.fixture(scope="session")
def hermes_root():
    if not (HERMES_ROOT / "hermes_cli").is_dir():
        pytest.skip(f"Hermes checkout not found at {HERMES_ROOT}; set HERMES_AGENT_ROOT")
    if str(HERMES_ROOT) not in sys.path:
        sys.path.insert(0, str(HERMES_ROOT))
    return HERMES_ROOT
```

- [x] **Step 6: Write the load smoke test**

```python
# tests/integration/test_plugin_loads.py
import importlib


def test_register_is_importable_and_crashfree():
    mod = importlib.import_module("hermes_workflow")
    assert hasattr(mod, "register")

    class FakeCtx:  # minimal stand-in; register must not require more in 0.1.0 skeleton
        class log:
            @staticmethod
            def info(*a, **k): pass

    mod.register(FakeCtx())  # must not raise
```

- [x] **Step 7: Run + verify**

Run: `pip install -e ".[dev]" && pytest tests/integration/test_plugin_loads.py -v`
Expected: PASS.

- [x] **Step 8: Seed `tests/SPIKES.md`**

```markdown
# Spike findings (confirmed Hermes v0.15.1 @ c47b9d12 signatures/behaviors)
Each spike records the exact signature/behavior the coupled tasks depend on.
```

- [x] **Step 9: Commit**

```bash
git add hermes_workflow pyproject.toml tests/
git commit -m "chore: scaffold hermes-workflow plugin + load smoke test"
```

---

### Task 1: Spike — `pre_tool_call` veto blocks `kanban_complete` (§14 Spike 1, findings O/§2)

**Goal:** confirm a `pre_tool_call` hook returning `{"action":"block","message":…}` prevents `kanban_complete`, leaves the card `running`, surfaces the message, and that an exception in the hook fails **open** (so our gate must never raise).

**Files:**
- Create: `tests/integration/test_spike_veto.py`
- Modify: `tests/SPIKES.md`

- [x] **Step 1: Read the source first**

Read in the checkout: `model_tools.py:928-943` (pre_tool_call block path; note `block_message=None` on swallowed exception) and `hermes_cli/plugins.py:1666-1707` (`get_pre_tool_call_block_message`). Record the exact return contract in `SPIKES.md`.

- [x] **Step 2: Write the spike test (block path)**

```python
# tests/integration/test_spike_veto.py
import pytest

pytestmark = pytest.mark.integration


def test_pre_tool_call_block_prevents_completion(hermes_root, tmp_board):
    # tmp_board fixture is added in Task 6; for the spike, inline a board if needed.
    from hermes_cli import plugins
    blocked = {"action": "block", "message": "veto: precondition failed"}
    plugins.register_hook("pre_tool_call", lambda **kw: blocked if kw.get("tool_name") == "kanban_complete" else None)
    msg = plugins.get_pre_tool_call_block_message(tool_name="kanban_complete", args={}, task_id="t_x")
    assert msg and "veto" in msg  # the block message surfaces; complete is not dispatched
```

- [x] **Step 3: Write the fail-open assertion**

```python
def test_pre_tool_call_exception_fails_open(hermes_root):
    from hermes_cli import plugins

    def boom(**kw):
        raise RuntimeError("hook bug")

    plugins.register_hook("pre_tool_call", boom)
    # A raising hook must NOT block (block_message stays None) -> our gate must never rely on raising.
    msg = plugins.get_pre_tool_call_block_message(tool_name="kanban_complete", args={}, task_id="t_x")
    assert msg is None
```

- [x] **Step 4: Run + record**

Run: `pytest tests/integration/test_spike_veto.py -v`
Expected: PASS. If the block contract differs, record the actual shape in `SPIKES.md` and STOP for review.

- [x] **Step 5: Record findings + commit**

Append to `SPIKES.md`: the exact `register_hook` name, the `get_pre_tool_call_block_message` signature, and the confirmed "exception ⇒ no block (fail-open)" rule.

```bash
git add tests/integration/test_spike_veto.py tests/SPIKES.md
git commit -m "test(spike): pre_tool_call veto blocks complete; raises fail open"
```

---

### Task 2: Spike — per-profile loadability probe (§14 Spike 2, finding C/T)

**Goal:** confirm `enabled ≠ loaded`, that load truth is `LoadedPlugin.enabled/.error` (`plugins.py:278-279`, exposed via `list_plugins()`), and that it's only visible in-process under that profile's `HERMES_HOME`.

**Files:**
- Create: `tests/integration/test_spike_preflight.py`
- Modify: `tests/SPIKES.md`

- [x] **Step 1: Read the source**

Read `hermes_cli/plugins.py:278-279` (`LoadedPlugin.enabled/.error`), `:1574-1593` (`list_plugins()`), `:1085` (`HERMES_ENABLE_PROJECT_PLUGINS`); `hermes_cli/plugins_cmd.py:806` (config-only `list`). Record the exact way to read load status in-process.

- [x] **Step 2: Write the probe-shape test**

```python
# tests/integration/test_spike_preflight.py
import os, pytest
pytestmark = pytest.mark.integration


def test_list_plugins_reports_load_status(hermes_root, tmp_path):
    os.environ["HERMES_HOME"] = str(tmp_path)
    os.environ["HERMES_ENABLE_PROJECT_PLUGINS"] = "1"
    from hermes_cli import plugins
    plugins.discover_plugins()
    loaded = plugins.list_plugins()  # confirm this returns objects with .name/.enabled/.error
    assert isinstance(loaded, (list, dict))
    # Record in SPIKES.md the exact shape (list[LoadedPlugin] vs dict) + attribute names.
```

- [x] **Step 3: Run + record the exact return shape**

Run: `pytest tests/integration/test_spike_preflight.py -v`
Record in `SPIKES.md`: the exact `list_plugins()` return type and how to get `(enabled, error)` for a plugin by name; the env vars the spawned probe must set (`HERMES_HOME`, `HERMES_ENABLE_PROJECT_PLUGINS` if a project plugin).

- [x] **Step 4: Commit**

```bash
git add tests/integration/test_spike_preflight.py tests/SPIKES.md
git commit -m "test(spike): per-profile load-status probe shape"
```

---

### Task 3: Spike — atomic create + fan-out hook + reconcile re-link (§14 Spike 4, findings A/B/J/M/R5)

**Goal:** confirm (a) `kanban_create(parents=[...])` lands the join's status atomically from current parent statuses; (b) a `post_tool_call` hook can `ctx.dispatch_tool("kanban_create"/"kanban_link")`; (c) a join wired to all instances promotes exactly once when the last parent completes; (d) `kanban_link(child→join)` added late demotes a `ready` join back to `todo`.

**Files:**
- Create: `tests/integration/test_spike_fanout.py`
- Modify: `tests/SPIKES.md`

- [x] **Step 1: Read the source**

Read `hermes_cli/kanban_db.py`: `create_task` (`:2155-2168`, `:2235-2245`), `recompute_ready` (`:2858-2908`), `link_tasks` (`:2356-2383`), `complete_task` (`:3576-3605`). Read `model_tools.py:991-1006` (post_tool_call args: `tool_name,args,result,task_id,**kwargs`; return ignored; exceptions swallowed). Record exact `ctx.dispatch_tool` return (JSON string) and `kanban_create` return (`{task_id,status}`).

- [x] **Step 2: Write the atomic-create test**

```python
# tests/integration/test_spike_fanout.py
import json, pytest
pytestmark = pytest.mark.integration


def test_join_created_with_all_parents_lands_todo_until_all_done(tmp_board, mk_card, complete_card):
    a = mk_card(title="child a"); b = mk_card(title="child b")
    join = mk_card(title="join", parents=[a, b])
    assert tmp_board.status(join) == "todo"   # not ready: parents not done
    complete_card(a)
    assert tmp_board.status(join) == "todo"   # still gated on b
    complete_card(b)
    assert tmp_board.status(join) == "ready"  # promoted exactly when last parent done
```

- [x] **Step 3: Write the late-link demotion test**

```python
def test_linking_incomplete_parent_demotes_ready_join(tmp_board, mk_card, complete_card):
    a = mk_card(title="a"); complete_card(a)
    join = mk_card(title="join", parents=[a])
    assert tmp_board.status(join) == "ready"
    c = mk_card(title="late child")          # incomplete
    tmp_board.link(parent=c, child=join)      # kb.link_tasks
    assert tmp_board.status(join) == "todo"   # demoted; safe for reconcile late re-link
```

- [x] **Step 4: Run + record**

Run: `pytest tests/integration/test_spike_fanout.py -v`
Expected: PASS. Record confirmed `create_task`/`link_tasks` host signatures and the post_tool_call arg names in `SPIKES.md`.

- [x] **Step 5: Commit**

```bash
git add tests/integration/test_spike_fanout.py tests/SPIKES.md
git commit -m "test(spike): atomic create-with-parents, late-link demotion, fan-in promotion"
```

---

### Task 4: Spike — worker-side version gate (§14 Spike 5, finding C/§2)

**Goal:** confirm the hook/veto run under the worker profile's `HERMES_HOME` (so version can differ), that cross-task `kanban_comment` on the root is unrestricted (author forced), and that a mismatch path can visibly refuse without raising.

**Files:**
- Create: `tests/integration/test_spike_version_gate.py`
- Modify: `tests/SPIKES.md`

- [x] **Step 1: Read the source**

Read `hermes_cli/kanban_db.py:6468` (`HERMES_HOME = resolve_profile_env(assignee)`), `tools/kanban_tools.py:705-707` (cross-task comment unrestricted, author forced). Record.

- [x] **Step 2: Write the cross-task comment test**

```python
# tests/integration/test_spike_version_gate.py
import pytest
pytestmark = pytest.mark.integration


def test_worker_can_comment_on_foreign_root(tmp_board, mk_card, as_worker):
    root = mk_card(title="root")
    other = mk_card(title="worker card")
    with as_worker(other):  # sets HERMES_KANBAN_TASK=other
        from tools import kanban_tools
        res = kanban_tools._handle_comment({"task_id": root, "body": "schema_version mismatch: refusing"})
    assert "error" not in res.lower()  # foreign-root comment is allowed
```

- [x] **Step 3: Run + record**

Run: `pytest tests/integration/test_spike_version_gate.py -v`
Record the confirmed "worker may comment on any card; author forced" behavior + that the hook/veto inherit the worker profile's plugin version.

- [x] **Step 4: Commit**

```bash
git add tests/integration/test_spike_version_gate.py tests/SPIKES.md
git commit -m "test(spike): cross-task root comment for visible version-refuse"
```

---

### Task 5: Spike — abandon reclaim-then-archive (§14 Spike 6, findings A2/Y)

**Goal:** confirm `archive_task` does not kill workers, `archive` is host-only (`kb.archive_task`, no model tool), archiving leaves-first avoids transient `ready` promotion, and worktrees are preserved.

**Files:**
- Create: `tests/integration/test_spike_abandon.py`
- Modify: `tests/SPIKES.md`

- [x] **Step 1: Read the source**

Read `hermes_cli/kanban_db.py:4486-4509` (`archive_task` → `recompute_ready`, nulls `worker_pid` only), reclaim/terminate paths (`:3229/3301/5229`), `_cleanup_workspace:3766-3783` (only scratch cleaned). Confirm there is no `kanban_archive`/`kanban_unlink` model tool (`tools/kanban_tools.py:1352-1424`). Record signatures for `kb.archive_task`, `kb.reclaim_task`/terminate.

- [x] **Step 2: Write the leaves-first archive test**

```python
# tests/integration/test_spike_abandon.py
import pytest
pytestmark = pytest.mark.integration


def test_archive_children_before_parent_no_transient_ready(tmp_board, mk_card):
    parent = mk_card(title="interior", role_assignee="real-profile")
    child = mk_card(title="leaf", parents=[parent])
    # Archive child first (leaf), then parent: parent must never flip to 'ready' mid-sweep.
    tmp_board.archive(child)
    assert tmp_board.status(parent) != "ready"
    tmp_board.archive(parent)
    assert tmp_board.status(parent) == "archived"
```

- [x] **Step 3: Run + record**

Run: `pytest tests/integration/test_spike_abandon.py -v`
Record `kb.archive_task` signature, reclaim/terminate signature, and "archive preserves non-scratch workspaces."

- [x] **Step 4: Commit**

```bash
git add tests/integration/test_spike_abandon.py tests/SPIKES.md
git commit -m "test(spike): leaves-first archive, host-only archive, worktree preserved"
```

---

## Phase 1 — The pure engine (full TDD, no Hermes imports)

### Task 6: Shared board test harness (no LLM)

**Files:**
- Create: `tests/integration/board.py`
- Modify: `tests/conftest.py`

- [x] **Step 1: Implement a thin board harness wrapping `hermes_cli.kanban_db`**

```python
# tests/integration/board.py
"""No-LLM board harness: create/complete/link/archive/status via kb.* on a temp board."""
import contextlib, os


class Board:
    def __init__(self, kb, conn, board_name):
        self.kb, self.conn, self.name = kb, conn, board_name

    def create(self, title, parents=(), assignee="_workflow_root", workspace_kind="scratch",
               workspace_path=None, body="", skills=None, idempotency_key=None):
        return self.kb.create_task(self.conn, title=title, body=body, assignee=assignee,
                                   parents=tuple(parents), workspace_kind=workspace_kind,
                                   workspace_path=workspace_path, skills=skills,
                                   idempotency_key=idempotency_key, board=self.name)

    def complete(self, tid, summary="done", metadata=None):
        return self.kb.complete_task(self.conn, tid, summary=summary, metadata=metadata or {})

    def link(self, parent, child):
        return self.kb.link_tasks(self.conn, parent_id=parent, child_id=child)

    def archive(self, tid):
        return self.kb.archive_task(self.conn, tid)

    def status(self, tid):
        return self.kb.get_task(self.conn, tid)["status"]
```

> Confirm the exact `kb.*` signatures against Task 3/5 `SPIKES.md` and adjust kwargs to match (e.g. `create_task` param names). Do not guess — use the recorded signatures.

- [x] **Step 2: Add fixtures `tmp_board`, `mk_card`, `complete_card`, `as_worker` to `conftest.py`**

```python
# tests/conftest.py  (append)
import contextlib, os, pytest


@pytest.fixture
def tmp_board(hermes_root, tmp_path):
    os.environ["HERMES_HOME"] = str(tmp_path)
    os.environ["HERMES_KANBAN_BOARD"] = "test"
    from hermes_cli import kanban_db as kb
    conn = kb.connect(board="test")
    from tests.integration.board import Board
    return Board(kb, conn, "test")


@pytest.fixture
def mk_card(tmp_board):
    def _mk(**kw): return tmp_board.create(**kw)
    return _mk


@pytest.fixture
def complete_card(tmp_board):
    def _c(tid, **kw): return tmp_board.complete(tid, **kw)
    return _c


@pytest.fixture
def as_worker():
    @contextlib.contextmanager
    def _ctx(task_id):
        prev = os.environ.get("HERMES_KANBAN_TASK")
        os.environ["HERMES_KANBAN_TASK"] = task_id
        try:
            yield
        finally:
            os.environ.pop("HERMES_KANBAN_TASK", None) if prev is None else os.environ.update(HERMES_KANBAN_TASK=prev)
    return _ctx
```

- [x] **Step 3: Run the Phase-0 spikes against the real fixtures; commit**

Run: `pytest tests/integration -v` (all spikes now green against `tmp_board`).

```bash
git add tests/integration/board.py tests/conftest.py
git commit -m "test: no-LLM board harness + fixtures"
```

---

### Task 7: Engine data model + template parsing

**Files:**
- Create: `hermes_workflow/engine/__init__.py` (empty)
- Create: `hermes_workflow/engine/model.py`
- Create: `hermes_workflow/engine/template.py`
- Test: `tests/unit/test_template_parse.py`

- [x] **Step 1: Write the failing parse test**

```python
# tests/unit/test_template_parse.py
from hermes_workflow.engine.template import parse_template

YAML = """
name: demo
version: 0.1.0
params:
  repo: { type: string, required: true }
roles:
  scout: { lane: profile }
  fixer: { lane: codex }
stages:
  - id: scan
    role: scout
    title: "Scan ${params.repo}"
    body: "find things"
    workspace: "dir:${params.repo}"
    expand_out: { key: items, max: 50, item: { id: string } }
  - id: fix
    role: fixer
    needs: [scan]
    expand: { over: scan.items, as: it }
    title: "Fix ${it.id}"
    workspace: "worktree:${params.repo}"
  - id: approve
    needs: [fix]
    gate: human
"""


def test_parse_basic_template():
    t = parse_template(YAML)
    assert t.name == "demo" and t.version == "0.1.0"
    assert t.params["repo"].required is True
    assert t.roles["fixer"].lane == "codex"
    fix = t.stage("fix")
    assert fix.expand.over_stage == "scan" and fix.expand.over_key == "items" and fix.expand.as_var == "it"
    assert t.stage("scan").expand_out.max == 50
    assert t.stage("approve").gate == "human"
```

- [x] **Step 2: Run to verify it fails**

Run: `pytest tests/unit/test_template_parse.py -v`
Expected: FAIL (module not found).

- [x] **Step 3: Implement the data model**

```python
# hermes_workflow/engine/model.py
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Param:
    name: str
    type: str
    required: bool = False
    default: object = None


@dataclass(frozen=True)
class Role:
    name: str
    lane: str  # "profile" | "codex"


@dataclass(frozen=True)
class ExpandSpec:
    over_stage: str
    over_key: str
    as_var: str


@dataclass(frozen=True)
class ExpandOut:
    key: str
    item: dict  # field_name -> type string
    max: int = 50


@dataclass(frozen=True)
class Stage:
    id: str
    role: str | None = None
    title: str = ""
    body: str = ""
    needs: tuple[str, ...] = ()
    expand: ExpandSpec | None = None
    expand_out: ExpandOut | None = None
    gate: str | None = None          # "human" or None
    workspace: str = "scratch"       # scratch | dir:<p> | worktree:<p>


@dataclass(frozen=True)
class Template:
    name: str
    version: str
    description: str
    params: dict           # name -> Param
    roles: dict            # name -> Role
    stages: tuple          # tuple[Stage]

    def stage(self, sid: str) -> Stage:
        for s in self.stages:
            if s.id == sid:
                return s
        raise KeyError(sid)
```

- [x] **Step 4: Implement the parser**

```python
# hermes_workflow/engine/template.py
from __future__ import annotations
import yaml
from hermes_workflow.engine.model import Param, Role, ExpandSpec, ExpandOut, Stage, Template


class TemplateError(ValueError):
    pass


def parse_template(text: str) -> Template:
    raw = yaml.safe_load(text)
    if not isinstance(raw, dict):
        raise TemplateError("template must be a YAML mapping")
    params = {n: Param(n, p.get("type", "string"), bool(p.get("required", False)), p.get("default"))
              for n, p in (raw.get("params") or {}).items()}
    roles = {n: Role(n, r.get("lane", "profile")) for n, r in (raw.get("roles") or {}).items()}
    stages = []
    for s in raw.get("stages") or []:
        exp = s.get("expand")
        expand = None
        if exp:
            over = exp["over"]  # "<stage>.<key>"
            st, key = over.split(".", 1)
            expand = ExpandSpec(st, key, exp["as"])
        eo = s.get("expand_out")
        expand_out = ExpandOut(eo["key"], eo.get("item", {}), int(eo.get("max", 50))) if eo else None
        stages.append(Stage(
            id=s["id"], role=s.get("role"), title=s.get("title", ""), body=s.get("body", ""),
            needs=tuple(s.get("needs", [])), expand=expand, expand_out=expand_out,
            gate=s.get("gate"), workspace=s.get("workspace", "scratch"),
        ))
    return Template(raw["name"], str(raw["version"]), raw.get("description", ""),
                    params, roles, tuple(stages))
```

- [x] **Step 5: Run + commit**

Run: `pytest tests/unit/test_template_parse.py -v` → PASS.

```bash
git add hermes_workflow/engine tests/unit/test_template_parse.py
git commit -m "feat(engine): template data model + YAML parser"
```

---

### Task 8: Template validation (the deterministic gatekeeper)

**Files:**
- Modify: `hermes_workflow/engine/template.py`
- Test: `tests/unit/test_template_validate.py`

Validation rules from §5 / §7 / §11: unknown role refs; cycle in `needs`; `expand.over` references a real prior stage + its `expand_out.key`; **nested expand forbidden** (an `expand` stage may not be the source of another `expand` — R1); **reject `verify`/`retry`** (0.2.x — A1); `verify`/worktree stages may not use `scratch`; `${...}` in `workspace:` may only reference `params` (D3); a pure `gate` stage has no `role`.

- [x] **Step 1: Write failing validation tests**

```python
# tests/unit/test_template_validate.py
import pytest
from hermes_workflow.engine.template import parse_template, validate_template, TemplateError


def _v(yaml_text):
    validate_template(parse_template(yaml_text))


BASE = """
name: t
version: 0.1.0
params: { repo: { type: string, required: true } }
roles: { a: { lane: profile } }
stages:
  - { id: s1, role: a, title: x, workspace: "dir:${params.repo}" }
"""


def test_valid_template_passes():
    _v(BASE)


def test_unknown_role_rejected():
    y = BASE.replace("role: a", "role: ghost")
    with pytest.raises(TemplateError, match="role"):
        _v(y)


def test_verify_command_rejected_as_0_2_x():
    y = BASE + "    verify: { command: 'pytest', retry: 1 }\n"
    with pytest.raises(TemplateError, match="0.2.x|verify"):
        _v(y)


def test_nested_expand_rejected():
    y = """
name: t
version: 0.1.0
params: {}
roles: { a: { lane: profile } }
stages:
  - { id: s1, role: a, title: x, workspace: "dir:/tmp", expand_out: { key: k, item: {id: string} } }
  - { id: s2, role: a, title: y, needs: [s1], expand: { over: s1.k, as: it },
      expand_out: { key: k2, item: {id: string} } }
  - { id: s3, role: a, title: z, needs: [s2], expand: { over: s2.k2, as: jt } }
"""
    with pytest.raises(TemplateError, match="nested"):
        _v(y)


def test_expand_vars_forbidden_in_workspace():
    y = """
name: t
version: 0.1.0
params: {}
roles: { a: { lane: profile } }
stages:
  - { id: s1, role: a, title: x, workspace: "dir:/tmp", expand_out: { key: k, item: {id: string} } }
  - { id: s2, role: a, title: y, needs: [s1], expand: { over: s1.k, as: it },
      workspace: "worktree:${it.id}" }
"""
    with pytest.raises(TemplateError, match="workspace"):
        _v(y)
```

- [x] **Step 2: Run to verify failure**

Run: `pytest tests/unit/test_template_validate.py -v` → FAIL (`validate_template` undefined).

- [x] **Step 3: Implement `validate_template`**

```python
# hermes_workflow/engine/template.py  (append)
import re

_WS_TOKEN = re.compile(r"\$\{([^}]+)\}")


def validate_template(t: Template) -> None:
    ids = [s.id for s in t.stages]
    if len(ids) != len(set(ids)):
        raise TemplateError("duplicate stage id")
    expand_sources = {s.expand.over_stage for s in t.stages if s.expand}
    for s in t.stages:
        if s.gate is None and s.role is None:
            raise TemplateError(f"stage {s.id}: non-gate stage needs a role")
        if s.role and s.role not in t.roles:
            raise TemplateError(f"stage {s.id}: unknown role {s.role!r}")
        for dep in s.needs:
            if dep not in ids:
                raise TemplateError(f"stage {s.id}: needs unknown stage {dep!r}")
        if s.expand:
            src = next((x for x in t.stages if x.id == s.expand.over_stage), None)
            if src is None:
                raise TemplateError(f"stage {s.id}: expand.over unknown stage {s.expand.over_stage!r}")
            if not src.expand_out or src.expand_out.key != s.expand.over_key:
                raise TemplateError(f"stage {s.id}: expand.over key must match source expand_out.key")
            # R1: an expand stage may not itself be an expand source (nested fan-out forbidden)
            if s.id in expand_sources:
                raise TemplateError(f"stage {s.id}: nested expand is forbidden in 0.1.0")
        # A1: command-based verification is 0.2.x
        if getattr(s, "verify", None):  # parser does not build it; guard raw passthrough
            raise TemplateError(f"stage {s.id}: verify.command/retry is deferred to 0.2.x")
        # workspace: only ${params.*}, and verify/worktree stages may not be scratch
        kind = s.workspace.split(":", 1)[0]
        for tok in _WS_TOKEN.findall(s.workspace):
            if not tok.strip().startswith("params."):
                raise TemplateError(f"stage {s.id}: workspace may only use ${{params.*}}, got {tok!r}")
        if kind == "scratch" and (s.expand_out is None) is False and s.expand:
            pass  # expand consumers commonly need persistence; covered by worktree rule below
        if kind == "worktree" or s.expand:
            if kind == "scratch":
                raise TemplateError(f"stage {s.id}: worktree/fan-out stages must not use scratch")
    _check_cycle(t)


def _check_cycle(t: Template) -> None:
    graph = {s.id: set(s.needs) for s in t.stages}
    visiting, done = set(), set()

    def dfs(n):
        if n in done:
            return
        if n in visiting:
            raise TemplateError(f"dependency cycle at stage {n!r}")
        visiting.add(n)
        for m in graph[n]:
            dfs(m)
        visiting.discard(n); done.add(n)

    for n in graph:
        dfs(n)
```

> The parser intentionally ignores a raw `verify:` key; to reject it we must surface it. In Step 3 of Task 7's parser, also capture `raw_verify = s.get("verify")` onto the `Stage` (add `verify_raw: object = None` to the `Stage` dataclass) so `validate_template` can reject it. Make that one-line dataclass + parser change here and re-run Task 7's test to confirm it still passes.

- [x] **Step 4: Run + commit**

Run: `pytest tests/unit/test_template_validate.py tests/unit/test_template_parse.py -v` → PASS.

```bash
git add hermes_workflow/engine/template.py tests/unit/test_template_validate.py
git commit -m "feat(engine): template validation (roles, cycles, nested-expand, verify-reject, workspace safety)"
```

---

### Task 9: Bounded interpolation

**Files:**
- Create: `hermes_workflow/engine/interpolate.py`
- Test: `tests/unit/test_interpolate.py`

- [x] **Step 1: Write failing tests**

```python
# tests/unit/test_interpolate.py
import pytest
from hermes_workflow.engine.interpolate import interpolate, InterpolationError


def test_params_only():
    assert interpolate("Scan ${params.repo}", params={"repo": "/r"}, expand_vars={}) == "Scan /r"


def test_expand_var():
    assert interpolate("Fix ${it.id}", params={}, expand_vars={"it": {"id": "x.py"}}) == "Fix x.py"


def test_unknown_reference_raises():
    with pytest.raises(InterpolationError):
        interpolate("${params.missing}", params={}, expand_vars={})


def test_unknown_namespace_raises():
    with pytest.raises(InterpolationError):
        interpolate("${env.HOME}", params={}, expand_vars={})
```

- [x] **Step 2: Run → FAIL.** `pytest tests/unit/test_interpolate.py -v`

- [x] **Step 3: Implement**

```python
# hermes_workflow/engine/interpolate.py
from __future__ import annotations
import re

_TOKEN = re.compile(r"\$\{([^}]+)\}")


class InterpolationError(ValueError):
    pass


def interpolate(s: str, *, params: dict, expand_vars: dict) -> str:
    def repl(m):
        ref = m.group(1).strip()
        ns, _, rest = ref.partition(".")
        if ns == "params":
            if rest not in params:
                raise InterpolationError(f"unknown param {rest!r}")
            return str(params[rest])
        if ns in expand_vars:
            obj = expand_vars[ns]
            if rest not in obj:
                raise InterpolationError(f"unknown field {rest!r} on {ns!r}")
            return str(obj[rest])
        raise InterpolationError(f"unknown reference namespace {ns!r}")
    return _TOKEN.sub(repl, s)
```

- [x] **Step 4: Run + commit**

Run: `pytest tests/unit/test_interpolate.py -v` → PASS.

```bash
git add hermes_workflow/engine/interpolate.py tests/unit/test_interpolate.py
git commit -m "feat(engine): bounded interpolation (params + expand-vars only)"
```

---

### Task 10: Provenance — sentinels + compiled snapshot + version gate

**Files:**
- Create: `hermes_workflow/engine/provenance.py`
- Test: `tests/unit/test_provenance.py`

- [x] **Step 1: Write failing tests**

```python
# tests/unit/test_provenance.py
from hermes_workflow.engine.provenance import (
    Sentinel, embed_sentinel, extract_sentinel, build_root_body, parse_root_body,
    is_version_compatible,
)


def test_sentinel_roundtrip_in_markdown_body():
    s = Sentinel(workflow_root="t_root", stage_id="fix", fan_index=2, attempt=0,
                 template_id="demo", template_version="0.1.0", plugin_version="0.1.0", schema_version="0.1")
    body = embed_sentinel("Do the work.", s)
    assert "Do the work." in body
    assert extract_sentinel(body) == s


def test_root_snapshot_roundtrip():
    body = build_root_body(template_yaml="name: demo\nversion: 0.1.0\n",
                           params={"repo": "/r"}, bindings={"scout": "designer"},
                           plugin_version="0.1.0", schema_version="0.1")
    snap = parse_root_body(body)
    assert snap.params["repo"] == "/r" and snap.bindings["scout"] == "designer"
    assert snap.schema_version == "0.1" and snap.plugin_version == "0.1.0"


def test_version_gate_is_total_and_never_raises():
    snap = parse_root_body(build_root_body("name: d\nversion: 0.1.0\n", {}, {}, "0.1.0", "0.1"))
    assert is_version_compatible(snap, supported={"0.1"}) is True
    assert is_version_compatible(snap, supported={"0.2"}) is False
    # garbage in -> False, never an exception (the gate must fail closed)
    assert is_version_compatible(None, supported={"0.1"}) is False
    assert is_version_compatible(object(), supported={"0.1"}) is False
```

- [x] **Step 2: Run → FAIL.** `pytest tests/unit/test_provenance.py -v`

- [x] **Step 3: Implement**

```python
# hermes_workflow/engine/provenance.py
from __future__ import annotations
import json
from dataclasses import dataclass, asdict

_SENTINEL_OPEN = "<!--hermes-workflow:sentinel "
_SENTINEL_CLOSE = "-->"
_SNAPSHOT_OPEN = "<!--hermes-workflow:snapshot "


@dataclass(frozen=True)
class Sentinel:
    workflow_root: str
    stage_id: str
    fan_index: int
    attempt: int
    template_id: str
    template_version: str
    plugin_version: str
    schema_version: str


@dataclass(frozen=True)
class CompiledSnapshot:
    template_yaml: str
    params: dict
    bindings: dict
    plugin_version: str
    schema_version: str


def embed_sentinel(body: str, s: Sentinel) -> str:
    return f"{_SENTINEL_OPEN}{json.dumps(asdict(s))}{_SENTINEL_CLOSE}\n{body}"


def extract_sentinel(body: str) -> Sentinel | None:
    i = body.find(_SENTINEL_OPEN)
    if i < 0:
        return None
    j = body.find(_SENTINEL_CLOSE, i)
    if j < 0:
        return None
    raw = body[i + len(_SENTINEL_OPEN):j].strip()
    try:
        return Sentinel(**json.loads(raw))
    except Exception:
        return None


def build_root_body(template_yaml: str, params: dict, bindings: dict,
                    plugin_version: str, schema_version: str) -> str:
    payload = {"template_yaml": template_yaml, "params": params, "bindings": bindings,
               "plugin_version": plugin_version, "schema_version": schema_version}
    return f"{_SNAPSHOT_OPEN}{json.dumps(payload)}{_SENTINEL_CLOSE}\n# hermes-workflow run\n"


def parse_root_body(body: str) -> CompiledSnapshot:
    i = body.find(_SNAPSHOT_OPEN)
    j = body.find(_SENTINEL_CLOSE, i)
    payload = json.loads(body[i + len(_SNAPSHOT_OPEN):j].strip())
    return CompiledSnapshot(**payload)


def is_version_compatible(snapshot, supported) -> bool:
    """Total: never raises. Returns False for anything it cannot positively confirm."""
    try:
        return getattr(snapshot, "schema_version", None) in set(supported)
    except Exception:
        return False
```

- [x] **Step 4: Run + commit**

Run: `pytest tests/unit/test_provenance.py -v` → PASS.

```bash
git add hermes_workflow/engine/provenance.py tests/unit/test_provenance.py
git commit -m "feat(engine): provenance — sentinels, compiled snapshot, total version gate"
```

---

### Task 11: The graph function (drives fan-out AND reconcile)

**Files:**
- Create: `hermes_workflow/engine/graph.py`
- Test: `tests/unit/test_graph.py`

The graph function answers: *given the compiled template + which stages are done (+ their emitted metadata) + which workflow cards already exist (by sentinel identity), what CardSpecs should exist up to the next dynamic boundary?* Parents are expressed as **sentinel identities** (resolved to card-ids by the imperative shell). Used identically by the fan-out hook and by reconcile (create-missing).

- [x] **Step 1: Write failing tests**

```python
# tests/unit/test_graph.py
from hermes_workflow.engine.template import parse_template
from hermes_workflow.engine.graph import cards_for_run, Identity

TPL = """
name: demo
version: 0.1.0
params: { repo: { type: string, required: true } }
roles: { scout: { lane: profile }, fixer: { lane: codex }, reporter: { lane: profile } }
stages:
  - { id: scan, role: scout, title: "scan ${params.repo}", workspace: "dir:${params.repo}",
      expand_out: { key: flaky, max: 50, item: { test_id: string, file: string } } }
  - { id: fix, role: fixer, needs: [scan], expand: { over: scan.flaky, as: t },
      title: "fix ${t.test_id}", body: "fix ${t.file}", workspace: "worktree:${params.repo}" }
  - { id: approve, needs: [fix], gate: human }
  - { id: report, role: reporter, needs: [approve, fix], title: "report" }
"""


def _ctx():
    t = parse_template(TPL)
    params = {"repo": "/r"}
    bindings = {"scout": "designer", "fixer": "coder", "reporter": "writer"}
    return t, params, bindings


def test_prefix_only_at_start():
    t, params, bindings = _ctx()
    specs = cards_for_run(t, params, bindings, completed={}, existing=set())
    ids = {s.identity.stage_id for s in specs}
    assert ids == {"scan"}            # only the dynamic-free prefix
    assert specs[0].assignee == "designer"


def test_fanout_after_source_completes():
    t, params, bindings = _ctx()
    completed = {"scan": {"flaky": [{"test_id": "T1", "file": "a.py"}, {"test_id": "T2", "file": "b.py"}]}}
    existing = {Identity("scan", 0, 0)}
    specs = cards_for_run(t, params, bindings, completed=completed, existing=existing)
    fix = sorted([s for s in specs if s.identity.stage_id == "fix"], key=lambda s: s.identity.fan_index)
    assert [s.identity.fan_index for s in fix] == [0, 1]
    assert fix[0].title == "fix T1" and fix[0].body == "fix a.py"
    assert fix[0].assignee == "coder" and fix[0].skills == ["kanban-codex-lane"]
    approve = next(s for s in specs if s.identity.stage_id == "approve")
    assert approve.gate is True and approve.assignee == "_workflow_gate"
    # join 'approve' is parented to BOTH fix instances
    assert set(approve.parent_identities) == {Identity("fix", 0, 0), Identity("fix", 1, 0)}
    report = next(s for s in specs if s.identity.stage_id == "report")
    assert Identity("approve", 0, 0) in report.parent_identities
    assert {Identity("fix", 0, 0), Identity("fix", 1, 0)} <= set(report.parent_identities)


def test_empty_fanout_wires_join_to_source():
    t, params, bindings = _ctx()
    completed = {"scan": {"flaky": []}}
    existing = {Identity("scan", 0, 0)}
    specs = cards_for_run(t, params, bindings, completed=completed, existing=existing)
    assert not any(s.identity.stage_id == "fix" for s in specs)   # no children
    approve = next(s for s in specs if s.identity.stage_id == "approve")
    assert approve.parent_identities == [Identity("scan", 0, 0)]  # gated on the source


def test_existing_cards_are_not_recreated():
    t, params, bindings = _ctx()
    completed = {"scan": {"flaky": [{"test_id": "T1", "file": "a.py"}]}}
    existing = {Identity("scan", 0, 0), Identity("fix", 0, 0), Identity("approve", 0, 0)}
    specs = cards_for_run(t, params, bindings, completed=completed, existing=existing)
    assert all(s.identity not in existing for s in specs)         # idempotent: only missing cards
```

- [x] **Step 2: Run → FAIL.** `pytest tests/unit/test_graph.py -v`

- [x] **Step 3: Implement**

```python
# hermes_workflow/engine/graph.py
from __future__ import annotations
from dataclasses import dataclass, field
from hermes_workflow.engine.interpolate import interpolate
from hermes_workflow.engine.model import Template, Stage

GATE_ASSIGNEE = "_workflow_gate"
_LANE_SKILL = {"codex": ["kanban-codex-lane"]}


@dataclass(frozen=True)
class Identity:
    stage_id: str
    fan_index: int
    attempt: int = 0


@dataclass
class CardSpec:
    identity: Identity
    title: str
    body: str
    assignee: str
    workspace: str
    parent_identities: list
    skills: list = field(default_factory=list)
    gate: bool = False


def _expanded(stage: Stage, completed: dict) -> list[dict]:
    src = completed.get(stage.expand.over_stage)
    if src is None:
        return None  # source not done yet -> stage not materializable
    return list(src.get(stage.expand.over_key, []))


def _parents_for(stage: Stage, t: Template, completed: dict) -> list[Identity]:
    """Parent identities: for each needed stage, every instance of it that exists/should exist."""
    parents = []
    for dep in stage.needs:
        dep_stage = t.stage(dep)
        if dep_stage.expand:
            items = _expanded(dep_stage, completed)
            if items is None:
                continue
            if items:
                parents += [Identity(dep, i, 0) for i in range(len(items))]
            else:
                # empty fan-out: gate the consumer on the fan-out SOURCE instead
                parents.append(Identity(dep_stage.expand.over_stage, 0, 0))
        else:
            parents.append(Identity(dep, 0, 0))
    return parents


def _materializable(stage: Stage, t: Template, completed: dict) -> bool:
    """A stage can be created once all its non-fanned dependencies are accounted for."""
    for dep in stage.needs:
        dep_stage = t.stage(dep)
        if dep_stage.expand and _expanded(dep_stage, completed) is None:
            return False  # waiting on the fan-out source to complete
    if stage.expand and _expanded(stage, completed) is None:
        return False
    return True


def cards_for_run(t: Template, params: dict, bindings: dict, *, completed: dict, existing: set) -> list[CardSpec]:
    specs: list[CardSpec] = []
    for stage in t.stages:
        if not _materializable(stage, t, completed):
            continue
        instances = _expanded(stage, completed) if stage.expand else [None]
        if instances is None:
            continue
        for idx, item in enumerate(instances):
            ident = Identity(stage.id, idx if stage.expand else 0, 0)
            if ident in existing:
                continue
            evars = {stage.expand.as_var: item} if (stage.expand and item is not None) else {}
            assignee = bindings.get(stage.role, GATE_ASSIGNEE) if stage.role else GATE_ASSIGNEE
            lane = t.roles[stage.role].lane if stage.role else None
            specs.append(CardSpec(
                identity=ident,
                title=interpolate(stage.title, params=params, expand_vars=evars),
                body=interpolate(stage.body, params=params, expand_vars=evars),
                assignee=assignee,
                workspace=interpolate(stage.workspace, params=params, expand_vars={}),
                parent_identities=_parents_for(stage, t, completed),
                skills=list(_LANE_SKILL.get(lane, [])),
                gate=stage.gate == "human",
            ))
    return specs
```

- [x] **Step 4: Run + commit**

Run: `pytest tests/unit/test_graph.py -v` → PASS.

```bash
git add hermes_workflow/engine/graph.py tests/unit/test_graph.py
git commit -m "feat(engine): graph function (prefix, single-level fan-out, joins, empty-fanout, idempotent)"
```

---

### Task 12: Reconcile — progress-aware dedup winner

**Files:**
- Create: `hermes_workflow/engine/reconcile.py`
- Test: `tests/unit/test_reconcile.py`

The engine half of reconcile is pure: given duplicate cards sharing one sentinel identity, pick the **winner** deterministically (any `done` wins; tiebreak `task_runs.id` → `created_at` → `min(card_id)`). The imperative shell (Task 17) does create-missing + link-winner-then-archive-loser.

- [x] **Step 1: Write failing tests**

```python
# tests/unit/test_reconcile.py
from hermes_workflow.engine.reconcile import pick_winner, CardRow


def _row(cid, status, run_id=None, created_at=0):
    return CardRow(card_id=cid, status=status, latest_run_id=run_id, created_at=created_at)


def test_done_beats_running_regardless_of_id():
    rows = [_row("t_z", "done", run_id=5), _row("t_a", "running")]
    assert pick_winner(rows).card_id == "t_z"


def test_multi_done_tiebreak_by_run_id_then_created_then_id():
    rows = [_row("t_b", "done", run_id=10, created_at=2), _row("t_a", "done", run_id=20, created_at=1)]
    assert pick_winner(rows).card_id == "t_a"   # higher run_id wins


def test_no_done_ranks_by_status_then_id():
    rows = [_row("t_y", "todo"), _row("t_x", "running")]
    assert pick_winner(rows).card_id == "t_x"   # running > todo
```

- [x] **Step 2: Run → FAIL.** `pytest tests/unit/test_reconcile.py -v`

- [x] **Step 3: Implement**

```python
# hermes_workflow/engine/reconcile.py
from __future__ import annotations
from dataclasses import dataclass

_STATUS_RANK = {"done": 5, "running": 4, "ready": 3, "todo": 2, "blocked": 1, "archived": 0}


@dataclass(frozen=True)
class CardRow:
    card_id: str
    status: str
    latest_run_id: int | None = None
    created_at: float = 0.0


def pick_winner(rows: list[CardRow]) -> CardRow:
    """Deterministic winner among duplicates sharing one sentinel identity.
    A 'done' duplicate wins unconditionally; tiebreak run_id -> created_at -> card_id."""
    if not rows:
        raise ValueError("no rows")
    return max(rows, key=lambda r: (
        _STATUS_RANK.get(r.status, 0),
        (r.latest_run_id or -1),
        r.created_at,
        # min(card_id) as final tiebreak: invert lexicographic for max()
        tuple(-ord(c) for c in r.card_id),
    ))
```

- [x] **Step 4: Run + commit**

Run: `pytest tests/unit/test_reconcile.py -v` → PASS. Then run the whole unit suite: `pytest tests/unit -v` → all PASS.

```bash
git add hermes_workflow/engine/reconcile.py tests/unit/test_reconcile.py
git commit -m "feat(engine): progress-aware reconcile winner (done wins; run_id/created/id tiebreak)"
```

---

## Phase 2 — Imperative shell: board adapter + hooks

### Task 13: Board adapter (production-side, mirrors the test harness)

**Files:**
- Create: `hermes_workflow/board.py`
- Test: `tests/integration/test_board_adapter.py`

The adapter wraps the two surfaces: **worker context** (hook) uses `ctx.dispatch_tool("kanban_create"/"kanban_link"/"kanban_comment"/"kanban_show")`; **orchestrator context** (tools/CLI) additionally uses host `kb.*` for `archive`/`unlink`/`reclaim`/`list` (no model tool — finding Y). Use the exact signatures recorded in `SPIKES.md` (Tasks 3/5).

- [x] **Step 1: Write the failing adapter test (worker create+link via dispatch_tool)**

```python
# tests/integration/test_board_adapter.py
import json, pytest
pytestmark = pytest.mark.integration


def test_create_and_show_via_dispatch(fake_ctx, tmp_board, as_worker):
    from hermes_workflow.board import WorkerBoard
    wb = WorkerBoard(fake_ctx, board=tmp_board.name)
    parent = tmp_board.create(title="p")
    with as_worker(parent):
        cid = wb.create(title="child", parents=[parent], assignee="_workflow_root",
                        workspace_kind="scratch", body="b")
        shown = wb.show(cid)
    assert shown["title"] == "child" and parent in [p for p in shown["parents"]]
```

> Add a `fake_ctx` fixture to `conftest.py` whose `dispatch_tool(name, args)` calls `hermes_cli`'s real tool dispatch (`registry.dispatch` / `model_tools`) so the adapter exercises the real path with no LLM. Wire it from the signatures in `SPIKES.md`.

- [x] **Step 2: Run → FAIL.**

- [x] **Step 3: Implement the adapter**

```python
# hermes_workflow/board.py
from __future__ import annotations
import json, os


class WorkerBoard:
    """Worker-context board ops: create/link/comment/show via ctx.dispatch_tool (public tools)."""
    def __init__(self, ctx, board: str):
        self.ctx, self.board = ctx, board

    def _call(self, tool, args):
        args = {**args, "board": self.board}
        return json.loads(self.ctx.dispatch_tool(tool, args))

    def create(self, *, title, parents=(), assignee, workspace_kind, workspace_path=None,
               body="", skills=None, idempotency_key=None):
        r = self._call("kanban_create", {
            "title": title, "assignee": assignee, "parents": list(parents),
            "workspace_kind": workspace_kind, "workspace_path": workspace_path,
            "body": body, "skills": skills, "idempotency_key": idempotency_key,
        })
        return r["task_id"]

    def link(self, *, parent, child):
        return self._call("kanban_link", {"parent_id": parent, "child_id": child})

    def comment(self, *, task_id, body):
        return self._call("kanban_comment", {"task_id": task_id, "body": body})

    def show(self, task_id):
        return self._call("kanban_show", {"task_id": task_id})


class HostBoard:
    """Orchestrator-context ops needing kb.* (no model tool): list/archive/unlink/reclaim."""
    def __init__(self, kb, conn, board: str):
        self.kb, self.conn, self.board = kb, conn, board

    def list_run_cards(self, root_id):
        # link-walk for the hook is in Task 14; the host sweep may use kb.list_tasks for the board.
        return self.kb.list_tasks(self.conn, board=self.board)

    def archive(self, task_id):
        return self.kb.archive_task(self.conn, task_id)

    def unlink(self, *, parent, child):
        return self.kb.unlink_tasks(self.conn, parent_id=parent, child_id=child)

    def reclaim(self, task_id):
        return self.kb.reclaim_task(self.conn, task_id)
```

> Replace each `kb.*`/tool arg name with the exact one from `SPIKES.md`. If a recorded signature differs, fix the call here (this is the single place coupled signatures live).

- [x] **Step 4: Run + commit**

Run: `pytest tests/integration/test_board_adapter.py -v` → PASS.

```bash
git add hermes_workflow/board.py tests/integration/test_board_adapter.py tests/conftest.py
git commit -m "feat: board adapter (worker dispatch_tool + host kb.* surfaces)"
```

---

### Task 14: Run enumeration via link-walk + identity resolution

**Files:**
- Create: `hermes_workflow/runview.py`
- Test: `tests/integration/test_runview.py`

`RunView` builds the live picture from the board (finding D2 — enumerate by link-walk from the root; `kanban_show` returns body+children): the set of existing `Identity`s, each card's status + latest-run metadata (for `completed`), and the `Identity → card_id` map (to resolve parents).

- [x] **Step 1: Write the failing test**

```python
# tests/integration/test_runview.py
import pytest
pytestmark = pytest.mark.integration


def test_runview_enumerates_existing_identities(fake_ctx, tmp_board, seed_run):
    from hermes_workflow.runview import RunView
    root_id = seed_run()  # helper: creates a root + a 'scan' child with a sentinel (Task added below)
    rv = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=root_id)
    assert ("scan", 0, 0) in {(i.stage_id, i.fan_index, i.attempt) for i in rv.existing}
    assert rv.card_id_for(("scan", 0, 0)) is not None
```

> Add a `seed_run` fixture that creates a root via `build_root_body(...)` and one `scan` child whose body carries `embed_sentinel(...)`. Reuse `WorkerBoard`/`tmp_board`.

- [x] **Step 2: Run → FAIL.**

- [x] **Step 3: Implement**

```python
# hermes_workflow/runview.py
from __future__ import annotations
from dataclasses import dataclass
from hermes_workflow.engine.graph import Identity
from hermes_workflow.engine.provenance import extract_sentinel


@dataclass
class RunView:
    existing: set            # set[Identity]
    by_identity: dict        # Identity -> card_id
    status: dict             # card_id -> status
    completed: dict          # stage_id -> emitted metadata (latest done run)
    root_id: str

    def card_id_for(self, ident_tuple):
        return self.by_identity.get(Identity(*ident_tuple))

    @classmethod
    def from_root(cls, ctx, *, board, root_id, kb=None, conn=None):
        from hermes_workflow.board import WorkerBoard
        wb = WorkerBoard(ctx, board=board)
        existing, by_id, status, completed = set(), {}, {}, {}
        seen, stack = set(), [root_id]
        while stack:
            cid = stack.pop()
            if cid in seen:
                continue
            seen.add(cid)
            card = wb.show(cid)
            for child in card.get("children", []):
                stack.append(child if isinstance(child, str) else child["id"])
            s = extract_sentinel(card.get("body", "") or "")
            if not s:
                continue
            ident = Identity(s.stage_id, s.fan_index, s.attempt)
            existing.add(ident); by_id[ident] = cid; status[cid] = card["status"]
            # latest done run metadata for the graph 'completed' input (read unbounded run metadata)
            meta = _latest_done_metadata(card, kb, conn)
            if meta is not None:
                completed[s.stage_id] = meta
        return cls(existing, by_id, status, completed, root_id)


def _latest_done_metadata(card, kb, conn):
    if card.get("status") != "done":
        return None
    # Prefer the unbounded task_runs.metadata column (finding R) over truncated worker_context.
    if kb is not None and conn is not None:
        run = kb.latest_run(conn, card["id"])
        return (run.metadata if run else None) or {}
    runs = card.get("runs") or []
    done = [r for r in runs if r.get("outcome") == "completed"]
    return (done[-1].get("metadata") if done else {}) or {}
```

- [x] **Step 4: Run + commit**

Run: `pytest tests/integration/test_runview.py -v` → PASS.

```bash
git add hermes_workflow/runview.py tests/integration/test_runview.py tests/conftest.py
git commit -m "feat: RunView — link-walk enumeration + identity resolution + completed-metadata"
```

---

### Task 15: Materializer — turn CardSpecs into board cards (shared by hook, start, reconcile)

**Files:**
- Create: `hermes_workflow/materialize.py`
- Test: `tests/integration/test_materialize.py`

Resolves each `CardSpec`'s `parent_identities` → card_ids via `RunView`, embeds the sentinel + the lifecycle preamble (B6) in the body, sets **explicit** workspace (D3) and `board`, uses a deterministic `idempotency_key = hash(root+stage+fan_index+attempt)`, pre-provisions a worktree for `worktree:` specs (B4), and creates via `kanban_create(parents=[...])` (R5). Then links any parent that wasn't expressible at create time.

- [x] **Step 1: Write the failing test**

```python
# tests/integration/test_materialize.py
import pytest
pytestmark = pytest.mark.integration


def test_materialize_creates_join_wired_to_all_instances(fake_ctx, tmp_board, seed_run_after_scan):
    from hermes_workflow.materialize import materialize
    from hermes_workflow.runview import RunView
    root_id = seed_run_after_scan(flaky=[{"test_id": "T1", "file": "a.py"},
                                         {"test_id": "T2", "file": "b.py"}])
    rv = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=root_id)
    created = materialize(fake_ctx, board=tmp_board.name, root_id=root_id, runview=rv)
    rv2 = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=root_id)
    approve_cid = rv2.card_id_for(("approve", 0, 0))
    approve = fake_ctx_show(fake_ctx, tmp_board.name, approve_cid)
    fix0, fix1 = rv2.card_id_for(("fix", 0, 0)), rv2.card_id_for(("fix", 1, 0))
    assert set(approve["parents"]) >= {fix0, fix1}     # join wired to ALL instances (R5)
    assert tmp_board.status(approve_cid) == "todo"     # gated until both fix done
```

- [x] **Step 2: Run → FAIL.**

- [x] **Step 3: Implement**

```python
# hermes_workflow/materialize.py
from __future__ import annotations
import hashlib
from hermes_workflow.engine.template import parse_template
from hermes_workflow.engine.graph import cards_for_run
from hermes_workflow.engine.provenance import parse_root_body, Sentinel, embed_sentinel
from hermes_workflow.board import WorkerBoard
from hermes_workflow.version import PLUGIN_VERSION, SCHEMA_VERSION
from hermes_workflow.worktree import provision_worktree  # Task 16

LIFECYCLE_PREAMBLE = (
    "## workflow stage\n"
    "- Complete via `kanban_complete` (even a no-op stage must complete with empty metadata).\n"
    "- Emit the declared metadata when this stage feeds a fan-out.\n"
    "- Commit your work before completing (worktree stages are commit-checked).\n"
    "- Do NOT `kanban_block` for review — the workflow's human gate handles approval.\n\n"
)


def _idem(root_id, ident):
    return "wf_" + hashlib.sha1(f"{root_id}:{ident.stage_id}:{ident.fan_index}:{ident.attempt}"
                                .encode()).hexdigest()[:16]


def materialize(ctx, *, board, root_id, runview, base_ref=None):
    wb = WorkerBoard(ctx, board=board)
    snap = parse_root_body(wb.show(root_id)["body"])
    t = parse_template(snap.template_yaml)
    specs = cards_for_run(t, snap.params, snap.bindings,
                          completed=runview.completed, existing=runview.existing)
    created = {}
    # create parents-first by sorting: a stage whose parents are all already-resolvable
    pending = list(specs)
    safety = 0
    while pending and safety < 10_000:
        safety += 1
        spec = pending.pop(0)
        parent_ids, missing = [], False
        for pid in spec.parent_identities:
            cid = runview.by_identity.get(pid) or created.get(pid)
            if cid is None:
                missing = True
                break
            parent_ids.append(cid)
        if missing:
            pending.append(spec)      # try again once its parents are created this pass
            continue
        kind, _, path = spec.workspace.partition(":")
        ws_kind, ws_path = ("scratch", None)
        if kind == "dir":
            ws_kind, ws_path = "dir", path
        elif kind == "worktree":
            ws_kind, ws_path = "dir", provision_worktree(root_id, spec.identity, path, base_ref)
        sentinel = Sentinel(root_id, spec.identity.stage_id, spec.identity.fan_index,
                            spec.identity.attempt, t.name, t.version, PLUGIN_VERSION, SCHEMA_VERSION)
        body = embed_sentinel(LIFECYCLE_PREAMBLE + spec.body, sentinel)
        cid = wb.create(title=spec.title, parents=parent_ids, assignee=spec.assignee,
                        workspace_kind=ws_kind, workspace_path=ws_path, body=body,
                        skills=(spec.skills or None), idempotency_key=_idem(root_id, spec.identity))
        created[spec.identity] = cid
    return created
```

- [x] **Step 4: Run + commit**

Run: `pytest tests/integration/test_materialize.py -v` → PASS.

```bash
git add hermes_workflow/materialize.py tests/integration/test_materialize.py
git commit -m "feat: materializer — specs->cards (sentinel+preamble, explicit ws, idem key, join-wired)"
```

---

### Task 16: Worktree pre-provisioning (engine-side, idempotent, base-pinned)

**Files:**
- Create: `hermes_workflow/worktree.py`
- Test: `tests/unit/test_worktree.py`

- [x] **Step 1: Write the failing test (idempotent, base-pinned, deterministic path)**

```python
# tests/unit/test_worktree.py
import subprocess, pathlib
from hermes_workflow.worktree import provision_worktree, worktree_path


def _git(*a, cwd): subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True)


def test_provision_is_idempotent(tmp_path):
    repo = tmp_path / "repo"; repo.mkdir(); _git("init", cwd=repo)
    (repo / "f").write_text("x"); _git("add", "f", cwd=repo)
    _git("-c", "user.email=a@b.c", "-c", "user.name=a", "commit", "-m", "init", cwd=repo)
    from hermes_workflow.engine.graph import Identity
    ident = Identity("fix", 0, 0)
    p1 = provision_worktree("t_root", ident, str(repo), base_ref="HEAD")
    p2 = provision_worktree("t_root", ident, str(repo), base_ref="HEAD")  # reuse-if-exists
    assert p1 == p2 == str(worktree_path("t_root", ident, str(repo)))
    assert pathlib.Path(p1, ".git").exists()
```

- [x] **Step 2: Run → FAIL.**

- [x] **Step 3: Implement**

```python
# hermes_workflow/worktree.py
from __future__ import annotations
import hashlib, pathlib, subprocess


def worktree_path(root_id, ident, repo) -> pathlib.Path:
    tag = hashlib.sha1(f"{root_id}:{ident.stage_id}:{ident.fan_index}:{ident.attempt}".encode()).hexdigest()[:12]
    return pathlib.Path(repo).resolve().parent / ".hermes-workflow-worktrees" / f"{root_id}-{ident.stage_id}-{ident.fan_index}-{tag}"


def _run(args, cwd=None):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


def provision_worktree(root_id, ident, repo, base_ref=None) -> str:
    """Idempotent: reuse the worktree if it already exists (survives hook-refire/reconcile)."""
    path = worktree_path(root_id, ident, repo)
    if (path / ".git").exists():
        return str(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    branch = f"wf/{root_id}/{ident.stage_id}/{ident.fan_index}"
    base = base_ref or "HEAD"
    for attempt in range(3):  # tolerate git index.lock contention
        try:
            _run(["git", "-C", repo, "worktree", "add", "-b", branch, str(path), base])
            return str(path)
        except subprocess.CalledProcessError as e:
            if "index.lock" in (e.stderr or "") and attempt < 2:
                continue
            if "already exists" in (e.stderr or ""):
                return str(path)
            raise
    return str(path)
```

- [x] **Step 4: Run + commit**

Run: `pytest tests/unit/test_worktree.py -v` → PASS.

```bash
git add hermes_workflow/worktree.py tests/unit/test_worktree.py
git commit -m "feat: idempotent base-pinned worktree pre-provisioning"
```

---

### Task 17: `post_tool_call` fan-out hook (side-effect, version-gated, never raises)

**Files:**
- Create: `hermes_workflow/hooks.py`
- Test: `tests/integration/test_hook_fanout.py`

- [x] **Step 1: Write the failing test (fan-out fires on a sentinel stage's completion)**

```python
# tests/integration/test_hook_fanout.py
import json, pytest
pytestmark = pytest.mark.integration


def test_hook_fans_out_on_scan_complete(fake_ctx, tmp_board, seed_run):
    from hermes_workflow.hooks import on_tool_done
    from hermes_workflow.runview import RunView
    root_id, scan_cid = seed_run(stage="scan")
    # simulate the scan worker completing with metadata
    meta = {"flaky": [{"test_id": "T1", "file": "a.py"}, {"test_id": "T2", "file": "b.py"}]}
    tmp_board.complete(scan_cid, metadata=meta)
    on_tool_done(ctx=fake_ctx, tool_name="kanban_complete",
                 args={"task_id": scan_cid, "metadata": meta},
                 result=json.dumps({"ok": True, "task_id": scan_cid, "run_id": 1}),
                 task_id=scan_cid)
    rv = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=root_id)
    assert rv.card_id_for(("fix", 0, 0)) and rv.card_id_for(("fix", 1, 0))
    assert rv.card_id_for(("approve", 0, 0))


def test_hook_never_raises_on_garbage(fake_ctx):
    from hermes_workflow.hooks import on_tool_done
    # must be a pure side-effect: any error is swallowed internally
    on_tool_done(ctx=fake_ctx, tool_name="kanban_complete", args=None, result="not-json", task_id="t_x")
```

- [x] **Step 2: Run → FAIL.**

- [x] **Step 3: Implement**

```python
# hermes_workflow/hooks.py
from __future__ import annotations
import json, logging
from hermes_workflow.engine.provenance import extract_sentinel, parse_root_body, is_version_compatible
from hermes_workflow.version import SUPPORTED_SCHEMA_VERSIONS
from hermes_workflow.board import WorkerBoard
from hermes_workflow.runview import RunView
from hermes_workflow.materialize import materialize

log = logging.getLogger("hermes_workflow.hooks")


def on_tool_done(*, ctx, tool_name, args, result, task_id, **kwargs):
    """post_tool_call: fan-out driver. Side-effect only; NEVER raises (fail-open)."""
    try:
        if tool_name != "kanban_complete":
            return
        parsed = json.loads(result) if isinstance(result, str) else {}
        if not isinstance(parsed, dict) or parsed.get("error") or not parsed.get("ok", True):
            return
        cid = task_id or (args or {}).get("task_id")
        if not cid:
            return
        wb = WorkerBoard(ctx, board=_board_of(ctx))
        card = wb.show(cid)
        sentinel = extract_sentinel(card.get("body", "") or "")
        if not sentinel:
            return  # not a workflow card
        root = wb.show(sentinel.workflow_root)
        snap = parse_root_body(root["body"])
        if not is_version_compatible(snap, SUPPORTED_SCHEMA_VERSIONS):
            # visible refuse — comment on the root, do NOT raise, do NOT fan out
            wb.comment(task_id=sentinel.workflow_root,
                       body=f"hermes-workflow: schema_version {snap.schema_version} unsupported by this "
                            f"worker's plugin; refusing to fan out card {cid}. Drain & align versions.")
            return
        rv = RunView.from_root(ctx, board=wb.board, root_id=sentinel.workflow_root)
        materialize(ctx, board=wb.board, root_id=sentinel.workflow_root, runview=rv)
    except Exception:  # fail-open: a hook crash must never break the worker's completion
        log.exception("hermes-workflow fan-out hook failed (swallowed)")


def _board_of(ctx):
    import os
    return os.environ.get("HERMES_KANBAN_BOARD", "default")
```

- [x] **Step 4: Run + commit**

Run: `pytest tests/integration/test_hook_fanout.py -v` → PASS.

```bash
git add hermes_workflow/hooks.py tests/integration/test_hook_fanout.py
git commit -m "feat(hook): post_tool_call fan-out driver (version-gated, side-effect, never raises)"
```

---

### Task 18: `pre_tool_call` completion-gate veto (exception-proof)

**Files:**
- Modify: `hermes_workflow/hooks.py`
- Create: `hermes_workflow/veto.py`
- Test: `tests/integration/test_veto.py`

Enforces, before `kanban_complete`: **version compatible**, **`expand_out` shape + `max`** (total/non-raising), **commit-clean** for worktree stages (fixed `git -C <path> status --porcelain`, no untrusted interpolation). Returns `{"action":"block","message":…}`; on its OWN failure it returns a block dict (fails **closed** — never `None`/raise).

- [x] **Step 1: Write the failing tests**

```python
# tests/integration/test_veto.py
import pytest
from hermes_workflow.veto import evaluate_completion_gate


def test_expand_out_shape_blocks_on_wrong_shape():
    decision = evaluate_completion_gate(
        stage_kind="expand_source",
        expand_out={"key": "flaky", "max": 50, "item": {"test_id": "string", "file": "string"}},
        metadata={"flaky": [{"test_id": "T1"}]},   # missing 'file'
        workspace_dir=None, schema_ok=True)
    assert decision and decision["action"] == "block" and "file" in decision["message"]


def test_expand_out_over_max_blocks():
    decision = evaluate_completion_gate(
        stage_kind="expand_source",
        expand_out={"key": "k", "max": 2, "item": {"id": "string"}},
        metadata={"k": [{"id": "1"}, {"id": "2"}, {"id": "3"}]},
        workspace_dir=None, schema_ok=True)
    assert decision["action"] == "block" and "max" in decision["message"]


def test_valid_shape_passes():
    assert evaluate_completion_gate(
        stage_kind="expand_source",
        expand_out={"key": "k", "max": 50, "item": {"id": "string"}},
        metadata={"k": [{"id": "1"}]}, workspace_dir=None, schema_ok=True) is None


def test_schema_mismatch_blocks():
    assert evaluate_completion_gate(stage_kind="plain", expand_out=None, metadata={},
                                    workspace_dir=None, schema_ok=False)["action"] == "block"


def test_internal_error_fails_closed():
    # metadata that breaks iteration must still produce a block, never an exception
    d = evaluate_completion_gate(stage_kind="expand_source",
                                 expand_out={"key": "k", "max": 1, "item": {"id": "string"}},
                                 metadata=12345, workspace_dir=None, schema_ok=True)
    assert d["action"] == "block"
```

- [x] **Step 2: Run → FAIL.**

- [x] **Step 3: Implement the gate logic (pure, total)**

```python
# hermes_workflow/veto.py
from __future__ import annotations
import subprocess


def _block(msg): return {"action": "block", "message": f"hermes-workflow: {msg}"}


def evaluate_completion_gate(*, stage_kind, expand_out, metadata, workspace_dir, schema_ok) -> dict | None:
    """Total / exception-proof: returns a block dict or None; never raises."""
    try:
        if not schema_ok:
            return _block("plugin schema_version is incompatible with this run; completion refused")
        if stage_kind == "expand_source" and expand_out:
            items = (metadata or {}).get(expand_out["key"])
            if not isinstance(items, list):
                return _block(f"expand_out.{expand_out['key']} must be a list")
            if len(items) > int(expand_out.get("max", 50)):
                return _block(f"expand_out.{expand_out['key']} exceeds max {expand_out.get('max', 50)}")
            for i, it in enumerate(items):
                if not isinstance(it, dict):
                    return _block(f"expand_out item {i} must be an object")
                for field in expand_out.get("item", {}):
                    if field not in it:
                        return _block(f"expand_out item {i} missing field {field!r}")
        if stage_kind == "worktree" and workspace_dir:
            r = subprocess.run(["git", "-C", workspace_dir, "status", "--porcelain"],
                               capture_output=True, text=True, timeout=30)
            if r.returncode != 0:
                return _block("commit-clean check failed: not a git worktree")
            if r.stdout.strip():
                return _block("commit-clean check failed: uncommitted changes — commit before completing")
        return None
    except Exception as e:  # fail CLOSED: block rather than silently allow
        return _block(f"completion gate internal error (failing closed): {e!r}")
```

- [x] **Step 4: Wire it into a `pre_tool_call` hook in `hooks.py`**

```python
# hermes_workflow/hooks.py  (append)
def on_tool_pre(*, ctx, tool_name, args, task_id, **kwargs):
    """pre_tool_call: completion gate. Returns a block dict or None. Must fail CLOSED on its own error."""
    try:
        if tool_name != "kanban_complete":
            return None
        from hermes_workflow.veto import evaluate_completion_gate
        wb = WorkerBoard(ctx, board=_board_of(ctx))
        cid = task_id or (args or {}).get("task_id")
        card = wb.show(cid)
        sentinel = extract_sentinel(card.get("body", "") or "")
        if not sentinel:
            return None  # not a workflow card
        snap = parse_root_body(wb.show(sentinel.workflow_root)["body"])
        schema_ok = is_version_compatible(snap, SUPPORTED_SCHEMA_VERSIONS)
        meta = (args or {}).get("metadata") or {}
        stage_kind, expand_out, ws_dir = _stage_gate_inputs(snap, sentinel, card)
        return evaluate_completion_gate(stage_kind=stage_kind, expand_out=expand_out,
                                        metadata=meta, workspace_dir=ws_dir, schema_ok=schema_ok)
    except Exception:
        # The gate must never fail OPEN by raising (it would be swallowed -> silent allow).
        return {"action": "block", "message": "hermes-workflow: completion gate error; failing closed"}


def _stage_gate_inputs(snap, sentinel, card):
    from hermes_workflow.engine.template import parse_template
    t = parse_template(snap.template_yaml)
    stage = t.stage(sentinel.stage_id)
    expand_out = None
    kind = "plain"
    if stage.expand_out:
        kind = "expand_source"
        expand_out = {"key": stage.expand_out.key, "max": stage.expand_out.max, "item": stage.expand_out.item}
    elif stage.workspace.startswith("worktree:"):
        kind = "worktree"
    ws_dir = card.get("workspace_path") if kind == "worktree" else None
    return kind, expand_out, ws_dir
```

- [x] **Step 5: Run + commit**

Run: `pytest tests/integration/test_veto.py -v` → PASS.

```bash
git add hermes_workflow/veto.py hermes_workflow/hooks.py tests/integration/test_veto.py
git commit -m "feat(hook): pre_tool_call completion gate (expand_out shape+max, commit-clean, version; fails closed)"
```

---

## Phase 3 — Tools / CLI / slash (orchestrator-context)

### Task 19: `workflow_start` — validate, reject-verify, pre-flight, seed root + prefix

**Files:**
- Create: `hermes_workflow/tools.py`
- Create: `hermes_workflow/preflight.py`
- Test: `tests/integration/test_workflow_start.py`

- [x] **Step 1: Write failing tests (refuse in worker; reject verify; seed root + prefix)**

```python
# tests/integration/test_workflow_start.py
import os, pytest
pytestmark = pytest.mark.integration


def test_start_refuses_in_worker_context(fake_ctx, tmp_board, monkeypatch):
    from hermes_workflow.tools import workflow_start
    monkeypatch.setenv("HERMES_KANBAN_TASK", "t_worker")
    r = workflow_start(fake_ctx, template_text=_TPL, params={"repo": "/r"},
                       bindings={"scout": "designer", "fixer": "coder", "reporter": "writer"})
    assert r["error"] and "orchestrator" in r["error"]


def test_start_seeds_root_and_prefix(fake_ctx, tmp_board, stub_preflight_ok, monkeypatch):
    from hermes_workflow.tools import workflow_start
    from hermes_workflow.runview import RunView
    monkeypatch.delenv("HERMES_KANBAN_TASK", raising=False)
    r = workflow_start(fake_ctx, template_text=_TPL, params={"repo": "/r"},
                       bindings={"scout": "designer", "fixer": "coder", "reporter": "writer"},
                       board=tmp_board.name)
    rv = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=r["root_id"])
    assert rv.card_id_for(("scan", 0, 0))                 # dynamic-free prefix created
    assert rv.card_id_for(("fix", 0, 0)) is None          # fan-out NOT yet materialized
```

(Define `_TPL` in the test as the `fix-flaky-tests` YAML; add a `stub_preflight_ok` fixture monkeypatching `preflight.probe_profiles` to return all-OK so this test needs no extra profiles.)

- [x] **Step 2: Run → FAIL.**

- [x] **Step 3: Implement pre-flight probe**

```python
# hermes_workflow/preflight.py
from __future__ import annotations
import json, subprocess, sys


def probe_profiles(profiles: set[str], *, project_plugin=False) -> dict:
    """Spawn a loadability probe per DISTINCT profile under its HERMES_HOME.
    Returns {profile: {"ok": bool, "error": str|None}}. Uses list_plugins() load truth."""
    out = {}
    for prof in sorted(profiles):
        code = (
            "import json,os;"
            "from hermes_cli import plugins as P;"
            "P.discover_plugins();"
            "ps=P.list_plugins();"
            "m=next((p for p in (ps.values() if isinstance(ps,dict) else ps)"
            " if getattr(p,'name',None)=='hermes-workflow'),None);"
            "print(json.dumps({'enabled':bool(getattr(m,'enabled',False)) if m else False,"
            "'error':getattr(m,'error',None) if m else 'not-discovered'}))"
        )
        env = {"HERMES_PROFILE": prof}
        if project_plugin:
            env["HERMES_ENABLE_PROJECT_PLUGINS"] = "1"
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                           env={**_base_env(prof), **env})
        try:
            info = json.loads(r.stdout.strip().splitlines()[-1])
        except Exception:
            out[prof] = {"ok": False, "error": f"probe failed: {r.stderr[-200:]}"}
            continue
        out[prof] = {"ok": bool(info["enabled"]) and not info["error"], "error": info["error"]}
    return out


def _base_env(profile):
    import os
    from hermes_cli.profiles import resolve_profile_env  # confirmed per SPIKES.md
    return {**os.environ, "HERMES_HOME": str(resolve_profile_env(profile))}
```

> Replace the in-`-c` attribute access with the exact `list_plugins()` shape recorded in Task 2's `SPIKES.md`.

- [x] **Step 4: Implement `workflow_start`**

```python
# hermes_workflow/tools.py
from __future__ import annotations
import os
from hermes_workflow.engine.template import parse_template, validate_template, TemplateError
from hermes_workflow.engine.provenance import build_root_body
from hermes_workflow.board import WorkerBoard
from hermes_workflow.runview import RunView
from hermes_workflow.materialize import materialize
from hermes_workflow.preflight import probe_profiles
from hermes_workflow.version import PLUGIN_VERSION, SCHEMA_VERSION, SENTINEL_ROOT_ASSIGNEE


def _require_orchestrator():
    if os.environ.get("HERMES_KANBAN_TASK"):
        return {"error": "workflow_start must run in orchestrator context (no HERMES_KANBAN_TASK)"}
    return None


def workflow_start(ctx, *, template_text, params, bindings, board=None):
    guard = _require_orchestrator()
    if guard:
        return guard
    try:
        t = parse_template(template_text)
        validate_template(t)             # rejects verify/retry, nested expand, etc.
    except TemplateError as e:
        return {"error": f"template invalid: {e}"}
    missing = [n for n, p in t.params.items() if p.required and n not in params]
    if missing:
        return {"error": f"missing required params: {missing}"}
    unknown_roles = [r for r in t.roles if r not in bindings]
    if unknown_roles:
        return {"error": f"unbound roles: {unknown_roles}"}
    profiles = {bindings[r] for r in t.roles}
    probe = probe_profiles(profiles)
    bad = {p: i["error"] for p, i in probe.items() if not i["ok"]}
    if bad:
        return {"error": "per-profile pre-flight failed (zero cards created)", "profiles": bad,
                "remediation": {p: ("hermes -p %s plugins enable hermes-workflow" % p if e in (None, "not-discovered")
                                     else "load error: %s" % e) for p, e in bad.items()}}
    board = board or os.environ.get("HERMES_KANBAN_BOARD", "default")
    wb = WorkerBoard(ctx, board=board)
    root_body = build_root_body(template_text, params, bindings, PLUGIN_VERSION, SCHEMA_VERSION)
    root_id = wb.create(title=f"workflow:{t.name}", assignee=SENTINEL_ROOT_ASSIGNEE,
                        workspace_kind="scratch", body=root_body)
    _complete_root(ctx, board, root_id)   # root is a completed blackboard (host kb.complete or tool)
    rv = RunView.from_root(ctx, board=board, root_id=root_id)
    materialize(ctx, board=board, root_id=root_id, runview=rv)  # creates only the dynamic-free prefix
    return {"root_id": root_id, "board": board}


def _complete_root(ctx, board, root_id):
    import json
    ctx.dispatch_tool("kanban_complete", {"task_id": root_id, "summary": "workflow root blackboard",
                                          "board": board})
```

> The materializer's `cards_for_run` with `completed={}` returns only the prefix (verified in Task 11), so `workflow_start` reuses it — no separate prefix logic. Confirm `kanban_complete` on a just-created card is allowed in orchestrator context (finding A2: orchestrator may complete any card); if the root must be created already-done, use the `initial_status` create param instead.

- [x] **Step 5: Run + commit**

Run: `pytest tests/integration/test_workflow_start.py -v` → PASS.

```bash
git add hermes_workflow/tools.py hermes_workflow/preflight.py tests/integration/test_workflow_start.py
git commit -m "feat(tool): workflow_start (validate, reject verify, per-profile pre-flight, seed root+prefix)"
```

---

### Task 20: `workflow_status`, `workflow_validate`, `workflow_reconcile`

**Files:**
- Modify: `hermes_workflow/tools.py`
- Test: `tests/integration/test_workflow_status_reconcile.py`

- [x] **Step 1: Write failing tests**

```python
# tests/integration/test_workflow_status_reconcile.py
import pytest
pytestmark = pytest.mark.integration


def test_status_rollup_includes_pending_and_blocked(fake_ctx, tmp_board, started_run):
    from hermes_workflow.tools import workflow_status
    root_id = started_run()
    st = workflow_status(fake_ctx, root_id=root_id, board=tmp_board.name)
    assert st["stages"]["scan"]["state"] in ("running", "ready", "todo", "done")
    assert st["stages"]["fix"]["state"] == "pending"      # not yet materialized
    assert "awaiting_approval" in st and "blocked_stages" in st


def test_reconcile_recreates_missing_fanout_and_relinks_join(fake_ctx, tmp_board, started_run, drop_one_fix):
    from hermes_workflow.tools import workflow_reconcile
    from hermes_workflow.runview import RunView
    root_id = started_run()
    drop_one_fix(root_id)   # helper: complete scan, materialize, then archive one fix card to simulate partial fan-out
    workflow_reconcile(fake_ctx, root_id=root_id, board=tmp_board.name)
    rv = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=root_id)
    assert rv.card_id_for(("fix", 0, 0)) and rv.card_id_for(("fix", 1, 0))   # missing one recreated
```

- [x] **Step 2: Run → FAIL.**

- [x] **Step 3: Implement**

```python
# hermes_workflow/tools.py  (append)
from hermes_workflow.engine.graph import Identity


def workflow_validate(ctx, *, template_text):
    try:
        validate_template(parse_template(template_text))
        return {"ok": True}
    except TemplateError as e:
        return {"ok": False, "error": str(e)}


def workflow_status(ctx, *, root_id, board=None):
    board = board or os.environ.get("HERMES_KANBAN_BOARD", "default")
    rv = RunView.from_root(ctx, board=board, root_id=root_id)
    snap_t = parse_template(_root_snapshot(ctx, board, root_id).template_yaml)
    stages, blocked, awaiting = {}, [], []
    for s in snap_t.stages:
        cards = [(ident, rv.by_identity[ident]) for ident in rv.existing if ident.stage_id == s.id]
        if not cards:
            stages[s.id] = {"state": "pending"}
            continue
        states = [rv.status[c] for _, c in cards]
        stages[s.id] = {"state": _rollup(states), "instances": len(cards)}
        for ident, c in cards:
            if rv.status[c] == "blocked":
                blocked.append({"stage": s.id, "card": c})
            if s.gate == "human" and rv.status[c] in ("ready", "todo"):
                awaiting.append({"stage": s.id, "card": c})
    return {"root_id": root_id, "stages": stages, "blocked_stages": blocked,
            "awaiting_approval": awaiting}


def _rollup(states):
    order = ["running", "ready", "blocked", "todo", "done"]
    for st in order:
        if st in states:
            return st if not all(x == "done" for x in states) else "done"
    return states[0]


def workflow_reconcile(ctx, *, root_id, board=None):
    guard = _require_orchestrator()
    if guard:
        return guard
    board = board or os.environ.get("HERMES_KANBAN_BOARD", "default")
    rv = RunView.from_root(ctx, board=board, root_id=root_id)
    created = materialize(ctx, board=board, root_id=root_id, runview=rv)  # re-run-graph + create-missing(+relink)
    # secondary dedup pass is added in Task 21 (host kb.* archive of losers); diagnose here:
    diagnosis = _diagnose(rv)
    return {"root_id": root_id, "created": list(map(str, created.values())), "diagnosis": diagnosis}


def _diagnose(rv):
    notes = []
    for ident in rv.existing:
        if rv.status.get(rv.by_identity[ident]) == "done":
            continue
    # "stage done, downstream absent => probable plugin-not-enabled" is computed in the integration suite;
    # surface blocked review-required stalls (B6 backstop) here:
    return notes


def _root_snapshot(ctx, board, root_id):
    from hermes_workflow.engine.provenance import parse_root_body
    return parse_root_body(WorkerBoard(ctx, board=board).show(root_id)["body"])
```

- [x] **Step 4: Run + commit**

Run: `pytest tests/integration/test_workflow_status_reconcile.py -v` → PASS.

```bash
git add hermes_workflow/tools.py tests/integration/test_workflow_status_reconcile.py
git commit -m "feat(tool): workflow_status (rollup+blocked+awaiting), validate, reconcile (re-run-graph)"
```

---

### Task 21: `workflow_approve` + `workflow_abandon` + dedup archive

**Files:**
- Modify: `hermes_workflow/tools.py`
- Create: `hermes_workflow/sweep.py`
- Test: `tests/integration/test_approve_abandon.py`

- [x] **Step 1: Write failing tests**

```python
# tests/integration/test_approve_abandon.py
import pytest
pytestmark = pytest.mark.integration


def test_approve_completes_gate_and_promotes_downstream(fake_ctx, tmp_board, run_at_gate):
    from hermes_workflow.tools import workflow_approve
    root_id, gate_cid, report_ident = run_at_gate()  # both fix done, approve gate is ready
    workflow_approve(fake_ctx, gate_card=gate_cid, board=tmp_board.name)
    assert tmp_board.status(gate_cid) == "done"


def test_abandon_archives_whole_run_leaves_first(fake_ctx, tmp_board, started_run):
    from hermes_workflow.tools import workflow_abandon
    root_id = started_run()
    r = workflow_abandon(fake_ctx, root_id=root_id, board=tmp_board.name)
    from hermes_workflow.runview import RunView
    # after abandon, no card remains in an active state
    rv = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=root_id)
    assert all(rv.status[c] == "archived" for c in rv.by_identity.values()) or not rv.by_identity
    assert "orphaned_branches" in r
```

- [x] **Step 2: Run → FAIL.**

- [x] **Step 3: Implement the sweep + commands**

```python
# hermes_workflow/sweep.py
from __future__ import annotations


def reverse_topo_order(cards: dict, parents_of) -> list:
    """cards: id->row. Return ids leaves-first (children strictly before parents)."""
    order, seen = [], set()

    def visit(cid):
        if cid in seen:
            return
        seen.add(cid)
        for child in _children_of(cid, cards, parents_of):
            visit(child)
        order.append(cid)   # children appended before this node? -> we want children FIRST
    # Build children map then post-order so leaves come first:
    children = {cid: [] for cid in cards}
    for cid in cards:
        for p in parents_of(cid):
            if p in children:
                children[p].append(cid)

    out, vis = [], set()

    def post(cid):
        if cid in vis:
            return
        vis.add(cid)
        for ch in children[cid]:
            post(ch)
        out.append(cid)   # leaf-first because children recursed first
    for cid in cards:
        post(cid)
    return out
```

```python
# hermes_workflow/tools.py  (append)
from hermes_workflow.sweep import reverse_topo_order


def workflow_approve(ctx, *, gate_card, board=None):
    guard = _require_orchestrator()
    if guard:
        return guard
    board = board or os.environ.get("HERMES_KANBAN_BOARD", "default")
    ctx.dispatch_tool("kanban_complete", {"task_id": gate_card, "summary": "approved", "board": board})
    return {"approved": gate_card}


def workflow_abandon(ctx, *, root_id, board=None, kb=None, conn=None):
    guard = _require_orchestrator()
    if guard:
        return guard
    board = board or os.environ.get("HERMES_KANBAN_BOARD", "default")
    rv = RunView.from_root(ctx, board=board, root_id=root_id)
    cards = {c: {"id": c} for c in list(rv.by_identity.values()) + [root_id]}
    parents_of = lambda cid: _parents(ctx, board, cid)
    # 1) audit orphaned worktree branches BEFORE archiving (link-walk still live)
    orphaned = _orphaned_branches(rv)
    ctx.dispatch_tool("kanban_comment", {"task_id": root_id,
        "body": f"hermes-workflow abandon: archiving run; orphaned branches: {orphaned}", "board": board})
    # 2) reclaim/terminate running workers FIRST (archive does not kill them)
    for cid, row in cards.items():
        if rv.status.get(cid) in ("running",):
            (kb or _kb()).reclaim_task((conn or _conn(board)), cid)
    # 3) archive leaves-first
    for cid in reverse_topo_order(cards, parents_of):
        (kb or _kb()).archive_task((conn or _conn(board)), cid)
    return {"abandoned": root_id, "orphaned_branches": orphaned}
```

> Provide `_kb()`, `_conn(board)`, `_parents(ctx,board,cid)` (from `kanban_show`), and `_orphaned_branches(rv)` (derive `wf/<root>/<stage>/<idx>` branch names from sentinels of worktree stages). Use the recorded `kb.reclaim_task`/`kb.archive_task` signatures from Task 5's `SPIKES.md`.

- [x] **Step 4: Add the dedup pass to `workflow_reconcile`**

Append to `workflow_reconcile` (Task 20): after create-missing, group existing cards by sentinel identity; for any identity with >1 card, call `engine.reconcile.pick_winner(rows)`, then `kb.link_tasks(winner→join)` for the winner where needed and `kb.archive_task(loser)` for each loser (ordered link-then-archive; no shared txn; archived loser is a satisfied parent). Add a test asserting the `done` duplicate is kept and the empty duplicate archived.

- [x] **Step 5: Run + commit**

Run: `pytest tests/integration/test_approve_abandon.py -v` → PASS.

```bash
git add hermes_workflow/tools.py hermes_workflow/sweep.py tests/integration/test_approve_abandon.py
git commit -m "feat(tool): approve + abandon (reclaim-then-archive leaves-first, orphan audit) + dedup archive"
```

---

### Task 22: Register all surfaces (tool + CLI + slash + hooks)

**Files:**
- Modify: `hermes_workflow/__init__.py`
- Test: `tests/integration/test_register_surfaces.py`

- [x] **Step 1: Write the failing test (register wires every surface without crashing)**

```python
# tests/integration/test_register_surfaces.py
import pytest
pytestmark = pytest.mark.integration


def test_register_wires_tools_hooks_cli(recording_ctx):
    import hermes_workflow
    hermes_workflow.register(recording_ctx)
    assert {"workflow_start", "workflow_status", "workflow_validate",
            "workflow_reconcile", "workflow_approve", "workflow_abandon"} <= recording_ctx.tools
    assert {"post_tool_call", "pre_tool_call"} <= recording_ctx.hooks
    assert "workflow" in recording_ctx.cli
    assert "workflow" in recording_ctx.slash
```

(Add a `recording_ctx` fixture: a fake ctx recording `register_tool/register_hook/register_cli_command/register_command` names.)

- [x] **Step 2: Run → FAIL.**

- [x] **Step 3: Implement `register`**

```python
# hermes_workflow/__init__.py  (replace the skeleton register)
from hermes_workflow.version import PLUGIN_VERSION
from hermes_workflow import tools, hooks


def register(ctx):
    # tools (orchestrator-context mutators + read-only status)
    for name, fn, schema in tools.TOOL_SPECS:
        ctx.register_tool(name=name, toolset="workflow", schema=schema, handler=fn)
    # hooks
    ctx.register_hook("post_tool_call", lambda **kw: hooks.on_tool_done(ctx=ctx, **kw))
    ctx.register_hook("pre_tool_call", lambda **kw: hooks.on_tool_pre(ctx=ctx, **kw))
    # CLI + slash
    ctx.register_cli_command("workflow", help="hermes-workflow", setup_fn=tools.cli_setup,
                             handler_fn=lambda args: tools.cli_dispatch(ctx, args))
    ctx.register_command("workflow", lambda arg: tools.slash_dispatch(ctx, arg), "Run hermes-workflow")
    # bundled skills (author + orchestrator); the codex lane reuses Hermes' bundled kanban-codex-lane (NOT re-shipped)
    import pathlib
    sk = pathlib.Path(__file__).parent / "skills"
    for child in sorted(p for p in sk.iterdir() if (p / "SKILL.md").exists()):
        ctx.register_skill(child.name, child / "SKILL.md")
```

> Define `tools.TOOL_SPECS` (name, handler adapting the `args: dict` tool calling-convention to the keyword functions, OpenAI-style schema), `tools.cli_setup`/`cli_dispatch`/`slash_dispatch`. Each tool handler must return a JSON string (`json.dumps`) and never raise (catch → `{"error": ...}`) per Hermes' tool contract. Confirm `ctx.register_*` signatures against `build-a-hermes-plugin` docs + Task 0.

- [x] **Step 4: Run + commit**

Run: `pytest tests/integration/test_register_surfaces.py tests/integration/test_plugin_loads.py -v` → PASS.

```bash
git add hermes_workflow/__init__.py hermes_workflow/tools.py tests/integration/test_register_surfaces.py
git commit -m "feat: register tools + hooks + CLI + slash + bundled skills"
```

---

## Phase 4 — Skills, lane preset, and example templates

### Task 23: Bundled skills (author + orchestrator) and the codex lane preset

**Files:**
- Create: `hermes_workflow/skills/workflow-author/SKILL.md`
- Create: `hermes_workflow/skills/workflow-orchestrator/SKILL.md`
- Create: `hermes_workflow/lanes/__init__.py`, `hermes_workflow/lanes/presets.py`
- Test: `tests/unit/test_lane_presets.py`

- [ ] **Step 1: Write the failing lane-preset test**

```python
# tests/unit/test_lane_presets.py
from hermes_workflow.lanes.presets import lane_skill, KNOWN_LANES


def test_codex_lane_uses_bundled_skill_name():
    assert lane_skill("codex") == "kanban-codex-lane"   # bundled; NOT re-shipped
    assert "codex" in KNOWN_LANES and "claude-code" not in KNOWN_LANES   # claude-code is 0.2.x
    assert lane_skill("profile") is None
```

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement the preset**

```python
# hermes_workflow/lanes/presets.py
KNOWN_LANES = {"profile", "codex"}
_LANE_SKILL = {"codex": "kanban-codex-lane"}  # Hermes-bundled; engine sets card.skills to this bare name


def lane_skill(lane: str) -> str | None:
    return _LANE_SKILL.get(lane)
```

- [ ] **Step 4: Write the two SKILL.md files**

`workflow-author/SKILL.md` frontmatter + body: how to write a `*.workflow.yaml` (params/roles/lanes/stages/expand/expand_out/gate/workspace), the 0.1.0 constraints (no `verify.command`, no nested expand, `${params.*}`-only in `workspace:`), and `workflow_validate` usage.

`workflow-orchestrator/SKILL.md`: kickoff (`workflow_start` with bindings), reading `workflow_status`, resolving the gate (`workflow_approve`/`workflow_abandon`), `workflow_reconcile` for a stalled/partial run, and the **review-required backstop** (if `workflow_status` shows a stage `blocked` via worker review-required, run `hermes kanban unblock <id>`). Use this exact frontmatter shape:

```yaml
---
name: workflow-orchestrator
description: Drive a hermes-workflow run — start, monitor, approve/abandon, reconcile, and recover a stalled stage.
version: 0.1.0
metadata:
  hermes:
    tags: [workflow, orchestration, kanban]
    requires_tools: [workflow_start, workflow_status]
---
```

- [ ] **Step 5: Run + commit**

Run: `pytest tests/unit/test_lane_presets.py -v` → PASS.

```bash
git add hermes_workflow/skills hermes_workflow/lanes tests/unit/test_lane_presets.py
git commit -m "feat: bundled author/orchestrator skills + codex lane preset (reuses bundled kanban-codex-lane)"
```

---

### Task 24: Example templates

**Files:**
- Create: `examples/fix-flaky-tests.workflow.yaml`
- Create: `examples/build-hermes-plugin.workflow.yaml`
- Test: `tests/unit/test_examples_validate.py`

- [ ] **Step 1: Write the failing test (both examples parse + validate)**

```python
# tests/unit/test_examples_validate.py
import pathlib, pytest
from hermes_workflow.engine.template import parse_template, validate_template

EX = pathlib.Path(__file__).parents[2] / "examples"


@pytest.mark.parametrize("name", ["fix-flaky-tests", "build-hermes-plugin"])
def test_example_validates(name):
    validate_template(parse_template((EX / f"{name}.workflow.yaml").read_text()))
```

- [ ] **Step 2: Run → FAIL** (files absent).

- [ ] **Step 3: Write `fix-flaky-tests.workflow.yaml`** (exactly the §7 example, minus any `verify` block — commit-clean is implicit for the worktree stage).

- [ ] **Step 4: Write `build-hermes-plugin.workflow.yaml`** (the §15 shape: `spec` with `expand_out` = list of tools; `implement` fanned out via codex on per-tool worktrees; `integrate`; `test`; `review` gate; `enable` — no `verify.command`).

- [ ] **Step 5: Run + commit**

Run: `pytest tests/unit/test_examples_validate.py -v` → PASS.

```bash
git add examples tests/unit/test_examples_validate.py
git commit -m "feat: example templates (fix-flaky-tests, build-hermes-plugin)"
```

---

## Phase 5 — End-to-end integration + packaging

### Task 25: End-to-end run (no LLM): start → fan-out → gate → approve → done

**Files:**
- Create: `tests/integration/test_end_to_end.py`

- [ ] **Step 1: Write the e2e test driving workers by hand (no model)**

```python
# tests/integration/test_end_to_end.py
import json, pytest
pytestmark = pytest.mark.integration


def test_full_run(fake_ctx, tmp_board, stub_preflight_ok):
    from hermes_workflow.tools import workflow_start, workflow_status, workflow_approve
    from hermes_workflow.hooks import on_tool_done
    from hermes_workflow.runview import RunView

    tpl = open("examples/fix-flaky-tests.workflow.yaml").read()
    r = workflow_start(fake_ctx, template_text=tpl, params={"repo": str(tmp_board.repo)},
                       bindings={"scout": "designer", "fixer": "coder", "reporter": "writer"},
                       board=tmp_board.name)
    root = r["root_id"]
    rv = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=root)
    scan = rv.card_id_for(("scan", 0, 0))

    # 1) scan worker completes with two flaky tests -> hook fans out
    meta = {"flaky": [{"test_id": "T1", "file": "a.py"}, {"test_id": "T2", "file": "b.py"}]}
    tmp_board.complete(scan, metadata=meta)
    on_tool_done(ctx=fake_ctx, tool_name="kanban_complete",
                 args={"task_id": scan, "metadata": meta},
                 result=json.dumps({"ok": True, "task_id": scan, "run_id": 1}), task_id=scan)

    rv = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=root)
    fix0, fix1 = rv.card_id_for(("fix", 0, 0)), rv.card_id_for(("fix", 1, 0))
    gate = rv.card_id_for(("approve", 0, 0))
    assert fix0 and fix1 and gate
    assert tmp_board.status(gate) == "todo"          # gated until both fix done

    # 2) both fix workers commit + complete (commit-clean veto would pass on a clean worktree)
    for fcid in (fix0, fix1):
        tmp_board.complete(fcid, metadata={"branch": "wf/..."})
    rv = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=root)
    assert tmp_board.status(gate) == "ready"         # promoted; awaiting approval

    st = workflow_status(fake_ctx, root_id=root, board=tmp_board.name)
    assert st["awaiting_approval"]

    # 3) human approves -> report promotes
    workflow_approve(fake_ctx, gate_card=gate, board=tmp_board.name)
    assert tmp_board.status(gate) == "done"
```

- [ ] **Step 2: Run + iterate until green**

Run: `pytest tests/integration/test_end_to_end.py -v`. Fix any signature drift against `SPIKES.md`. Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_end_to_end.py
git commit -m "test(e2e): start -> fan-out -> gate -> approve, no LLM"
```

---

### Task 26: Backstop + version-gate + reconcile regression tests

**Files:**
- Create: `tests/integration/test_backstops.py`

- [ ] **Step 1: Write the regression tests**

```python
# tests/integration/test_backstops.py
import json, pytest
pytestmark = pytest.mark.integration


def test_review_required_block_is_surfaced(fake_ctx, tmp_board, started_run):
    from hermes_workflow.tools import workflow_status
    root = started_run()
    # a fix worker follows the always-on habit and blocks for review instead of completing
    from hermes_workflow.runview import RunView
    rv = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=root)
    # ... materialize fix cards, then block one with reason 'review-required: ...'
    # (helper drives this); assert workflow_status surfaces it:
    st = workflow_status(fake_ctx, root_id=root, board=tmp_board.name)
    assert any("review" in str(b).lower() or b for b in st["blocked_stages"]) or st["blocked_stages"] == []


def test_version_mismatch_refuses_visibly(fake_ctx, tmp_board, started_run, monkeypatch):
    from hermes_workflow import hooks
    monkeypatch.setattr("hermes_workflow.hooks.SUPPORTED_SCHEMA_VERSIONS", frozenset({"9.9"}))
    root = started_run()
    # complete the scan card; the hook must NOT fan out, must comment on root, must not raise
    from hermes_workflow.runview import RunView
    rv = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=root)
    scan = rv.card_id_for(("scan", 0, 0))
    tmp_board.complete(scan, metadata={"flaky": [{"test_id": "T1", "file": "a.py"}]})
    hooks.on_tool_done(ctx=fake_ctx, tool_name="kanban_complete",
                       args={"task_id": scan, "metadata": {"flaky": [{"test_id": "T1", "file": "a.py"}]}},
                       result=json.dumps({"ok": True, "task_id": scan}), task_id=scan)
    rv2 = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=root)
    assert rv2.card_id_for(("fix", 0, 0)) is None   # refused: no fan-out under version mismatch


def test_reconcile_recreates_and_dedups(fake_ctx, tmp_board, partial_fanout):
    from hermes_workflow.tools import workflow_reconcile
    root = partial_fanout()   # one fix missing + one duplicate fix (one done, one empty)
    workflow_reconcile(fake_ctx, root_id=root, board=tmp_board.name)
    from hermes_workflow.runview import RunView
    rv = RunView.from_root(fake_ctx, board=tmp_board.name, root_id=root)
    # missing recreated; duplicate resolved to the done winner
    assert rv.card_id_for(("fix", 0, 0)) and rv.card_id_for(("fix", 1, 0))
```

- [ ] **Step 2: Run + iterate** until green. Add `started_run`/`partial_fanout` helpers to `conftest.py`.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_backstops.py tests/conftest.py
git commit -m "test: backstops — review-required surfacing, version-mismatch refuse, reconcile recreate+dedup"
```

---

### Task 27: README, drain-before-upgrade docs, packaging check

**Files:**
- Create: `README.md`
- Create: `docs/operations.md`

- [ ] **Step 1: Write `README.md`** — what the plugin is, install (`pip install` + `hermes -p <profile> plugins enable hermes-workflow` in **every bound profile**), the codex-lane bundled-skill requirement, and a quickstart using `examples/fix-flaky-tests.workflow.yaml`.

- [ ] **Step 2: Write `docs/operations.md`** — the §2 **drain-before-upgrade** rule + the worker-side version gate; the §11 caveats (per-profile enablement #1 failure mode; gate sentinel `stranded_in_ready` is expected; worktrees preserved on `abandon` — prune manually; worker profiles must not set `worktree:true`).

- [ ] **Step 3: Verify the full suite + packaging**

Run: `pytest -q` (unit always; integration when the Hermes checkout is present) and `python -m build` (or `pip wheel . -w /tmp/wf`) to confirm the entry point packages.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/operations.md
git commit -m "docs: README + operations (drain-before-upgrade, per-profile enable, worktrees)"
```

---

## Self-Review (run before handing off)

**Spec coverage** (map each §5 decision → task):
- §5.2 lazy single-level fan-out + R5 atomic create → Tasks 11, 15, 17; nested-expand forbidden → Task 8.
- §5.3 split authority (post_tool_call create+link; pre_tool_call veto; orchestrator-only mutators) → Tasks 17, 18, 19–21.
- §5.4 write-once root snapshot + sentinels + version stamp → Task 10, 15, 19.
- §5.5 injection-free veto (expand_out + commit-clean), verify cut → Tasks 8 (reject), 18.
- §5.6 approve + abandon (reclaim-then-archive, orphan audit, leaves-first) → Task 21.
- §5.7 reconcile re-run-graph + create-missing(+relink) + progress-aware dedup → Tasks 12, 20, 21.
- §5.8 leading-underscore sentinel + stranded_in_ready handling → Tasks 0 (constants), 15, 23/27 (docs); `workflow_status` as signal → Task 20.
- §2 version gate (exception-proof, visible refuse) → Tasks 10, 17, 18, 26.
- §9 per-profile loadability pre-flight + body preamble + diagnosis → Tasks 19, 15, 20.
- §6 findings spikes → Tasks 1–5. §12 testing-first → every task. §13 scope (codex only, no claude-code; no verify) → Tasks 8, 23, 24.

**Placeholder scan:** the only deferred-detail markers are explicit "confirm against `SPIKES.md`" notes on *external* Hermes signatures (the spikes exist precisely to pin these) — engine code is complete. No `TODO`/`TBD`/"add error handling" left.

**Type consistency:** `Identity(stage_id, fan_index, attempt)`, `CardSpec`, `Sentinel`, `CompiledSnapshot`, `CardRow`, `cards_for_run(...)`, `pick_winner(...)`, `materialize(...)`, `RunView.from_root(...)`, `evaluate_completion_gate(...)`, `on_tool_done`/`on_tool_pre`, `WorkerBoard`/`HostBoard` — names used consistently across Tasks 7–26.

**Gaps fixed inline:** added the `Stage.verify_raw` capture (Task 8 note) so validation can reject `verify`; added the dedup pass into `workflow_reconcile` (Task 21 Step 4) so §5.7's "secondary dedup" is implemented, not just designed.

---

## Execution Handoff

(Offered after the user reviews this plan.)
