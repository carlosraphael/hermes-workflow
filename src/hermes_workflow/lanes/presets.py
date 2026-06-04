# src/hermes_workflow/lanes/presets.py
"""Lane contract — the single source of truth for which bundled skill a lane requests.

A *lane* is the execution shape bound to an abstract role:

- ``profile``     — a plain LLM worker on the bound profile (no extra skill).
- ``codex``       — an LLM worker that drives the ``codex`` binary as a subprocess,
                    requesting the Hermes-BUNDLED ``kanban-codex-lane`` skill (this
                    plugin does NOT re-ship it; the engine sets ``card.skills`` to
                    this bare name and Hermes resolves it at dispatch).
- ``claude-code`` — deferred to 0.2.x; intentionally ABSENT from ``KNOWN_LANES``.
"""

KNOWN_LANES = {"profile", "codex"}
_LANE_SKILL = {"codex": "kanban-codex-lane"}  # Hermes-bundled; engine sets card.skills to this bare name


def lane_skill(lane: str) -> str | None:
    return _LANE_SKILL.get(lane)
