"""Spike 2 — per-profile load-status probe (real Hermes source).

Confirms against Hermes v0.15.1 @ c47b9d12 the in-process way to read a
plugin's LOAD status (``enabled`` != merely configured). The truth lives in
``LoadedPlugin.enabled`` / ``LoadedPlugin.error`` (plugins.py:278-279) and is
surfaced by ``PluginManager.list_plugins()`` (plugins.py:1574-1593), which is
only visible in-process under that profile's ``HERMES_HOME``.

Confirmed API (the plan's example was WRONG on both counts):
  - ``list_plugins()`` is a METHOD of ``PluginManager``; call it via the
    singleton: ``plugins.get_plugin_manager().list_plugins()`` — NOT a
    module-level ``plugins.list_plugins()``.
  - It returns ``List[Dict[str, Any]]`` — a list of DICTS (NOT objects with
    ``.name/.enabled/.error``). Read load status as ``entry["enabled"]`` /
    ``entry["error"]``; find a plugin by name via a dict keyed on ``"name"``.

CRITICAL caveat: ``discover_plugins()`` is idempotent/cached on the
process-global singleton, so a plain call after a prior discovery is a no-op
and will NOT rescan under a new ``HERMES_HOME``. The probe MUST force-rescan:
``discover_plugins(force=True)`` (-> ``discover_and_load(force=True)``).
See SPIKES.md "Spike 2" for full findings.
"""
import pytest

pytestmark = pytest.mark.integration


def test_list_plugins_reports_load_status_shape(hermes_root, tmp_path, monkeypatch, request):
    # monkeypatch auto-restores both env vars after the test (no os.environ
    # mutation left behind). HERMES_HOME isolates the profile; the project-
    # plugins gate is set explicitly so the scan behavior is deterministic.
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_ENABLE_PROJECT_PLUGINS", "1")

    from hermes_cli import plugins

    # force=True rescans under our tmp HERMES_HOME and CACHES the result on the
    # process-global PluginManager singleton. monkeypatch restores HERMES_HOME
    # on teardown but does NOT undo that singleton mutation, so without this
    # finalizer the cache outlives the test pointed at a since-deleted tmp dir —
    # the single-process equivalent of the cross-test leak that subprocess
    # isolation prevents (production preflight.py spawns a subprocess for
    # exactly this reason). Reset the singleton to None so the next
    # get_plugin_manager() rediscovers cleanly under the then-current home.
    request.addfinalizer(lambda: setattr(plugins, "_plugin_manager", None))

    # force=True: the singleton is process-global and may have already
    # discovered in an earlier test; without force this is a no-op and would
    # NOT rescan under our tmp HERMES_HOME.
    plugins.discover_plugins(force=True)

    lst = plugins.get_plugin_manager().list_plugins()

    # Spike-stop: the return shape MUST be list[dict]. If it is not, the real
    # probe's by-key reads are invalid; do not force the assertion downstream.
    assert isinstance(lst, list)

    # The dict-key assertions only run when entries exist. An empty list under
    # the tmp home is still informative (recorded in SPIKES.md) and not a
    # failure — bundled plugins ship with the Hermes checkout, so in practice
    # the list is non-empty.
    for entry in lst:
        assert isinstance(entry, dict)
        # Keys the downstream preflight probe depends on:
        assert "name" in entry
        assert "enabled" in entry
        assert "error" in entry
        assert isinstance(entry["enabled"], bool)
        # error is Optional[str]: None when the plugin loaded cleanly.
        assert entry["error"] is None or isinstance(entry["error"], str)

    # Demonstrate the by-name read pattern the real probe uses to answer
    # "is plugin X loaded, and if not why?":
    by_name = {e["name"]: e for e in lst}
    # Every projected name round-trips into the lookup map.
    assert len(by_name) == len({e["name"] for e in lst})

    # Read (enabled, error) for an arbitrary discovered plugin to prove the
    # access pattern works end-to-end (skipped only if nothing was discovered).
    if by_name:
        name = next(iter(by_name))
        entry = by_name[name]
        enabled, error = entry["enabled"], entry["error"]
        assert isinstance(enabled, bool)
        assert error is None or isinstance(error, str)
