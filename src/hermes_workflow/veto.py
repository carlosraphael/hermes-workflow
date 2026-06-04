# src/hermes_workflow/veto.py
"""The PURE, TOTAL completion-gate logic for the ``pre_tool_call`` veto.

This is the plugin's ONLY blocking channel (Spike 1): a ``pre_tool_call`` hook
that RAISES fails OPEN (the host swallows the exception and allows the tool),
so the veto must NEVER raise. It vetoes by RETURNING a block dict and fails
CLOSED — on ANY internal error it returns a block dict, never ``None``/raise.

``evaluate_completion_gate`` is kept pure (no board, no ctx): it takes the
already-resolved gate inputs and returns ``{"action": "block", "message": ...}``
or ``None``. The whole body is one ``try/except`` so an unexpected input shape
produces a block, not an exception.
"""
import subprocess

# Defensive fallback only: in production ``_stage_gate_inputs`` always supplies
# ``max`` from the already-defaulted ``ExpandOut.max`` (engine model.py), so this
# mirrors that engine default and is reached only by direct (unit-test) callers.
_DEFAULT_MAX = 50          # expand_out item cap when the caller omits ``max``
_GIT_TIMEOUT_S = 30        # the veto's own self-timeout hygiene for the git probe


def _block(msg: str) -> dict:
    return {"action": "block", "message": f"hermes-workflow: {msg}"}


def evaluate_completion_gate(*, stage_kind, expand_out, metadata, workspace_dir, schema_ok) -> dict | None:
    """Return a block dict, or ``None`` to allow. NEVER raises (fails CLOSED)."""
    try:
        if not schema_ok:
            return _block("plugin schema_version is incompatible with this run; completion refused")

        if stage_kind == "expand_source" and expand_out:
            gate = _check_expand_out(expand_out, metadata)
            if gate is not None:
                return gate

        if stage_kind == "worktree" and workspace_dir:
            gate = _check_commit_clean(workspace_dir)
            if gate is not None:
                return gate

        return None
    except Exception as e:
        return _block(f"completion gate internal error (failing closed): {e!r}")


def _check_expand_out(expand_out, metadata) -> dict | None:
    """The sole pre-fan-out DATA gate. TOTAL: any malformed input -> block."""
    key = expand_out["key"]
    items = (metadata or {}).get(key)
    if not isinstance(items, list):
        return _block(f"expand_out.{key} must be a list")

    max_items = int(expand_out.get("max", _DEFAULT_MAX))
    if len(items) > max_items:
        return _block(f"expand_out.{key} exceeds max {max_items}")

    fields = expand_out.get("item", {})
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            return _block(f"expand_out item {i} must be an object")
        for field in fields:
            if field not in item:
                return _block(f"expand_out item {i} missing field '{field}'")
    return None


def _check_commit_clean(workspace_dir) -> dict | None:
    """Commit-clean check on an engine-provisioned worktree.

    The git command uses a FIXED form (``git -C <dir> status --porcelain``) with
    NO untrusted interpolation: ``workspace_dir`` is the engine-provisioned path
    recorded on the card, not user data.
    """
    r = subprocess.run(
        ["git", "-C", workspace_dir, "status", "--porcelain"],
        capture_output=True, text=True, timeout=_GIT_TIMEOUT_S,
    )
    if r.returncode != 0:
        detail = r.stderr.strip().splitlines()[0] if r.stderr.strip() else "non-zero git exit"
        return _block(f"commit-clean check failed: not a git worktree ({detail})")
    if r.stdout.strip():
        return _block("commit-clean check failed: uncommitted changes — commit before completing")
    return None
