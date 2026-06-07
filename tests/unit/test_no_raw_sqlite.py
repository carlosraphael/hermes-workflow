"""Meta-test pinning the 'no raw SQLite anywhere in hermes_workflow/' invariant.

Every DB access in the plugin must go through ctx.dispatch_tool / WorkerBoard or
the host-side kb.* / HostBoard helpers — NEVER a direct sqlite handle or a raw
cursor. The only sanctioned connection opener is ``kb.connect_closing(...)``
inside ``hermes_workflow/reconcile_exec.py::_host_board``. This test walks every module
under hermes_workflow/ and fails (naming file + line) on any violation, so a
future regression that smuggles in raw SQLite is caught.
"""
import pathlib

import hermes_workflow

# Resolve the package dir from the imported module so this meta-test follows the
# package regardless of repo layout (src-layout, flat, or eventual in-tree).
_PKG = pathlib.Path(hermes_workflow.__file__).resolve().parent

# Forbidden substrings. ``connect_closing`` is explicitly allowed (sanctioned
# host-board opener); a BARE ``.connect(`` is forbidden, so we detect raw connects
# by stripping the allowed token first.
_FORBIDDEN = (
    "import sqlite3",
    "from sqlite3",
    "sqlite3.connect",
    ".execute(",
    ".executemany(",
    ".executescript(",
)
_ALLOWED_CONNECT = "connect_closing"
_RAW_CONNECT = ".connect("


def _violations_in(text):
    """Yield (lineno, line, reason) for every forbidden pattern in a file's text.

    Caveat: this is a substring scan over raw source lines, not an AST walk — a
    comment or string literal that happens to contain ``.execute(`` (or another
    forbidden token) will also trip it. That's intentionally strict for a
    safety invariant; if a future line legitimately needs such text, rephrase it.
    """
    for i, line in enumerate(text.splitlines(), start=1):
        for needle in _FORBIDDEN:
            if needle in line:
                yield i, line.strip(), needle
        # Raw connect: allow connect_closing, forbid a bare .connect(
        if _RAW_CONNECT in line.replace(_ALLOWED_CONNECT, ""):
            yield i, line.strip(), _RAW_CONNECT


def test_no_raw_sqlite_in_hermes_workflow():
    assert _PKG.is_dir(), f"package dir not found: {_PKG}"

    offenders = []
    for path in sorted(_PKG.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for lineno, line, reason in _violations_in(text):
            offenders.append(f"{path}:{lineno}: {reason!r} in: {line}")

    assert not offenders, (
        "raw SQLite / raw cursor / bare .connect( found in hermes_workflow/ "
        "(all DB access must go via ctx.dispatch_tool/WorkerBoard or kb.*/HostBoard; "
        "only connect_closing in reconcile_exec.py::_host_board is sanctioned):\n"
        + "\n".join(offenders)
    )
