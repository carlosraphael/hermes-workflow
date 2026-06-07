# src/hermes_workflow/worktree.py
"""Worktree pre-provisioning (pure — no Hermes imports; shells out to ``git``).

Worktree isolation is engine-pre-provisioned (deterministic), idempotent
(reuse-if-exists; survives hook-refire/reconcile), base-ref pinned, and
provision-then-create per child. Each child gets its own git worktree on a
fixed, engine-derived branch so workers never share a working tree.

Consumed by the Task 15 materializer, which turns a ``worktree:<repo>``
workspace spec into a provisioned ``dir:<provisioned-path>`` card; the same
branch format is reused by ``_orphaned_branches`` to audit teardown (abandon).

``ident`` is an ``engine.graph.Identity`` (``.stage_id``/``.fan_index``/
``.attempt``); it is duck-typed rather than imported to keep this module
free of any Hermes/engine import (it stays pure stdlib).
"""
from __future__ import annotations

import hashlib
import pathlib
import subprocess

_WORKTREES_DIRNAME = ".hermes-workflow-worktrees"
_TAG_LEN = 12               # chars of sha1 used to disambiguate worktree dirs
_INDEX_LOCK_RETRIES = 3     # brief retries on `git index.lock` contention
_INDEX_LOCK_MARKER = "index.lock"
_ALREADY_EXISTS_MARKER = "already exists"


def worktree_path(root_id: str, ident, repo: str) -> pathlib.Path:
    """Deterministic worktree path for a child. Pure: no filesystem side effects.

    The path is a sibling of the resolved repo so worktrees never nest inside it.
    """
    parent = pathlib.Path(repo).resolve().parent
    tag = hashlib.sha1(
        f"{root_id}:{ident.stage_id}:{ident.fan_index}:{ident.attempt}".encode()
    ).hexdigest()[:_TAG_LEN]
    name = f"{root_id}-{ident.stage_id}-{ident.fan_index}-{tag}"
    return parent / _WORKTREES_DIRNAME / name


def provision_worktree(root_id: str, ident, repo: str, base_ref: str | None = None) -> str:
    """Provision (idempotently) a base-pinned git worktree for a child; return its path.

    Reuse-if-exists, so this survives hook-refire/reconcile. Retries only on
    ``git index.lock`` contention; treats an "already exists" race as success;
    re-raises any other git failure (so the materializer won't create a card
    pointing at a missing worktree).
    """
    path = worktree_path(root_id, ident, repo)
    if (path / ".git").exists():
        return str(path)  # reuse-if-exists; do NOT recreate

    path.parent.mkdir(parents=True, exist_ok=True)
    branch = f"wf/{root_id}/{ident.stage_id}/{ident.fan_index}"  # engine-derived, no untrusted interpolation
    base = base_ref or "HEAD"
    args = ["git", "-C", repo, "worktree", "add", "-b", branch, str(path), base]

    for attempt in range(_INDEX_LOCK_RETRIES):
        try:
            _run(args)
            return str(path)
        except subprocess.CalledProcessError as err:
            stderr = err.stderr or ""
            if _ALREADY_EXISTS_MARKER in stderr:
                return str(path)  # branch/path race -> already provisioned
            if _INDEX_LOCK_MARKER in stderr and attempt < _INDEX_LOCK_RETRIES - 1:
                continue          # brief retry on index.lock contention
            raise                 # genuine failure -> reconcile handles it
    # unreachable: the final attempt always returns or raises inside the loop.


def _orphaned_branches(t, rv, root_id):
    """Engine-derived worktree branch names for a run's worktree-stage cards.

    Matches ``provision_worktree``'s format ``wf/<root>/<stage>/<fan_index>``; used
    by ``workflow_abandon`` to audit branches left behind after teardown. Pure and
    duck-typed (``t`` Template, ``rv`` RunView) — no Hermes/engine import.
    """
    stages = {s.id: s for s in t.stages}
    out = []
    for ident in rv.existing:
        s = stages.get(ident.stage_id)
        if s and s.workspace.startswith("worktree:"):
            out.append(f"wf/{root_id}/{ident.stage_id}/{ident.fan_index}")
    return sorted(out)


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, check=True, capture_output=True, text=True)
