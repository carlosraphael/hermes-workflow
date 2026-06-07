"""Drift-guard: the package version is single-sourced from
``hermes_workflow.version.PLUGIN_VERSION``.

``pyproject.toml`` declares the version *dynamically* (``dynamic = ["version"]``
plus a ``[tool.setuptools.dynamic]`` ``attr`` pointing at ``PLUGIN_VERSION``), so
the packaged version and the runtime/provenance version cannot drift. This test
fails the unit suite if the build config is ever reverted to a *static*
``project.version`` that disagrees with ``PLUGIN_VERSION`` — catching the
mis-stamped-provenance regression that motivated single-sourcing.

It asserts a *relationship* (agreement / wiring), never a version snapshot, so a
routine version bump does not break it — consistent with the repo's
"don't write change-detector tests" rule (AGENTS.md).
"""
import pathlib
import tomllib

from hermes_workflow.version import PLUGIN_VERSION

_REPO = pathlib.Path(__file__).resolve().parents[2]
_PYPROJECT = _REPO / "pyproject.toml"

# The attr setuptools must resolve the dynamic version from.
_VERSION_ATTR = "hermes_workflow.version.PLUGIN_VERSION"


def _pyproject():
    return tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))


def test_pyproject_version_is_single_sourced():
    data = _pyproject()
    project = data["project"]

    if "version" in project.get("dynamic", []):
        # Intended state: the version is derived from PLUGIN_VERSION, not copied.
        assert "version" not in project, (
            "`version` cannot be both declared dynamic and pinned as a static "
            "[project] key — setuptools rejects this."
        )
        attr = (
            data.get("tool", {})
            .get("setuptools", {})
            .get("dynamic", {})
            .get("version", {})
            .get("attr")
        )
        assert attr == _VERSION_ATTR, (
            f"dynamic version must resolve from {_VERSION_ATTR!r}, got {attr!r}"
        )
    else:
        # Fallback guard: if a static version is ever reintroduced it MUST agree
        # with PLUGIN_VERSION — drift here silently mis-stamps run provenance.
        assert project.get("version") == PLUGIN_VERSION, (
            f"static pyproject version {project.get('version')!r} disagrees with "
            f"PLUGIN_VERSION {PLUGIN_VERSION!r}"
        )
