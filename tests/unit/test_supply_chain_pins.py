"""Meta-test: every declared dependency is upper-bounded and every GitHub Action
is SHA-pinned — the plugin's supply-chain pinning invariant, enforced in CI.

This bounds the dependency-pinning policy in CONTRIBUTING.md: a regression that
adds an unbounded `>=` spec or a tag-pinned action fails the unit suite. It is
repo-rooted (reads pyproject.toml + .github/ from the source tree), so it runs in
CI and from a checkout, not against an installed wheel.
"""
import pathlib
import re
import tomllib

import yaml

_REPO = pathlib.Path(__file__).resolve().parents[2]
_PYPROJECT = _REPO / "pyproject.toml"
_WORKFLOWS = _REPO / ".github" / "workflows"

_SHA_PINNED = re.compile(r"@[0-9a-f]{40}$")


def _is_bounded(spec):
    # Upper-bounded: a `<` ceiling, or an `==exact` pin (the CI-only treatment).
    return "<" in spec or "==" in spec


def _all_requirements():
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    reqs = list(data.get("build-system", {}).get("requires", []))
    proj = data.get("project", {})
    reqs += list(proj.get("dependencies", []))
    for extra in proj.get("optional-dependencies", {}).values():
        reqs += list(extra)
    return reqs


def test_every_dependency_is_upper_bounded():
    unbounded = [r for r in _all_requirements() if not _is_bounded(r)]
    assert not unbounded, f"unbounded dependency specs (need a <ceiling): {unbounded}"


def _iter_uses(node):
    """Yield every `uses:` value in a parsed workflow YAML tree."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "uses" and isinstance(value, str):
                yield value
            else:
                yield from _iter_uses(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_uses(item)


def test_every_github_action_is_sha_pinned():
    offenders = []
    for wf in sorted(_WORKFLOWS.glob("*.yml")):
        tree = yaml.safe_load(wf.read_text(encoding="utf-8"))
        for uses in _iter_uses(tree):
            if uses.startswith("./") or uses.startswith("docker://"):
                continue  # local / docker actions are not SHA-pinnable refs
            if not _SHA_PINNED.search(uses):
                offenders.append(f"{wf.name}: {uses}")
    assert not offenders, f"GitHub Actions not pinned to a 40-char commit SHA: {offenders}"
