# hermes-workflow — Test-Convention Audit (Tier 3)

- **Date:** 2026-06-04
- **Target:** the whole `tests/` tree (32 files, 137 passing: 65 unit + 72
  integration) at branch `test/convention-audit` off `v0.1.2` (`7052028`).
- **Standard:** Hermes Agent's own testing conventions
  (`hermes-agent/AGENTS.md` "Testing"): **(1)** don't write change-detector
  tests, **(2)** subprocess-per-test isolation / no un-restored process-global
  state, **(3)** no LLM in any test, no writes to a real `~/.hermes`.
- **Method:** 8-agent workflow — 6 partitioned auditors (engine-unit,
  prov/veto-unit, pure-root+conftest, integration-tools, integration-hooks,
  integration-spikes+load) each reading its files in full, then **adversarial
  verification** of every finding (re-read the cited code, default to
  false-positive unless a standard is clearly violated). Only `confirmed`
  findings are actioned.
- **Coverage constraint:** no change may weaken coverage; **137 tests must
  still pass.** They do (verified post-fix with `HERMES_AGENT_ROOT` set).

---

## 1) Verdict

**PASS, with one low-severity fix applied.** The suite is genuinely
behavior-focused. Across 32 files the audit produced **2 candidate findings**;
adversarial verification **confirmed 1** (low) and **dismissed 1** as a
false positive. The confirmed finding was cheap and is fixed in this branch.

What the audit specifically did **not** find (the clean bill of health that
"documents the rest"):

- **No change-detector tests.** The exact-value assertions that look like
  snapshots are all behavioral contracts: parser reads of fixture-set fields
  (`expand_out.max == 50` where the template under test declares `max: 50`),
  deterministic logic results (`fan_index == [0, 1]`, dedup → 1 card, a join
  has 1 instance), and gate/version-compat logic pinned against a fixed
  `supported` set. None reproduces a value that is *expected to change*
  (release versions are imported from `version.py`, never hardcoded as an
  assertion target).
- **No LLM in any test** — confirmed across all 32 files (the design invariant
  holds in practice).
- **No real-home writes** — `HERMES_HOME` is always redirected to `tmp_path`
  via `monkeypatch`; example paths are repo-relative via `Path(__file__)`.
- **`conftest.py` fixture hygiene is correct.** `register_pre_hook` removes
  **exactly** the callbacks it appended from the process-global
  `pre_tool_call` hook list (the documented leak hazard in
  `AGENTS.md#testing`), and `monkeypatch` is used throughout for env/attr
  mutation (auto-restored), rather than raw `setattr`.

## 2) Confirmed finding (fixed)

| ID | Severity | Standard | Location |
|----|----------|----------|----------|
| **IN-01** | LOW | state-leak / isolation | `tests/integration/test_spike_preflight.py:28-42` |

**What.** `test_list_plugins_reports_load_status_shape` sets `HERMES_HOME` to
`tmp_path` (auto-restored) and then calls `plugins.discover_plugins(force=True)`,
which **caches the discovered plugin set on the process-global
`PluginManager` singleton** (`hermes_cli.plugins._plugin_manager`). `monkeypatch`
restores the env var on teardown but does **not** undo the singleton mutation,
so the cache outlives the test pointed at a since-deleted `tmp_path`. Because
the plugin runs its whole suite in **one process** (no subprocess-per-test
isolation), this is precisely the un-restored cross-test process-global
mutation that isolation would otherwise mask.

**Why it's LOW, not higher.** It is a **latent** leak, not an active failure:
the only other singleton consumer in the suite (`register_pre_hook`) touches
the independent `_hooks` dict and cleans up exactly, and **no later test
re-reads the discovered-plugins cache.** So nothing currently breaks. (The
production code already treats this state as process-poisoning:
`preflight.py` spawns a **fresh subprocess per profile** specifically because
`discover_plugins(force=True)` would leave the singleton pointed at that
profile's home — see `SPIKES.md` "Spike 2".)

**Fix applied.** Register a finalizer that resets the singleton so the next
`get_plugin_manager()` rediscovers cleanly under the then-current home:

```python
request.addfinalizer(lambda: setattr(plugins, "_plugin_manager", None))
```

Resetting to `None` (rather than re-running `discover_plugins`) is the correct
choice: `monkeypatch` restores `HERMES_HOME` only at fixture teardown, so a
re-discovery from inside the test would just re-cache against `tmp_path` again;
nulling the singleton is the in-process equivalent of the subprocess boundary
production relies on. All assertions are unchanged — **zero coverage impact**;
the full suite still reports **137 passed**.

## 3) Dismissed (false positive, documented)

| ID | Location | Why dismissed |
|----|----------|---------------|
| **PR-01** | `tests/unit/test_examples_validate.py:8-10` | The hardcoded `parametrize` list `["fix-flaky-tests", "build-hermes-plugin"]` is **not** a change-detector: it asserts no count/snapshot, its per-iteration body runs a real contract (`validate_template(parse_template(...))` must succeed on a shipped example), and **adding** a new example does not break it. The only failure mode is renaming/removing a referenced example — a legitimate signal, not a spurious break. The reframed concern (a *new* example could escape validation) is a **coverage gap**, i.e. under-testing, which is the opposite of the over-asserting pattern the standard targets. |

**Optional future enhancement (NOT a fix, deliberately deferred).** If you want
new examples auto-covered, replace the literal list with a glob over
`examples/*.workflow.yaml`. This *adds* coverage; it does not remediate any
standard violation, and the "do not weaken coverage" constraint plus
surgical-change discipline argue for leaving it to a dedicated change rather
than bundling it into this audit. Tracked here so it isn't lost.

## 4) Method note

The 6 auditors covered all 32 files; the 2 false-positive-prone findings were
each re-derived from source by an independent verifier (e.g. IN-01 was
empirically reproduced against the real `hermes_cli/plugins.py` — singleton
identity preserved, `_discovered` still `True`, cache bound to a deleted dir —
before being confirmed). The clean result is therefore a *checked* clean
result, not an absence of looking.
