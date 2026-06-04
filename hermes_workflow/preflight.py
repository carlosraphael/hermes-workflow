# hermes_workflow/preflight.py
"""Per-profile pre-flight loadability probe.

Before a run is seeded, we must KNOW that ``hermes-workflow`` is actually
loadable under every profile a binding points at (and, for codex-lane roles,
that the codex binary + bundled lane skill are present). The plugin's load
truth lives in a process-global PluginManager singleton, so we CANNOT inspect a
foreign profile in-process: ``discover_plugins(force=True)`` would leave the
singleton pointed at that profile's home for the rest of the process (Spike 2).

So we spawn ONE fresh subprocess per distinct profile, each under that
profile's ``HERMES_HOME``, and read the load truth there. ``_probe_once`` is the
subprocess body; ``_evaluate_probe`` is the pure decision over its emitted dict;
``probe_profiles`` is the orchestrator-side fan-out that returns a per-profile
verdict. The decision and the I/O are split so the decision stays unit-testable.
"""
PLUGIN_NAME = "hermes-workflow"
_PROBE_TIMEOUT_S = 60


def _probe_once() -> dict:
    """Runs INSIDE the spawned subprocess under the target HERMES_HOME.

    Force-rescan, read this plugin's load truth, plus codex-lane readiness.
    """
    import shutil

    from hermes_cli import plugins

    plugins.discover_plugins(force=True)
    by_name = {e["name"]: e for e in plugins.get_plugin_manager().list_plugins()}
    entry = by_name.get(PLUGIN_NAME)
    return {
        "enabled": bool(entry["enabled"]) if entry else False,
        "error": (entry["error"] if entry else "not-discovered"),
        "codex_bin": shutil.which("codex") is not None,
        "lane_skill": _lane_skill_present(),
    }


def _lane_skill_present() -> bool:
    """True if the bundled ``kanban-codex-lane/SKILL.md`` is reachable.

    Checks the profile's skills dir AND the Hermes package's bundled skills
    tree (the lane skill ships inside the Hermes package).
    """
    import pathlib

    import hermes_cli
    from tools.skills_tool import SKILLS_DIR

    roots = [
        SKILLS_DIR,
        pathlib.Path(hermes_cli.__file__).resolve().parent.parent / "skills",
    ]
    return any(
        r.is_dir() and any(r.rglob("kanban-codex-lane/SKILL.md")) for r in roots
    )


def _evaluate_probe(info: dict, is_codex: bool) -> dict:
    """Pure decision over a probe-emitted info dict -> {"ok": bool, "error": str|None}."""
    if not info.get("enabled") or info.get("error"):
        return {"ok": False, "error": info.get("error") or "plugin not enabled"}
    if is_codex:
        if not info.get("codex_bin"):
            return {"ok": False, "error": "codex binary not found on PATH"}
        if not info.get("lane_skill"):
            return {"ok": False, "error": "bundled kanban-codex-lane skill not found"}
    return {"ok": True, "error": None}


def probe_profiles(profiles, *, codex_profiles=frozenset(), project_plugin=False) -> dict:
    """Spawn ONE probe subprocess per DISTINCT profile under its HERMES_HOME.

    Returns ``{profile: {"ok": bool, "error": str|None}}``. The ``PYTHONPATH``
    propagation is what lets the spawned process import ``hermes_cli``/``tools``
    in a sys.path-injected (not pip-installed) test environment; it is harmless
    in a real deployment where Hermes is importable anyway.
    """
    import json
    import os
    import subprocess
    import sys

    from hermes_cli.profiles import resolve_profile_env

    out = {}
    for prof in sorted(profiles):
        try:
            home = resolve_profile_env(prof)
        except (FileNotFoundError, ValueError) as e:
            out[prof] = {"ok": False, "error": f"profile invalid: {e}"}
            continue
        env = {
            **os.environ,
            "HERMES_HOME": home,
            "PYTHONPATH": os.pathsep.join(p for p in sys.path if p),
        }
        if project_plugin:
            env["HERMES_ENABLE_PROJECT_PLUGINS"] = "1"
        try:
            r = subprocess.run(
                [sys.executable, "-m", "hermes_workflow.preflight"],
                capture_output=True, text=True, env=env,
                timeout=_PROBE_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            out[prof] = {"ok": False, "error": "probe timed out"}
            continue
        try:
            info = json.loads(r.stdout.strip().splitlines()[-1])
        except Exception:
            out[prof] = {"ok": False, "error": f"probe failed: {r.stderr[-300:]}"}
            continue
        out[prof] = _evaluate_probe(info, prof in codex_profiles)
    return out


if __name__ == "__main__":
    import json

    print(json.dumps(_probe_once()))
